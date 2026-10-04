#!/usr/bin/perl

use strict;
use warnings;
use utf8;
use CGI;
use JSON;
use IPC::Open2;
use POSIX qw(setsid);
use Encode qw(decode);
use LoxBerry::System;
use LoxBerry::IO;
use LoxBerry::Log;

my $cgi    = CGI->new;
my $action = $cgi->param('action') // $cgi->param('ajax') // '';

print $cgi->header(-type => 'application/json', -charset => 'UTF-8');

my $pid_file    = '/dev/shm/navimow_gateway.pid';
my $plugin_cfg  = "$lbpconfigdir/pluginconfig.json";
my $stopped_flag = "$lbpconfigdir/gateway_stopped";

if ($action eq 'getpid') {
    action_getpid();
} elsif ($action eq 'restart') {
    action_restart();
} elsif ($action eq 'stop') {
    action_stop();
} elsif ($action eq 'gettokenstatus') {
    action_gettokenstatus();
} elsif ($action eq 'unofficiallogin') {
    action_unofficiallogin();
} elsif ($action eq 'getunofficialstatus') {
    action_getunofficialstatus();
} elsif ($action eq 'unofficiallogout') {
    action_unofficiallogout();
} elsif ($action eq 'unofficialmap') {
    action_unofficialmap();
} else {
    print encode_json({ error => "Unknown action: $action" });
}
exit;

sub read_pid {
    return undef unless -f $pid_file;
    my $pid = do { local $/; open(my $fh, '<', $pid_file) or return undef; <$fh> };
    chomp $pid;
    return ($pid =~ /^\d+$/) ? $pid : undef;
}

sub pid_running {
    my ($pid) = @_;
    return 0 unless defined $pid;
    return kill(0, $pid) ? 1 : 0;
}

sub action_getpid {
    my $pid = read_pid();
    if (defined $pid && pid_running($pid)) {
        print encode_json({ pid => $pid+0 });
    } else {
        print encode_json({ pid => undef });
    }
}

sub action_stop {
    my $pid = read_pid();
    unless (defined $pid && pid_running($pid)) {
        { open my $fh, '>', $stopped_flag }
        print encode_json({ ok => 1, msg => 'Not running' });
        return;
    }
    kill('TERM', $pid);
    for (1..10) {
        sleep 1;
        last unless pid_running($pid);
    }
    if (pid_running($pid)) {
        kill('KILL', $pid);
        sleep 1;
    }
    unlink $pid_file if -f $pid_file;
    { open my $fh, '>', $stopped_flag }
    print encode_json({ ok => 1, msg => 'Stopped' });
}

sub action_restart {
    print encode_json(do_restart());
}

sub do_restart {
    my $pid = read_pid();
    if (defined $pid && pid_running($pid)) {
        kill('TERM', $pid);
        for (1..10) {
            sleep 1;
            last unless pid_running($pid);
        }
        kill('KILL', $pid) if pid_running($pid);
    }
    unlink $pid_file if -f $pid_file;

    unlink $stopped_flag if -f $stopped_flag;

    my $plugin_folder = $lbpplugindir;
    $plugin_folder =~ s{.*/plugins/}{};
    my $gateway = "$lbhomedir/bin/plugins/$plugin_folder/navimow_gateway.py";

    # Register log entry in LoxBerry log database so loglist_html() finds it
    my ($logfile, $logdbkey, $loglevel);
    eval {
        my $log = LoxBerry::Log->new(
            name    => 'gateway',
            package => $lbpplugindir,
            addtime => 1,
        );
        $log->LOGSTART("Navimow Gateway starting");
        $logfile  = $log->{filename};
        $logdbkey = $log->{dbkey} // 0;
        # Den in der WebUI eingestellten Loglevel holt LoxBerry::Log selbst aus
        # der Plugin-Datenbank; wir reichen genau diesen Wert an den Gateway
        # weiter, damit Perl- und Python-Logs demselben Level folgen.
        $loglevel = $log->loglevel;
    };
    $logfile  //= "$lbplogdir/navimow_gateway.log";
    $logdbkey //= 0;
    $loglevel //= 7;

    unless (-f $gateway) {
        return { ok => 0, error => "Gateway not found: $gateway" };
    }

    # Double-fork to detach gateway from CGI process; use exec list form (no shell)
    my $child = fork();
    if (!defined $child) {
        return { ok => 0, error => "fork failed: $!" };
    }
    if ($child == 0) {
        my $gc = fork();
        if (!defined $gc) { exit 1; }
        if ($gc == 0) {
            setsid();
            open(STDIN,  '<', '/dev/null');
            open(STDOUT, '>>', $logfile) or open(STDOUT, '>', '/dev/null');
            open(STDERR, '>>', $logfile) or open(STDERR, '>', '/dev/null');
            exec('python3', $gateway,
                '--logfile',   $logfile,
                '--logdbkey',  $logdbkey,
                '--configdir', $lbpconfigdir,
                '--loglevel',  $loglevel,
            ) or exit 1;
        }
        exit 0;
    }
    waitpid($child, 0);

    my $new_pid;
    for (1..10) {
        select(undef, undef, undef, 0.5);
        $new_pid = read_pid();
        last if defined $new_pid && pid_running($new_pid);
        $new_pid = undef;
    }

    if (defined $new_pid) {
        return { ok => 1, pid => $new_pid+0 };
    } else {
        return { ok => 0, error => 'Gateway did not start' };
    }
}

sub action_gettokenstatus {
    # Read base_topic from config to build the gateway MQTT topic
    my $cfg = {};
    if (-f $plugin_cfg) {
        local $/;
        if (open(my $fh, '<', $plugin_cfg)) {
            eval { $cfg = decode_json(<$fh>); };
        }
    }
    my $base_topic  = $cfg->{base_topic}   // 'navimow';
    my $has_refresh = ($cfg->{refresh_token} // '') ne '' ? 1 : 0;

    # Auth status is published retained by the gateway to {base_topic}/gateway
    my $raw = LoxBerry::IO::mqtt_get("$base_topic/gateway");

    unless (defined $raw && $raw ne '') {
        # Gateway not yet running or has never published
        print encode_json({ ok => 0, has_refresh => $has_refresh,
                            expires_in => 0, masked => '' });
        return;
    }

    my $data = eval { decode_json($raw) } // {};
    my $authenticated = $data->{authenticated} ? 1 : 0;
    my $expires_at    = $data->{expires_at}    // 0;
    my $now           = time();
    my $expires_in    = ($expires_at > $now) ? int($expires_at - $now) : 0;

    print encode_json({
        ok          => $authenticated,
        expires_in  => $expires_in+0,
        has_refresh => $has_refresh,
    });
}

sub read_cfg {
    return {} unless -f $plugin_cfg;
    local $/;
    open(my $fh, '<', $plugin_cfg) or return undef;
    my $cfg = eval { decode_json(<$fh>) };
    return ref $cfg eq 'HASH' ? $cfg : undef;
}

sub write_cfg {
    my ($cfg) = @_;
    my $tmp = "$plugin_cfg.tmp.$$";
    open(my $fh, '>', $tmp) or return 0;
    print $fh JSON->new->utf8->pretty->canonical->encode($cfg);
    close $fh or return 0;
    return rename($tmp, $plugin_cfg) ? 1 : 0;
}

sub action_unofficiallogin {
    my $email    = decode('UTF-8', $cgi->param('email')    // '');
    my $password = decode('UTF-8', $cgi->param('password') // '');
    unless ($email ne '' && $password ne '') {
        print encode_json({ ok => 0, code => 'required', error => 'E-Mail und Passwort erforderlich' });
        return;
    }

    my $plugin_folder = $lbpplugindir;
    $plugin_folder =~ s{.*/plugins/}{};
    my $helper = "$lbhomedir/bin/plugins/$plugin_folder/navimow_unofficial_login.py";
    unless (-f $helper) {
        print encode_json({ ok => 0, error => "Login-Helfer nicht gefunden: $helper" });
        return;
    }

    my $stdin_json = encode_json({ email => $email, password => $password });

    local $SIG{PIPE} = 'IGNORE';
    my ($pid, $out, $in, $result_line);
    my $started = eval {
        $pid = open2($out, $in, 'python3', $helper, '--configdir', $lbpconfigdir);
        1;
    };
    unless ($started) {
        print encode_json({ ok => 0, error => 'Login-Helfer konnte nicht gestartet werden' });
        return;
    }
    print $in $stdin_json;
    close $in;
    $result_line = <$out>;
    close $out;
    waitpid($pid, 0);

    my $result = eval { decode_json($result_line // '') };
    if (!$result) {
        print encode_json({ ok => 0, error => 'Login-Helfer lieferte keine gültige Antwort' });
        return;
    }
    if ($result->{ok}) {
        $result->{ts} = time();
        my $r = do_restart();
        $result->{restarted} = ($r->{ok} ? JSON::true : JSON::false);
    }
    print encode_json($result);
}

sub action_unofficiallogout {
    my $cfg = read_cfg();
    unless ($cfg) {
        print encode_json({ ok => 0, error => 'pluginconfig.json nicht lesbar' });
        return;
    }
    $cfg->{unofficial_enabled} = JSON::false;
    $cfg->{$_} = '' for qw(unofficial_access_token unofficial_refresh_token unofficial_uuid
                           unofficial_uid unofficial_region unofficial_host);
    $cfg->{unofficial_devices}  = [];
    $cfg->{unofficial_vehicles} = [];
    unless (write_cfg($cfg)) {
        print encode_json({ ok => 0, error => 'pluginconfig.json nicht schreibbar' });
        return;
    }
    my $ts = time();
    my $r  = do_restart();
    print encode_json({ ok => 1, ts => $ts, restarted => ($r->{ok} ? JSON::true : JSON::false) });
}

sub action_unofficialmap {
    my $device_id  = decode('UTF-8', $cgi->param('device_id')  // '');
    my $vehicle_sn = decode('UTF-8', $cgi->param('vehicle_sn') // '');
    my $cfg = read_cfg();
    unless ($cfg) {
        print encode_json({ ok => 0, error => 'pluginconfig.json nicht lesbar' });
        return;
    }
    my ($vehicle) = grep { ($_->{vehicle_sn} // '') eq $vehicle_sn } @{ $cfg->{unofficial_vehicles} // [] };
    my ($device)  = grep { ($_->{device_id}  // '') eq $device_id  } @{ $cfg->{devices} // [] };
    unless ($vehicle && $device) {
        print encode_json({ ok => 0, error => 'Unbekannter Mäher' });
        return;
    }
    my @mapping = grep { ($_->{device_id} // '') ne $device_id } @{ $cfg->{unofficial_devices} // [] };
    push @mapping, { device_id => $device_id, vehicle_sn => $vehicle_sn,
                     vehicle_type => ($vehicle->{vehicle_type} // 0) + 0 };
    $cfg->{unofficial_devices} = \@mapping;
    unless (write_cfg($cfg)) {
        print encode_json({ ok => 0, error => 'pluginconfig.json nicht schreibbar' });
        return;
    }
    my $ts = time();
    my $r  = do_restart();
    print encode_json({ ok => 1, ts => $ts, restarted => ($r->{ok} ? JSON::true : JSON::false) });
}

sub action_getunofficialstatus {
    my $cfg = read_cfg() // {};
    my $base_topic = $cfg->{base_topic} // 'navimow';
    my @mapping  = ref $cfg->{unofficial_devices}  eq 'ARRAY' ? @{ $cfg->{unofficial_devices} }  : ();
    my @vehicles = ref $cfg->{unofficial_vehicles} eq 'ARRAY' ? @{ $cfg->{unofficial_vehicles} } : ();
    my @devices  = ref $cfg->{devices}             eq 'ARRAY' ? @{ $cfg->{devices} }             : ();

    my $raw  = LoxBerry::IO::mqtt_get("$base_topic/gateway_app");
    my $data = (defined $raw && $raw ne '') ? (eval { decode_json($raw) } // {}) : {};

    my $zones_text = '';
    if (@mapping && $mapping[0]->{device_id}) {
        my $zraw = LoxBerry::IO::mqtt_get("$base_topic/$mapping[0]->{device_id}/zones");
        my $zdata = (defined $zraw && $zraw ne '') ? (eval { decode_json($zraw) } // {}) : {};
        $zones_text = $zdata->{text} // '';
    }

    print encode_json({
        enabled    => $cfg->{unofficial_enabled} ? 1 : 0,
        ok         => $data->{authenticated} ? 1 : 0,
        state      => $data->{state} // '',
        error      => $data->{error} // '',
        since      => ($data->{since} // 0) + 0,
        ts         => ($data->{ts} // 0) + 0,
        base_topic => $base_topic,
        mapping    => [ map { { device_id => $_->{device_id}, vehicle_sn => $_->{vehicle_sn} } } @mapping ],
        vehicles   => [ map { { vehicle_sn => $_->{vehicle_sn}, name => $_->{name} // '' } } @vehicles ],
        devices    => [ map { { device_id => $_->{device_id}, name => $_->{name} // '' } } @devices ],
        zones_text => $zones_text,
    });
}

