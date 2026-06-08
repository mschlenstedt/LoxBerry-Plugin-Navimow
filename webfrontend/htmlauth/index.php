<?php
require_once "loxberry_system.php";
require_once "loxberry_web.php";
require_once "loxberry_log.php";

$version = LBSystem::pluginversion();
$L = LBSystem::readlanguage("language.ini");

$plugincfg_raw = file_exists("$lbpconfigdir/pluginconfig.json")
    ? file_get_contents("$lbpconfigdir/pluginconfig.json")
    : '{}';
$plugincfg = json_decode($plugincfg_raw, true) ?: [];
$plugincfg += [
    'base_topic'    => 'navimow',
    'access_token'  => '',
    'refresh_token' => '',
    'expires_at'    => 0,
    'devices'       => [],
];

$tab         = isset($_GET['tab']) ? $_GET['tab'] : 'navimow';
$oauth_ok    = isset($_GET['oauth_ok']);
$oauth_error = isset($_GET['oauth_error']) ? htmlspecialchars($_GET['oauth_error']) : '';

$scheme   = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http';
$host     = $_SERVER['HTTP_HOST'] ?? 'localhost';
$folder   = basename($lbpplugindir);
$callback = urlencode("$scheme://$host/plugins/$folder/oauth_callback.php");
$oauth_authorize_url =
    "https://navimow-h5-fra.willand.com/smartHome/login?channel=homeassistant"
    . "&redirect_uri=$callback";

$navbar[10]['Name']   = 'Navimow';
$navbar[10]['URL']    = 'index.php?tab=navimow';
$navbar[10]['active'] = ($tab === 'navimow');

$navbar[20]['Name']   = 'MQTT';
$navbar[20]['URL']    = 'index.php?tab=mqtt';
$navbar[20]['active'] = ($tab === 'mqtt');

$navbar[30]['Name']   = 'Logs';
$navbar[30]['URL']    = 'index.php?tab=logs';
$navbar[30]['active'] = ($tab === 'logs');

LBWeb::lbheader("Navimow V$version", "https://github.com/mschlenstedt/LoxBerry-Plugin-Navimow", "", true);

if ($oauth_ok) {
    echo '<div class="lb-alert lb-alert-success">' . $L['OAUTH_SUCCESS'] . '</div>';
}
if ($oauth_error) {
    echo '<div class="lb-alert lb-alert-danger">' . $L['OAUTH_ERROR'] . ': ' . $oauth_error . '</div>';
}

if ($tab === 'navimow') {
    include "$lbptemplatedir/navimow_tab.html";
} elseif ($tab === 'mqtt') {
    include "$lbptemplatedir/mqtt_tab.html";
} else {
    echo LBWeb::loglist_html();
}

$ajaxcfgfile = "LBPCONFIG/" . basename($lbpconfigdir) . "/pluginconfig.json";
?>

<script>
function updateGatewayStatus() {
    fetch('ajax.cgi?action=getpid')
        .then(r => r.json())
        .then(data => {
            const el = document.getElementById('gw_status_text');
            if (!el) return;
            if (data.pid) {
                el.textContent = '<?= $L['GATEWAY_RUNNING'] ?> (PID ' + data.pid + ')';
                el.parentElement.style.cssText =
                    'background:#6dac20;color:black;border-color:#5a9a18;padding:.4rem .8rem;border-radius:4px;';
            } else {
                el.textContent = '<?= $L['GATEWAY_NOT_RUNNING'] ?>';
                el.parentElement.style.cssText =
                    'background:#d0021b;color:white;border-color:#b00218;padding:.4rem .8rem;border-radius:4px;';
            }
        })
        .catch(() => {});
}

function updateTokenStatus() {
    fetch('ajax.cgi?action=gettokenstatus')
        .then(r => r.json())
        .then(data => {
            const badge   = document.getElementById('token_badge');
            const val     = document.getElementById('token_value');
            const expires = document.getElementById('token_expires');
            if (!badge) return;
            if (data.ok) {
                badge.textContent = '<?= $L['TOKEN_AUTHENTICATED'] ?>';
                badge.className   = 'lb-badge lb-badge-success';
                val.textContent   = data.masked || '--';
                const h = Math.floor(data.expires_in / 3600);
                const m = Math.floor((data.expires_in % 3600) / 60);
                expires.textContent = h + 'h ' + m + 'm';
            } else {
                badge.textContent = '<?= $L['TOKEN_NOT_AUTHENTICATED'] ?>';
                badge.className   = 'lb-badge lb-badge-danger';
                val.textContent   = '--';
                expires.textContent = '--';
            }
        })
        .catch(() => {});
}

const btnRestart = document.getElementById('btn_restart');
if (btnRestart) {
    btnRestart.addEventListener('click', function(e) {
        e.preventDefault();
        this.classList.add('lb-btn-loading');
        fetch('ajax.cgi?action=restart')
            .then(r => r.json())
            .then(() => {
                btnRestart.classList.remove('lb-btn-loading');
                updateGatewayStatus();
            })
            .catch(() => btnRestart.classList.remove('lb-btn-loading'));
    });
}

const btnStop = document.getElementById('btn_stop');
if (btnStop) {
    btnStop.addEventListener('click', function(e) {
        e.preventDefault();
        fetch('ajax.cgi?action=stop').then(() => updateGatewayStatus());
    });
}

const btnSaveMqtt = document.getElementById('btn_save_mqtt');
if (btnSaveMqtt) {
    btnSaveMqtt.addEventListener('click', function() {
        const topic  = document.getElementById('base_topic').value.trim();
        const result = document.getElementById('save_result');
        fetch('/admin/system/tools/ajax-generic.php', {
            method:  'POST',
            headers: {'Content-Type': 'application/json'},
            body:    JSON.stringify({
                action:  'savenewvalue',
                cfgfile: '<?= $ajaxcfgfile ?>',
                key:     'base_topic',
                value:   topic,
            }),
        })
        .then(r => r.json())
        .then(data => {
            result.style.display = 'inline';
            result.textContent   = data.error ? 'Error: ' + data.error : '<?= $L['MQTT_SAVED'] ?>';
            setTimeout(() => { result.style.display = 'none'; }, 3000);
        });
    });
}

updateGatewayStatus();
updateTokenStatus();
setInterval(updateGatewayStatus, 5000);
setInterval(updateTokenStatus,   30000);
</script>

<?php LBWeb::lbfooter(); ?>
