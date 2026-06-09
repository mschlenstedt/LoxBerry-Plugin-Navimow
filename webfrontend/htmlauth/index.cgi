#!/usr/bin/perl

use CGI;
use LoxBerry::System;
use LoxBerry::Web;
use LoxBerry::JSON;
use LoxBerry::Log;
use File::Basename;
use warnings;
use strict;

my $cgi     = CGI->new;
my $q       = $cgi->Vars;
my $version = LoxBerry::System::pluginversion();
my %L;

# Load plugin config
my $jsonobj = LoxBerry::JSON->new();
my $cfg = $jsonobj->open(filename => "$lbpconfigdir/pluginconfig.json", readonly => 1);
$cfg //= {};
$cfg->{base_topic}    //= 'navimow';
$cfg->{access_token}  //= '';
$cfg->{devices}       //= [];

# Build OAuth callback URL
my $scheme       = ($ENV{HTTPS} && $ENV{HTTPS} ne 'off') ? 'https' : 'http';
my $host         = $ENV{HTTP_HOST} // 'localhost';
my $folder       = basename($lbpplugindir);
my $callback_raw = "$scheme://$host/admin/plugins/$folder/oauth_callback.php";
(my $callback    = $callback_raw) =~ s/([^A-Za-z0-9\-_.~])/sprintf("%%%02X", ord($1))/ge;
my $oauth_url    = "https://navimow-h5-fra.willand.com/smartHome/login?channel=homeassistant&redirect_uri=$callback";

# Active tab
my $form = $q->{form} // $q->{tab} // 'navimow';
$form = 'navimow' unless $form =~ /^(navimow|mqtt|logs)$/;

# Load template
my $templatefile = $form eq 'logs' ? "$lbptemplatedir/logs_tab.html"
                 : $form eq 'mqtt' ? "$lbptemplatedir/mqtt_tab.html"
                 :                   "$lbptemplatedir/navimow_tab.html";

my $template = LoxBerry::System::read_file($templatefile);
$template   .= LoxBerry::System::read_file("$lbptemplatedir/javascript.js");

my $templateout = HTML::Template->new_scalar_ref(
    \$template,
    global_vars       => 1,
    loop_context_vars => 1,
    die_on_bad_params => 0,
);

%L = LoxBerry::System::readlanguage($templateout, "language.ini");

# Navbar
our %navbar;
$navbar{10}{Name}   = "Navimow";
$navbar{10}{URL}    = 'index.cgi?form=navimow';
$navbar{10}{active} = 1 if $form eq 'navimow';
$navbar{20}{Name}   = "MQTT";
$navbar{20}{URL}    = 'index.cgi?form=mqtt';
$navbar{20}{active} = 1 if $form eq 'mqtt';
$navbar{30}{Name}   = "Logs";
$navbar{30}{URL}    = 'index.cgi?form=logs';
$navbar{30}{active} = 1 if $form eq 'logs';

# Template parameters
$templateout->param(OAUTH_AUTHORIZE_URL => $oauth_url);
$templateout->param(BASE_TOPIC          => $cfg->{base_topic});
$templateout->param(AJAXCFGFILE         => "LBPCONFIG/$folder/pluginconfig.json");
$templateout->param(OAUTH_OK            => ($q->{oauth_ok} ? 1 : 0));
$templateout->param(OAUTH_ERROR         => CGI::escapeHTML($q->{oauth_error} // ''));

# Devices loop
my @devices = ();
if (ref $cfg->{devices} eq 'ARRAY') {
    @devices = map { {
        DEVICE_NAME => $_->{name}      // '',
        DEVICE_ID   => $_->{device_id} // '',
    } } @{ $cfg->{devices} };
}
$templateout->param(HAS_DEVICES => scalar(@devices) ? 1 : 0);
$templateout->param(DEVICES     => \@devices);

# Log list
if ($form eq 'logs') {
    $templateout->param(LOGLIST => LoxBerry::Web::loglist_html());
}

# Render
LoxBerry::Web::lbheader($L{'BASIC.TITLE'} . " V$version",
    "https://github.com/mschlenstedt/LoxBerry-Plugin-Navimow", "", 1);
print $templateout->output();
LoxBerry::Web::lbfooter();

exit;
