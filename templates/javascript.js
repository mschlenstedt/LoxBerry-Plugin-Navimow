<script>
(function () {
'use strict';

/* ---------- MQTT-Tab: Basis-Topic speichern ---------- */
const btnSaveMqtt = document.getElementById('btn_save_mqtt');
if (btnSaveMqtt) {
    btnSaveMqtt.addEventListener('click', function () {
        const topic  = document.getElementById('base_topic').value.trim();
        const result = document.getElementById('save_result');
        btnSaveMqtt.disabled = true;
        fetch('/admin/system/tools/ajax-generic.php', {
            method:  'POST',
            headers: {'Content-Type': 'application/json'},
            body:    JSON.stringify({
                action:  'savenewvalue',
                cfgfile: '<TMPL_VAR AJAXCFGFILE ESCAPE=JS>',
                key:     'base_topic',
                value:   topic,
            }),
        })
        .then(r => r.json())
        .then(data => {
            result.style.display = 'inline';
            result.textContent   = data.error ? 'Error: ' + data.error : '<TMPL_VAR "MQTT.SAVED" ESCAPE=JS>';
            setTimeout(() => { result.style.display = 'none'; }, 3000);
        })
        .finally(() => { btnSaveMqtt.disabled = false; });
    });
}

/* ---------- Navimow-Tab ---------- */
const root = document.getElementById('nm_root');
if (!root) return;

const L = {
    GW_RUNNING:      '<TMPL_VAR "GATEWAY.RUNNING" ESCAPE=JS>',
    GW_STOPPED:      '<TMPL_VAR "GATEWAY.NOT_RUNNING" ESCAPE=JS>',
    GW_RESTARTING:   '<TMPL_VAR "GATEWAY.RESTARTING" ESCAPE=JS>',
    GW_STOPPING:     '<TMPL_VAR "GATEWAY.STOPPING" ESCAPE=JS>',
    GW_DESC_RUN:     '<TMPL_VAR "GATEWAY.DESC_RUNNING" ESCAPE=JS>',
    GW_DESC_STOP:    '<TMPL_VAR "GATEWAY.DESC_STOPPED" ESCAPE=JS>',
    GW_ERR:          '<TMPL_VAR "GATEWAY.ERR_ACTION" ESCAPE=JS>',
    OFF_OK:          '<TMPL_VAR "TOKEN.AUTHENTICATED" ESCAPE=JS>',
    OFF_NONE:        '<TMPL_VAR "TOKEN.NOT_AUTHENTICATED" ESCAPE=JS>',
    OFF_RENEW:       '<TMPL_VAR "TOKEN.EXPIRED_REFRESH" ESCAPE=JS>',
    OFF_GW_STOPPED:  '<TMPL_VAR "TOKEN.GATEWAY_STOPPED" ESCAPE=JS>',
    OFF_VALID_FOR:   '<TMPL_VAR "TOKEN.VALID_FOR" ESCAPE=JS>',
    OFF_AUTO:        '<TMPL_VAR "TOKEN.AUTO_RENEW" ESCAPE=JS>',
    OFF_EXPIRED:     '<TMPL_VAR "TOKEN.EXPIRED_HINT" ESCAPE=JS>',
    OFF_NOT_AUTH:    '<TMPL_VAR "TOKEN.NOT_AUTH_HINT" ESCAPE=JS>',
    OFF_BTN:         '<TMPL_VAR "TOKEN.BTN_AUTHENTICATE" ESCAPE=JS>',
    OFF_BTN_FIRST:   '<TMPL_VAR "TOKEN.BTN_AUTHENTICATE_FIRST" ESCAPE=JS>',
    HINT:            '<TMPL_VAR "UNOFFICIAL.HINT" ESCAPE=JS>',
    WARN_APP:        '<TMPL_VAR "UNOFFICIAL.WARN_APP" ESCAPE=JS>',
    EMAIL:           '<TMPL_VAR "UNOFFICIAL.LABEL_EMAIL" ESCAPE=JS>',
    PASSWORD:        '<TMPL_VAR "UNOFFICIAL.LABEL_PASSWORD" ESCAPE=JS>',
    BTN_CONNECT:     '<TMPL_VAR "UNOFFICIAL.BTN_CONNECT" ESCAPE=JS>',
    BTN_RETRY:       '<TMPL_VAR "UNOFFICIAL.BTN_RETRY" ESCAPE=JS>',
    BTN_WORKING:     '<TMPL_VAR "UNOFFICIAL.BTN_WORKING" ESCAPE=JS>',
    BTN_LOGOUT:      '<TMPL_VAR "UNOFFICIAL.BTN_LOGOUT" ESCAPE=JS>',
    BTN_LOGOUT_OK:   '<TMPL_VAR "UNOFFICIAL.BTN_LOGOUT_CONFIRM" ESCAPE=JS>',
    BTN_CANCEL:      '<TMPL_VAR "UNOFFICIAL.BTN_CANCEL" ESCAPE=JS>',
    BTN_SAVE_MAP:    '<TMPL_VAR "UNOFFICIAL.BTN_SAVE_MAP" ESCAPE=JS>',
    BTN_SAVING:      '<TMPL_VAR "UNOFFICIAL.BTN_SAVING" ESCAPE=JS>',
    CONFIRM_LOGOUT:  '<TMPL_VAR "UNOFFICIAL.CONFIRM_LOGOUT" ESCAPE=JS>',
    STEPS: ['<TMPL_VAR "UNOFFICIAL.STEP_1" ESCAPE=JS>', '<TMPL_VAR "UNOFFICIAL.STEP_2" ESCAPE=JS>', '<TMPL_VAR "UNOFFICIAL.STEP_3" ESCAPE=JS>'],
    ST_CONNECTED:    '<TMPL_VAR "UNOFFICIAL.STATUS_CONNECTED" ESCAPE=JS>',
    ST_NONE:         '<TMPL_VAR "UNOFFICIAL.STATUS_NOT_CONNECTED" ESCAPE=JS>',
    ST_WORKING:      '<TMPL_VAR "UNOFFICIAL.STATUS_WORKING" ESCAPE=JS>',
    ST_STARTING:     '<TMPL_VAR "UNOFFICIAL.STATUS_STARTING" ESCAPE=JS>',
    ST_ERROR:        '<TMPL_VAR "UNOFFICIAL.STATUS_ERROR" ESCAPE=JS>',
    ST_MAP:          '<TMPL_VAR "UNOFFICIAL.STATUS_MAP" ESCAPE=JS>',
    SH_NONE:         '<TMPL_VAR "UNOFFICIAL.SHORT_NONE" ESCAPE=JS>',
    SH_CONNECTED:    '<TMPL_VAR "UNOFFICIAL.SHORT_CONNECTED" ESCAPE=JS>',
    SH_MAP:          '<TMPL_VAR "UNOFFICIAL.SHORT_MAP" ESCAPE=JS>',
    SH_ERROR:        '<TMPL_VAR "UNOFFICIAL.SHORT_ERROR" ESCAPE=JS>',
    SH_STARTING:     '<TMPL_VAR "UNOFFICIAL.SHORT_STARTING" ESCAPE=JS>',
    OK_CONNECTED:    '<TMPL_VAR "UNOFFICIAL.OK_CONNECTED" ESCAPE=JS>',
    LBL_SINCE:       '<TMPL_VAR "UNOFFICIAL.LABEL_SINCE" ESCAPE=JS>',
    LBL_TOPIC:       '<TMPL_VAR "UNOFFICIAL.LABEL_TOPIC" ESCAPE=JS>',
    LBL_MOWER:       '<TMPL_VAR "UNOFFICIAL.LABEL_MOWER" ESCAPE=JS>',
    LBL_ZONES:       '<TMPL_VAR "UNOFFICIAL.LABEL_ZONES" ESCAPE=JS>',
    ZONES_NONE:      '<TMPL_VAR "UNOFFICIAL.ZONES_NONE" ESCAPE=JS>',
    MAP_HINT:        '<TMPL_VAR "UNOFFICIAL.MAP_HINT" ESCAPE=JS>',
    MAP_LABEL:       '<TMPL_VAR "UNOFFICIAL.MAP_LABEL" ESCAPE=JS>',
    MAP_CHOOSE:      '<TMPL_VAR "UNOFFICIAL.MAP_CHOOSE" ESCAPE=JS>',
    ERR_EMAIL:       '<TMPL_VAR "UNOFFICIAL.ERR_REQUIRED_EMAIL" ESCAPE=JS>',
    ERR_PW:          '<TMPL_VAR "UNOFFICIAL.ERR_REQUIRED_PW" ESCAPE=JS>',
    ERR_BADPW:       '<TMPL_VAR "UNOFFICIAL.ERR_BADPW" ESCAPE=JS>',
    ERR_NOACCOUNT:   '<TMPL_VAR "UNOFFICIAL.ERR_NOACCOUNT" ESCAPE=JS>',
    ERR_NETWORK:     '<TMPL_VAR "UNOFFICIAL.ERR_NETWORK" ESCAPE=JS>',
    ERR_LOGIN:       '<TMPL_VAR "UNOFFICIAL.ERR_LOGIN_FAILED" ESCAPE=JS>',
    ERR_SESSION:     '<TMPL_VAR "UNOFFICIAL.ERR_SESSION" ESCAPE=JS>',
    ERR_TIMEOUT:     '<TMPL_VAR "UNOFFICIAL.ERR_TIMEOUT" ESCAPE=JS>',
    ERR_RESTART:     '<TMPL_VAR "UNOFFICIAL.ERR_RESTART" ESCAPE=JS>',
    ERR_REQUEST:     '<TMPL_VAR "UNOFFICIAL.ERR_REQUEST" ESCAPE=JS>',
    DONE_LOGOUT:     '<TMPL_VAR "UNOFFICIAL.DONE_LOGOUT" ESCAPE=JS>',
    DONE_MAP:        '<TMPL_VAR "UNOFFICIAL.DONE_MAP" ESCAPE=JS>',
};

const S = {
    busy: false,
    gw:  { pid: null, phase: '' },            // phase: '' | 'restarting' | 'stopping'
    gwError: '',
    off: { ok: 0, expires_in: 0, has_refresh: 0 },
    un:  null,                                // letzte Antwort von getunofficialstatus
    flow: '',                                 // '' | 'login' | 'logout' | 'map'
    steps: ['pending', 'pending', 'pending'],
    err: '', notice: '', fieldErr: '',
    email: '', pw: '', map: '', confirmLogout: false,
};
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const live = (msg) => { $('nm_live').textContent = msg; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const getJSON = (url) => fetch(url, { cache: 'no-store' }).then((r) => r.json());
const postJSON = (params) => fetch('ajax.cgi', { method: 'POST', body: new URLSearchParams(params) }).then((r) => r.json());

/* ---------- Statusableitungen ---------- */
function gwRunning() { return !!S.gw.pid && !S.gw.phase; }

function unofficialView() {
    const u = S.un || {};
    if (S.flow === 'login') return 'working';
    if (S.flow === 'logout' || S.flow === 'map') return 'busy';
    if (!u.enabled) return S.err ? 'error' : 'none';
    if (!gwRunning()) return 'gwdown';
    if (u.ok) {
        const devices = u.devices || [], mapping = u.mapping || [];
        return (devices.length > 0 && mapping.length < devices.length && (u.vehicles || []).length > 1) ? 'map' : 'connected';
    }
    if (u.error || S.err) return 'error';
    return 'starting';
}

function setPill(id, kind, text, spinning) {
    const el = $(id);
    if (!el) return;
    el.className = 'nm-pill ' + kind + (spinning ? ' spin' : '');
    el.textContent = text;
    el.title = text;
}

function fmtDuration(sec) {
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
    return h > 0 ? h + ' h ' + m + ' min' : m + ' min';
}
function fmtSince(epoch) {
    return epoch ? new Date(epoch * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '–';
}

/* ---------- Rendern ---------- */
function renderGateway() {
    const restart = $('nm_btn_restart'), stop = $('nm_btn_stop'), start = $('nm_btn_start');
    let desc = S.gwError || L.GW_DESC_RUN;
    if (S.gw.phase === 'restarting') setPill('nm_gw_pill', 'info', L.GW_RESTARTING, true);
    else if (S.gw.phase === 'stopping') setPill('nm_gw_pill', 'info', L.GW_STOPPING, true);
    else if (S.gw.pid) setPill('nm_gw_pill', 'ok', L.GW_RUNNING + ' · PID ' + S.gw.pid);
    else { setPill('nm_gw_pill', 'err', L.GW_STOPPED); desc = S.gwError || L.GW_DESC_STOP; }
    $('nm_gw_desc').textContent = desc;
    const stopped = !S.gw.pid && !S.gw.phase;
    restart.hidden = stopped; stop.hidden = stopped; start.hidden = !stopped;
    [restart, stop, start].forEach((b) => { b.disabled = S.busy; });
    restart.innerHTML = (S.gw.phase === 'restarting' ? '<span class="nm-spinner" aria-hidden="true"></span>' + esc(L.GW_RESTARTING) : esc('<TMPL_VAR "GATEWAY.RESTART" ESCAPE=JS>'));
}

function renderOfficial() {
    let kind, text, valid, primary = false;
    if (!gwRunning()) { kind = ''; text = L.OFF_GW_STOPPED; valid = '–'; }
    else if (S.off.ok) { kind = 'ok'; text = L.OFF_OK; valid = L.OFF_VALID_FOR + ' ' + fmtDuration(S.off.expires_in) + ' · ' + L.OFF_AUTO; }
    else if (S.off.has_refresh) { kind = 'warn'; text = L.OFF_RENEW; valid = L.OFF_EXPIRED; }
    else { kind = 'err'; text = L.OFF_NONE; valid = L.OFF_NOT_AUTH; primary = true; }
    setPill('nm_off_pill', kind, text);
    setPill('nm_off_pill2', kind, text);
    $('nm_off_valid').textContent = valid;
    const oauth = $('nm_btn_oauth');
    oauth.textContent = primary ? L.OFF_BTN_FIRST : L.OFF_BTN;
    oauth.classList.toggle('lb-btn-primary', primary);
    oauth.classList.toggle('lb-disabled', S.busy);
    oauth.setAttribute('aria-disabled', String(S.busy));
}

function stepsHtml() {
    return '<ol class="nm-steps">' + L.STEPS.map((t, i) => {
        const st = S.steps[i];
        const mark = st === 'done' ? '✓' : st === 'fail' ? '!' : st === 'active' ? '' : String(i + 1);
        return '<li class="' + st + '"><span class="nm-mark">' + mark + '</span><span>' + esc(t) + '</span></li>';
    }).join('') + '</ol>';
}

function btn(act, label, cls, opts) {
    opts = opts || {};
    return '<button type="button" class="lb-btn lb-btn-sm ' + (cls || '') + '" data-nm="' + act + '"' + (opts.disabled ? ' disabled' : '') + '>' +
        (opts.spin ? '<span class="nm-spinner" aria-hidden="true"></span>' : '') + esc(label) + '</button>';
}

function unofficialSignature(view) {
    const u = S.un || {};
    return [view, S.busy, S.steps.join(), S.err, S.notice, S.fieldErr, S.confirmLogout, S.flow, S.map,
            u.error, u.since, JSON.stringify(u.mapping || []), JSON.stringify(u.vehicles || []), u.zones_text, (S.un ? S.un.base_topic : '')].join('|');
}
let lastSig = '';

function renderUnofficial() {
    const u = S.un || {};
    const view = unofficialView();
    const pills = {
        working:   ['info', L.ST_WORKING, true],
        busy:      ['info', L.GW_RESTARTING, true],
        connected: ['ok', L.ST_CONNECTED],
        map:       ['warn', L.ST_MAP],
        error:     ['err', L.ST_ERROR],
        starting:  ['info', L.ST_STARTING, true],
        gwdown:    ['', L.OFF_GW_STOPPED],
        none:      ['', L.ST_NONE],
    }[view];
    setPill('nm_un_pill', pills[0], pills[1], pills[2]);
    setPill('nm_un_pill2', pills[0], pills[1], pills[2]);
    $('nm_un_short').textContent = {
        working: L.ST_WORKING, busy: L.GW_RESTARTING, connected: L.SH_CONNECTED + ' ' + fmtSince(u.since),
        map: L.SH_MAP, error: L.SH_ERROR, starting: L.SH_STARTING, gwdown: L.GW_DESC_STOP, none: L.SH_NONE,
    }[view];

    const sig = unofficialSignature(view);
    if (sig === lastSig) return;
    lastSig = sig;

    const body = $('nm_un_body'), foot = $('nm_un_foot');
    const focused = document.activeElement && document.activeElement.id;
    let html = '', actions = '';
    const notice = S.notice ? '<div class="nm-note ok" role="status"><b class="nm-ico">✓</b><span>' + esc(S.notice) + '</span></div>' : '';

    if (view === 'connected') {
        const base = u.base_topic || root.dataset.base || 'navimow';
        const dev = (u.mapping && u.mapping[0] && u.mapping[0].device_id) || '&lt;device_id&gt;';
        html = notice + '<div class="nm-note ok"><b class="nm-ico">✓</b><span>' + esc(L.OK_CONNECTED) + '</span></div>' +
            '<div class="nm-note warn"><b class="nm-ico">!</b><span>' + esc(L.WARN_APP) + '</span></div>' +
            '<dl class="nm-kv"><dt>' + esc(L.LBL_SINCE) + '</dt><dd>' + esc(fmtSince(u.since)) + '</dd>' +
            '<dt>' + esc(L.LBL_ZONES) + '</dt><dd>' + esc(u.zones_text || L.ZONES_NONE) + '</dd>' +
            '<dt>' + esc(L.LBL_TOPIC) + '</dt><dd class="nm-mono">' + esc(base) + '/' + (dev === '&lt;device_id&gt;' ? dev : esc(dev)) + '/set_unofficial</dd></dl>';
        actions = S.confirmLogout
            ? '<span class="nm-desc">' + esc(L.CONFIRM_LOGOUT) + '</span>' + btn('logout-cancel', L.BTN_CANCEL) + btn('logout-confirm', L.BTN_LOGOUT_OK, 'lb-btn-danger')
            : btn('logout', L.BTN_LOGOUT, 'lb-btn-danger', { disabled: S.busy });
    } else if (view === 'map') {
        const dev = (u.devices || [])[0] || {};
        const opts = (u.vehicles || []).map((v) => '<option value="' + esc(v.vehicle_sn) + '"' + (S.map === v.vehicle_sn ? ' selected' : '') + '>' +
            esc((v.name ? v.name + ' · ' : '') + v.vehicle_sn) + '</option>').join('');
        html = '<div class="nm-note warn"><b class="nm-ico">!</b><span>' + esc(L.MAP_HINT) + '</span></div>' +
            '<div class="nm-field"><label for="nm_map">' + esc(L.MAP_LABEL + ' ' + (dev.name || dev.device_id || '')) + '</label>' +
            '<select class="lb-select" id="nm_map" data-bind="map"' + (S.busy ? ' disabled' : '') + '><option value="">' + esc(L.MAP_CHOOSE) + '</option>' + opts + '</select></div>';
        if (S.err) html = '<div class="nm-note err" role="alert"><b class="nm-ico">!</b><span>' + esc(S.err) + '</span></div>' + html;
        actions = btn('save-map', S.flow === 'map' ? L.BTN_SAVING : L.BTN_SAVE_MAP, 'lb-btn-primary', { disabled: S.busy || !S.map, spin: S.flow === 'map' });
    } else if (view === 'starting' || view === 'busy') {
        html = '<p class="nm-hint">' + esc(L.SH_STARTING) + '…</p>';
    } else if (view === 'gwdown') {
        html = '<p class="nm-hint">' + esc(L.GW_DESC_STOP) + '</p>';
    } else {
        const errText = S.err || (u.error ? L.ERR_SESSION + ' ' + u.error : '');
        const dis = S.busy ? ' disabled' : '';
        html = notice + '<p class="nm-hint">' + esc(L.HINT) + '</p>' +
            '<div class="nm-note warn"><b class="nm-ico">!</b><span>' + esc(L.WARN_APP) + '</span></div>' +
            (errText ? '<div class="nm-note err" role="alert"><b class="nm-ico">!</b><span>' + esc(errText) + '</span></div>' : '') +
            '<div class="nm-form">' +
            '<div class="nm-field"><label for="nm_email">' + esc(L.EMAIL) + '</label>' +
            '<input class="lb-input" type="email" id="nm_email" data-bind="email" autocomplete="username" value="' + esc(S.email) + '"' + dis +
            (S.fieldErr === 'email' ? ' aria-invalid="true"' : '') + '></div>' +
            '<div class="nm-field"><label for="nm_pw">' + esc(L.PASSWORD) + '</label>' +
            '<input class="lb-input" type="password" id="nm_pw" data-bind="pw" autocomplete="current-password" value="' + esc(S.pw) + '"' + dis +
            (S.fieldErr === 'pw' ? ' aria-invalid="true"' : '') + '></div></div>' +
            (S.fieldErr ? '<p class="nm-fielderr">' + esc(S.fieldErr === 'email' ? L.ERR_EMAIL : L.ERR_PW) + '</p>' : '') +
            (view === 'working' || S.steps.some((s) => s !== 'pending') ? stepsHtml() : '');
        actions = view === 'working'
            ? btn('login', L.BTN_WORKING, 'lb-btn-primary', { disabled: true, spin: true })
            : btn('login', view === 'error' ? L.BTN_RETRY : L.BTN_CONNECT, 'lb-btn-primary', { disabled: S.busy });
    }
    body.innerHTML = html;
    foot.innerHTML = actions;
    if (focused && $(focused) && !$(focused).disabled) $(focused).focus();
}

function render() { renderGateway(); renderOfficial(); renderUnofficial(); }

/* ---------- Daten holen ---------- */
async function refreshGateway() {
    try { const d = await getJSON('ajax.cgi?action=getpid'); S.gw.pid = d.pid || null; } catch (e) { S.gw.pid = null; }
}
async function refreshOfficial() {
    try { const d = await getJSON('ajax.cgi?action=gettokenstatus'); S.off = d; } catch (e) { /* letzter Stand bleibt */ }
}
async function refreshUnofficial() {
    try { S.un = await getJSON('ajax.cgi?action=getunofficialstatus'); } catch (e) { /* letzter Stand bleibt */ }
}
async function refreshAll() {
    await Promise.all([refreshGateway(), refreshOfficial(), refreshUnofficial()]);
    render();
}

/* Wartet, bis der neu gestartete Gateway seinen Status meldet (höchstens 30 s). */
async function waitForGateway(sinceTs, done) {
    const until = Date.now() + 30000;
    while (Date.now() < until) {
        await sleep(1500);
        await refreshUnofficial();
        const u = S.un || {};
        if (u.state === 'running' && u.ts >= sinceTs && done(u)) return true;
    }
    return false;
}

function errorText(code, msg) {
    if (code === '90014') return L.ERR_BADPW;
    if (code === '00002') return L.ERR_NOACCOUNT;
    if (code === 'network') return L.ERR_NETWORK;
    if (code === 'required') return L.ERR_EMAIL;
    return L.ERR_LOGIN + ' ' + [code, msg].filter(Boolean).join(': ');
}

function begin(flow) {
    S.busy = true; S.flow = flow; S.err = ''; S.notice = ''; S.confirmLogout = false;
    render();
}
async function finish(msg) {
    S.busy = false; S.flow = '';
    await Promise.all([refreshGateway(), refreshOfficial()]);
    render();
    if (msg) live(msg);
}

/* ---------- Abläufe ---------- */
async function login() {
    S.fieldErr = !S.email.trim() ? 'email' : !S.pw ? 'pw' : '';
    if (S.fieldErr) { lastSig = ''; render(); $(S.fieldErr === 'email' ? 'nm_email' : 'nm_pw').focus(); return; }
    S.steps = ['active', 'pending', 'pending'];
    begin('login');
    live(L.STEPS[0]);
    let res;
    try {
        res = await postJSON({ action: 'unofficiallogin', email: S.email.trim(), password: S.pw });
    } catch (e) {
        S.steps = ['fail', 'pending', 'pending']; S.err = L.ERR_REQUEST;
        return finish(S.err);
    }
    if (!res.ok) {
        S.steps = ['fail', 'pending', 'pending']; S.err = errorText(res.code, res.error);
        if (res.code === '90014') S.pw = '';
        await finish(S.err);
        const pw = $('nm_pw'); if (pw) pw.focus();
        return;
    }
    S.steps = ['done', res.restarted ? 'done' : 'fail', res.restarted ? 'active' : 'pending'];
    if (!res.restarted) { S.err = L.ERR_RESTART; return finish(S.err); }
    S.pw = '';
    render(); live(L.STEPS[2]);
    const ok = await waitForGateway(res.ts, (u) => u.ok || !!u.error);
    const u = S.un || {};
    if (!ok) { S.steps = ['done', 'done', 'fail']; S.err = L.ERR_TIMEOUT; return finish(S.err); }
    if (!u.ok) { S.steps = ['done', 'done', 'fail']; S.err = L.ERR_SESSION + ' ' + u.error; return finish(S.err); }
    S.steps = ['pending', 'pending', 'pending'];
    finish(L.OK_CONNECTED);
}

async function logout() {
    begin('logout');
    let res;
    try { res = await postJSON({ action: 'unofficiallogout' }); } catch (e) { S.err = L.ERR_REQUEST; return finish(S.err); }
    if (!res.ok) { S.err = res.error || L.ERR_REQUEST; return finish(S.err); }
    await waitForGateway(res.ts, (st) => !st.enabled);
    S.email = ''; S.pw = ''; S.steps = ['pending', 'pending', 'pending'];
    S.notice = L.DONE_LOGOUT;
    finish(L.DONE_LOGOUT);
}

async function saveMap() {
    const dev = ((S.un || {}).devices || [])[0];
    if (!dev || !S.map) return;
    begin('map');
    let res;
    try { res = await postJSON({ action: 'unofficialmap', device_id: dev.device_id, vehicle_sn: S.map }); }
    catch (e) { S.err = L.ERR_REQUEST; return finish(S.err); }
    if (!res.ok) { S.err = res.error || L.ERR_REQUEST; return finish(S.err); }
    const ok = await waitForGateway(res.ts, (u) => u.ok || !!u.error);
    if (!ok) { S.err = L.ERR_TIMEOUT; return finish(S.err); }
    S.notice = L.DONE_MAP;
    finish(L.DONE_MAP);
}

async function gatewayAction(action) {
    S.busy = true; S.gwError = ''; S.gw.phase = action === 'stop' ? 'stopping' : 'restarting';
    render();
    try {
        const res = await getJSON('ajax.cgi?action=' + action);
        if (action !== 'stop' && res && !res.ok) S.gwError = L.GW_ERR + (res.error ? ' (' + res.error + ')' : '');
    } catch (e) { S.gwError = L.GW_ERR; }
    S.gw.phase = '';
    await refreshAll();
    S.busy = false;
    render();
    live(S.gwError || (S.gw.pid ? L.GW_RUNNING : L.GW_STOPPED));
}

/* ---------- Ereignisse ---------- */
root.addEventListener('click', (e) => {
    const oauth = e.target.closest('#nm_btn_oauth');
    if (oauth && S.busy) { e.preventDefault(); return; }
    if (e.target.closest('#nm_btn_restart')) return gatewayAction('restart');
    if (e.target.closest('#nm_btn_start'))   return gatewayAction('restart');
    if (e.target.closest('#nm_btn_stop'))    return gatewayAction('stop');
    const t = e.target.closest('[data-nm]');
    if (!t || t.disabled) return;
    switch (t.dataset.nm) {
        case 'login': login(); break;
        case 'logout': S.confirmLogout = true; render(); break;
        case 'logout-cancel': S.confirmLogout = false; render(); break;
        case 'logout-confirm': logout(); break;
        case 'save-map': saveMap(); break;
    }
});
root.addEventListener('input', (e) => {
    const k = e.target.dataset && e.target.dataset.bind;
    if (!k) return;
    S[k] = e.target.value;
    if (S.fieldErr) { S.fieldErr = ''; e.target.removeAttribute('aria-invalid'); }
    if (k === 'map') render();
});
root.addEventListener('change', (e) => {
    if (e.target.dataset && e.target.dataset.bind === 'map') { S.map = e.target.value; render(); }
});
root.addEventListener('keydown', (e) => {
    const k = e.target.dataset && e.target.dataset.bind;
    if (e.key === 'Enter' && (k === 'email' || k === 'pw') && !S.busy) { e.preventDefault(); login(); }
});

refreshAll();
setInterval(() => { if (!S.busy) refreshAll(); }, 5000);
})();
</script>
