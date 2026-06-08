<?php
require_once "loxberry_system.php";

define('TOKEN_URL',    'https://navimow-fra.ninebot.com/openapi/oauth/getAccessToken');
define('CLIENT_ID',    'homeassistant');
define('CLIENT_SECRET','57056e15-722e-42be-bbaa-b0cbfb208a52');

$code  = isset($_GET['code'])  ? trim($_GET['code'])  : '';
$error = isset($_GET['error']) ? trim($_GET['error']) : '';

if ($error) {
    header("Location: index.php?tab=navimow&oauth_error=" . urlencode($error));
    exit;
}
if (!$code) {
    header("Location: index.php?tab=navimow&oauth_error=no_code");
    exit;
}

$scheme   = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http';
$host     = $_SERVER['HTTP_HOST'] ?? 'localhost';
$folder   = basename($lbpplugindir);
$callback = "$scheme://$host/admin/plugins/$folder/oauth_callback.php";

$post_data = json_encode([
    'grant_type'    => 'authorization_code',
    'code'          => $code,
    'redirect_uri'  => $callback,
    'client_id'     => CLIENT_ID,
    'client_secret' => CLIENT_SECRET,
]);

$ctx = stream_context_create([
    'http' => [
        'method'  => 'POST',
        'header'  => "Content-Type: application/json\r\nContent-Length: " . strlen($post_data),
        'content' => $post_data,
        'timeout' => 15,
        'ignore_errors' => true,
    ]
]);

$response = @file_get_contents(TOKEN_URL, false, $ctx);
if ($response === false) {
    header("Location: index.php?tab=navimow&oauth_error=" . urlencode('token_request_failed'));
    exit;
}

$token_data = json_decode($response, true);
if (!is_array($token_data)) {
    header("Location: index.php?tab=navimow&oauth_error=" . urlencode('invalid_response: ' . substr($response, 0, 100)));
    exit;
}

// Some Navimow API responses wrap data in a nested structure
$payload = $token_data;
if (isset($token_data['data']) && is_array($token_data['data'])) {
    $payload = $token_data['data'];
}

$access_token  = $payload['access_token']  ?? '';
$refresh_token = $payload['refresh_token'] ?? '';
$expires_in    = (int)($payload['expires_in'] ?? 3600);
$token_type    = $payload['token_type']    ?? 'Bearer';

if (!$access_token) {
    $err_msg = $payload['error_description']
        ?? $payload['error']
        ?? $token_data['desc']
        ?? $token_data['error_description']
        ?? $token_data['error']
        ?? ('empty_token: ' . substr($response, 0, 200));
    header("Location: index.php?tab=navimow&oauth_error=" . urlencode($err_msg));
    exit;
}

$cfg_path = "$lbpconfigdir/pluginconfig.json";
$cfg = [];
if (file_exists($cfg_path)) {
    $cfg = json_decode(file_get_contents($cfg_path), true) ?: [];
}
$cfg['access_token']  = $access_token;
$cfg['refresh_token'] = $refresh_token;
$cfg['expires_at']    = time() + $expires_in;
$cfg['token_type']    = $token_type;

$tmp = $cfg_path . '.tmp';
file_put_contents($tmp, json_encode($cfg, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
rename($tmp, $cfg_path);

header("Location: index.php?tab=navimow&oauth_ok=1");
exit;
