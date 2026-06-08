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
$callback = "$scheme://$host/plugins/$folder/oauth_callback.php";

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
    ]
]);

$response = @file_get_contents(TOKEN_URL, false, $ctx);
if ($response === false) {
    header("Location: index.php?tab=navimow&oauth_error=token_request_failed");
    exit;
}

$token_data = json_decode($response, true);
$access_token  = $token_data['access_token']  ?? '';
$refresh_token = $token_data['refresh_token'] ?? '';
$expires_in    = (int)($token_data['expires_in'] ?? 3600);
$token_type    = $token_data['token_type']    ?? 'Bearer';

if (!$access_token) {
    $err_desc = $token_data['error_description'] ?? $token_data['error'] ?? 'empty_token';
    header("Location: index.php?tab=navimow&oauth_error=" . urlencode($err_desc));
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
