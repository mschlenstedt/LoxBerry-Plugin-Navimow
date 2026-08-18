# CLAUDE.md — Navimow-Plugin

Nur was **speziell für dieses Plugin** gilt. Allgemeine LoxBerry-V4-Regeln (Plugin-Struktur, Lifecycle-Skripte, `purge_installation()`, Logging-Architektur, Upgrade-Sicherung, LF-Zeilenenden, Anonymisierung vor Veröffentlichung) stehen in der übergeordneten `CLAUDE.md` des Arbeitsverzeichnisses.

**Dieses Repository ist öffentlich.** Seriennummern, Kontokennungen, Tokens, interne IPs und GPS-Koordinaten gehören in keine Datei hier — auch nicht in Kommentare, Commit-Messages oder eingefügte Logausgaben.

## Zwei Datenquellen — und warum das die häufigste Fehlermeldung erklärt

Der Gateway (`bin/navimow_gateway.py`) holt die Daten aus zwei völlig getrennten Kanälen. Wer das verwechselt, sucht an der falschen Stelle:

| Kanal | Liefert | Nicht enthalten |
|---|---|---|
| **REST** `POST /openapi/smarthome/getVehicleStatus` (alle 300 s) | Grundstatus, Batterie, Fehlercode | Mähfortschritt, Position — die Smarthome-Bridge kennt diese Felder **strukturell nicht** |
| **Cloud-MQTT** `wss://mqtt-fra.navimow.com` | Position (~alle 2 s beim Mähen), Mähfortschritt (tickt nur je vollem Prozentpunkt), Statistik, Live-State | — |

Symptom „Batterie kommt an, Mähfortschritt bleibt bei -1": der REST-Pfad funktioniert, der MQTT-Pfad nicht. Nie umgekehrt debuggen.

## Cloud-MQTT — vier Bedingungen, sonst kommt gar nichts

Verbindung und `SUBACK` sehen in allen vier Fehlerfällen sauber aus. Es kommt trotzdem nichts an.

1. **Client-ID muss `web_<mqtt-username>_<random>` sein** (`NavimowCloudMQTT.connect`). Der Username ist `userName` aus `/openapi/mqtt/userInfo/get/v2` — **nicht** die Login-Mail. Mit fremdem Präfix (früher `navimow_loxberry_…`) wird die Verbindung angenommen und jede Subscription bestätigt, ausgeliefert wird nichts. Gleiches Muster in `mower_sdk` (`_build_web_client_id`) und `ioBroker.navimow`. Die ID nur **maskiert** loggen, sie enthält eine Kontokennung.
2. **`KEEPALIVE = 60`, nicht 2400.** Eine leerlaufende Verbindung wird cloudseitig nach ~10 min **ohne FIN** abgeräumt; bei 2400 s fällt das dem Client erst 40 min später auf. Symptom: nach jedem Connect exakt zwei 5-Minuten-Heartbeats, dann Stille auf allen Kanälen. Der Mähbetrieb maskiert den Fehler vollständig, weil der Positionsstrom die Verbindung nie leerlaufen lässt — deshalb nur in der Ladestation reproduzierbar.
3. **Nach jedem Token-Refresh neu verbinden** (`task_token_refresh`). Der Bearer-Token geht nur beim WebSocket-Upgrade mit und ist danach für die Lebensdauer der Verbindung eingefroren; ohne Reconnect läuft sie mit abgelaufenem Token weiter und versiegt still. `update_token()` allein reicht nicht — das wirkt erst beim nächsten Connect.
4. **Keine Wildcard-Subscription neben den Kanälen.** `/downlink/vehicle/<did>/#` matcht `state|event|attributes|location` ein zweites Mal; der Broker stellt pro passender Subscription zu, jede Nachricht käme doppelt.

**Silence-Watchdog** (`task_cloud_mqtt_watchdog`): `_last_cloud_msg_time` muss mit `time.time()` initialisiert **und** in `_cb_connect` zurückgesetzt werden. Mit `0.0` gilt jede frische Verbindung sofort als „seit 1970 stumm". Gemessen mit dem alten Startwert: 3132 Connects, 2977 Watchdog-Reconnects in 3,8 Tagen, **0** empfangene Nachrichten.

Der Watchdog reconnectet **nur, wenn der Mäher laut REST aktiv ist** — in der Ladestation bleibt er absichtlich still. Deshalb ist Punkt 2 keine Redundanz, sondern der einzige Schutz im Docked-Zustand.

**Doppelte Nachrichten 1 ms auseinander** kommen von der Cloud selbst und sind kein Subscription-Fehler. Der State-Merge ist idempotent.

## Topics

Publiziert (Basis-Topic aus der Config, Default `navimow`):

| Topic | Inhalt | retained |
|---|---|---|
| `<base>/<did>/state` | Status, Batterie, Mähfortschritt, Flächen | ja |
| `<base>/<did>/location` | `postureX/Y/Theta`, `mowingPercentage`, `time` | ja |
| `<base>/<did>/mower` | Modell, Firmware, Name — einmal beim Start | ja |
| `<base>/gateway` | `state`, `authenticated`, `expires_at` — von `ajax.cgi?action=gettokenstatus` gelesen, LWT `{"state":"stopped"}` | ja |

Abonniert: `<base>/+/set` — Payload ist ein Kommandowort. Erlaubt: `start`, `stop`, `pause`, `resume`, `dock` sowie die Aliase `mow`/`go`/`run` → `start` und `home`/`return` → `dock`. Umgesetzt auf `POST /openapi/smarthome/sendCommands` mit den Google-Smarthome-Traits (`StartStop`, `PauseUnpause`, `Dock`).

**`-1` heißt „nie ein Wert eingetroffen"**, nicht „Wert ist null". Die Defaults aus `_STATE_DEFAULTS`/`_LOCATION_DEFAULTS` werden beim Start publiziert, damit Loxone sofort alle Felder kennt. Ein dauerhaftes `-1` bei Mähfortschritt/Position ist das Symptom aus dem Abschnitt oben.

`vehicleState_desc` (Text) und `state_code` (Zahl) kommen aus `_normalize_vehicle_state()`; unbekannte Cloud-Zustände landen auf `unknown`/`99` statt zu verschwinden.

## Laufzeit

- **PID-File** `/dev/shm/navimow_gateway.pid`, vom Gateway selbst geschrieben.
- **`config/gateway_stopped`** ist die Source of Truth für „soll nicht laufen" und überlebt Reboot und Upgrade. `daemon.sh stop` **setzt dieses Flag** — zum bloßen Neustarten also niemals `daemon.sh stop` verwenden, sondern die PID killen und das PID-File löschen.
- **Der Gateway läuft immer als `loxberry`**, auch beim Boot (`daemon.sh` re-exect sich per `su`). Sonst passen PID-File, Logs und WebUI-Rechte nicht zusammen.
- **Cloud-Nachrichten werden nur auf `--loglevel 7` geloggt** (`LOGDEB`). `daemon.sh` übergibt keinen Level, der Boot-Start läuft also auf 6 — bei der Fehlersuche am Cloud-Kanal den Gateway von Hand mit `--loglevel 7` starten, sonst sieht man eingehende Nachrichten überhaupt nicht.

## Fix an einem laufenden Testsystem prüfen

Ohne Plugin-Upgrade, direkt auf einem LoxBerry (`<loxberry>`):

```sh
scp bin/navimow_gateway.py loxberry@<loxberry>:/tmp/navimow_gateway.py.new
ssh loxberry@<loxberry> '
  python3 -m py_compile /tmp/navimow_gateway.py.new || exit 1
  install -m 755 /tmp/navimow_gateway.py.new /opt/loxberry/bin/plugins/navimow/navimow_gateway.py
  PID=$(cat /dev/shm/navimow_gateway.pid); kill "$PID"; sleep 4; rm -f /dev/shm/navimow_gateway.pid
  setsid python3 /opt/loxberry/bin/plugins/navimow/navimow_gateway.py \
      --logfile /opt/loxberry/log/plugins/navimow/navimow_gateway.log \
      --logdbkey 0 --configdir /opt/loxberry/config/plugins/navimow \
      --lbsconfig /opt/loxberry/config/system --loglevel 7 </dev/null >/dev/null 2>&1 &'
```

- **`setsid` mit umgeleitetem stdio ist Pflicht**, sonst hängt die SSH-Sitzung bis zum Timeout, weil der Python-Prozess ihre Deskriptoren erbt.
- Verifikation läuft am besten über einen zweiten Kanal: `mosquitto_sub -t 'navimow/#' -v` mitschreiben lassen. Das zeigt, was tatsächlich bei Loxone ankäme, unabhängig vom Loglevel.
- **Geduld beim Docked-Test:** die erste Cloud-Nachricht kam nach dem Fix erst nach 8 Minuten. Ein 2-Minuten-Test beweist nichts.
- `pgrep -af mosquitto_sub` zeigt das Broker-Passwort im Klartext — nicht in Ausgaben kopieren, die irgendwo landen.

## Referenzimplementierungen

Bei Cloud-Verhalten immer gegenlesen, statt zu raten — beide sprechen mit derselben Cloud:

- `ioBroker.navimow` (TA2k) — hat die Keepalive-Messung und das Client-ID-Muster dokumentiert.
- `mower_sdk` / `NavimowHA` — Topic-Struktur und Client-ID-Aufbau.
