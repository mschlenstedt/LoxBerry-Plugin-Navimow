#!/bin/bash
# LoxBerry calls this at boot with PLUGINNAME set to the NAME from plugin.cfg.
# LBHOMEDIR and LBSCONFIG are set in /etc/environment.
#
# The gateway must ALWAYS run as the 'loxberry' user so that its PID file,
# its log files and the WebUI (ajax.cgi — also loxberry) stay owner-consistent.
# At boot this script runs as root, so re-exec ourselves as loxberry first.
# (--preserve-environment keeps PLUGINNAME, LBHOMEDIR, LBSCONFIG, ...)
if [ "$(id -u)" = "0" ]; then
    exec su loxberry --preserve-environment -c "$0 $*"
fi

ACTION="${1:-start}"

# The daemon file is named exactly after the plugin folder, so derive it from
# our own path. The old plugindatabase.dat lookup fails: that file is pipe-
# delimited (or empty of data lines) and never matched NAME=/FOLDER= patterns,
# leaving PLUGIN_FOLDER empty -> exit 1 -> gateway never started at boot.
PLUGIN_FOLDER=$(basename "$0")

LBPBINDIR="${LBHOMEDIR}/bin/plugins/${PLUGIN_FOLDER}"
LBPCONFIGDIR="${LBHOMEDIR}/config/plugins/${PLUGIN_FOLDER}"
LBPLOGDIR="${LBHOMEDIR}/log/plugins/${PLUGIN_FOLDER}"
GATEWAY="${LBPBINDIR}/navimow_gateway.py"
PIDFILE="/dev/shm/navimow_gateway.pid"
STOPPED_FLAG="${LBPCONFIGDIR}/gateway_stopped"

case "$ACTION" in
  start)
    # Do not start if the gateway was manually stopped via the WebUI
    if [ -f "$STOPPED_FLAG" ]; then
        logger "Navimow: gateway_stopped flag set — not starting"
        exit 0
    fi

    if [ ! -f "$GATEWAY" ]; then
        logger "Navimow: gateway not found at $GATEWAY"
        exit 1
    fi

    mkdir -p "$LBPLOGDIR"

    # Register log entry in LoxBerry log database and get filename + dbkey
    read LOGFILE LOGDBKEY < <(perl -e "
        use LoxBerry::Log;
        my \$log = LoxBerry::Log->new(name => 'gateway', package => '${LBHOMEDIR}/data/plugins/${PLUGIN_FOLDER}', addtime => 1);
        \$log->LOGSTART('Navimow Gateway starting (boot)');
        print \$log->{filename} . ' ' . (\$log->{dbkey} // 0) . \"\n\";
    ")

    if [ -z "$LOGFILE" ]; then
        LOGFILE="${LBPLOGDIR}/navimow_gateway.log"
        LOGDBKEY="0"
    fi

    python3 "$GATEWAY" \
        --logfile    "$LOGFILE" \
        --logdbkey   "$LOGDBKEY" \
        --configdir  "$LBPCONFIGDIR" \
        --lbsconfig  "$LBSCONFIG" \
        &

    logger "Navimow: gateway started (PID $!)"
    ;;

  stop)
    # Persist the stop so the gateway stays down across reboots
    touch "$STOPPED_FLAG"
    if [ -f "$PIDFILE" ]; then
        kill "$(cat "$PIDFILE")" 2>/dev/null
        rm -f "$PIDFILE"
        logger "Navimow: gateway stopped"
    else
        logger "Navimow: gateway not running"
    fi
    ;;

  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
        echo "running $(cat "$PIDFILE")"
    else
        echo "stopped"
    fi
    ;;

  *)
    echo "Usage: $0 {start|stop|status}"
    exit 1
    ;;
esac

exit 0
