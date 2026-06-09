<script>
function updateGatewayStatus() {
    fetch('ajax.cgi?action=getpid')
        .then(r => r.json())
        .then(data => {
            const el = document.getElementById('gw_status_text');
            if (!el) return;
            if (data.pid) {
                el.textContent = '<TMPL_VAR "GATEWAY.RUNNING"> (PID ' + data.pid + ')';
                el.style.cssText = 'flex:1;min-height:3rem;padding:0.5rem 1rem;border-radius:4px;background:#6dac20;color:black;font-weight:500;display:flex;align-items:center;';
            } else {
                el.textContent = '<TMPL_VAR "GATEWAY.NOT_RUNNING">';
                el.style.cssText = 'flex:1;min-height:3rem;padding:0.5rem 1rem;border-radius:4px;background:#d0021b;color:white;font-weight:500;display:flex;align-items:center;';
            }
        })
        .catch(() => {
            const el = document.getElementById('gw_status_text');
            if (el) {
                el.textContent = '<TMPL_VAR "GATEWAY.NOT_RUNNING">';
                el.style.cssText = 'flex:1;min-height:3rem;padding:0.5rem 1rem;border-radius:4px;background:#d0021b;color:white;font-weight:500;display:flex;align-items:center;';
            }
        });
}

function updateTokenStatus() {
    fetch('ajax.cgi?action=gettokenstatus')
        .then(r => r.json())
        .then(data => {
            const badge   = document.getElementById('token_badge');
            const val     = document.getElementById('token_value');
            const expires = document.getElementById('token_expires');
            if (!badge) return;
            val.textContent = data.masked || '--';
            if (data.ok) {
                badge.textContent = '<TMPL_VAR "TOKEN.AUTHENTICATED">';
                badge.className   = 'lb-badge lb-badge-success';
                const h = Math.floor(data.expires_in / 3600);
                const m = Math.floor((data.expires_in % 3600) / 60);
                expires.textContent = h + 'h ' + m + 'm';
            } else if (data.has_refresh) {
                badge.textContent = '<TMPL_VAR "TOKEN.EXPIRED_REFRESH">';
                badge.className   = 'lb-badge lb-badge-warning';
                expires.textContent = '--';
            } else {
                badge.textContent = '<TMPL_VAR "TOKEN.NOT_AUTHENTICATED">';
                badge.className   = 'lb-badge lb-badge-danger';
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
            .then(data => {
                btnRestart.classList.remove('lb-btn-loading');
                if (data && !data.ok && data.error) {
                    const el = document.getElementById('gw_status_text');
                    if (el) {
                        el.textContent = 'Fehler: ' + data.error;
                        el.style.cssText = 'flex:1;min-height:3rem;padding:0.5rem 1rem;border-radius:4px;background:#f5a623;color:black;font-weight:500;display:flex;align-items:center;';
                    }
                } else {
                    setTimeout(updateGatewayStatus, 1000);
                }
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
                cfgfile: '<TMPL_VAR AJAXCFGFILE>',
                key:     'base_topic',
                value:   topic,
            }),
        })
        .then(r => r.json())
        .then(data => {
            result.style.display = 'inline';
            result.textContent   = data.error ? 'Error: ' + data.error : '<TMPL_VAR "MQTT.SAVED">';
            setTimeout(() => { result.style.display = 'none'; }, 3000);
        });
    });
}

let _sdkUpdatePoll = null;

function updateSdkVersions() {
    fetch('ajax.cgi?action=sdk_versions')
        .then(r => r.json())
        .then(data => {
            const inst   = document.getElementById('sdk_installed');
            const avail  = document.getElementById('sdk_available');
            const btn    = document.getElementById('btn_sdk_update');
            const status = document.getElementById('sdk_update_status');
            if (inst)  inst.textContent  = data.installed || '?';
            if (avail) avail.textContent = data.available || '?';
            if (data.updating) {
                if (btn)    btn.disabled = true;
                if (status) status.style.display = '';
            } else {
                if (btn)    btn.disabled = false;
                if (status) status.style.display = 'none';
                if (_sdkUpdatePoll) {
                    clearInterval(_sdkUpdatePoll);
                    _sdkUpdatePoll = null;
                }
            }
        })
        .catch(() => {});
}

const btnSdkUpdate = document.getElementById('btn_sdk_update');
if (btnSdkUpdate) {
    btnSdkUpdate.addEventListener('click', function() {
        this.disabled = true;
        const status = document.getElementById('sdk_update_status');
        if (status) status.style.display = '';
        fetch('ajax.cgi?action=sdk_update')
            .then(r => r.json())
            .then(data => {
                if (data.ok) {
                    _sdkUpdatePoll = setInterval(updateSdkVersions, 2000);
                } else {
                    this.disabled = false;
                    if (status) status.style.display = 'none';
                }
            })
            .catch(() => {
                this.disabled = false;
                if (status) status.style.display = 'none';
            });
    });
}

updateGatewayStatus();
updateTokenStatus();
updateSdkVersions();
setInterval(updateGatewayStatus, 5000);
setInterval(updateTokenStatus,   30000);
</script>
