#!/usr/bin/perl

use strict;
use warnings;
use CGI;
use JSON;
use POSIX qw(setsid);
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
    my $lbsconf = "$lbhomedir/config/system";

    # Register log entry in LoxBerry log database so loglist_html() finds it
    my ($logfile, $logdbkey);
    eval {
        my $log = LoxBerry::Log->new(
            name    => 'gateway',
            package => $lbpplugindir,
            addtime => 1,
        );
        $log->LOGSTART("Navimow Gateway starting");
        $logfile  = $log->{filename};
        $logdbkey = $log->{dbkey} // 0;
    };
    $logfile  //= "$lbplogdir/navimow_gateway.log";
    $logdbkey //= 0;

    unless (-f $gateway) {
        print encode_json({ ok => 0, error => "Gateway not found: $gateway" });
        return;
    }

    # Double-fork to detach gateway from CGI process; use exec list form (no shell)
    my $child = fork();
    if (!defined $child) {
        print encode_json({ ok => 0, error => "fork failed: $!" });
        return;
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
                '--lbsconfig', $lbsconf,
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
        print encode_json({ ok => 1, pid => $new_pid+0 });
    } else {
        print encode_json({ ok => 0, error => 'Gateway did not start' });
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
    my $masked        = $data->{token_masked}  // '';
    my $now           = time();
    my $expires_in    = ($expires_at > $now) ? int($expires_at - $now) : 0;

    print encode_json({
        ok          => $authenticated,
        masked      => $masked,
        expires_in  => $expires_in+0,
        has_refresh => $has_refresh,
    });
}

