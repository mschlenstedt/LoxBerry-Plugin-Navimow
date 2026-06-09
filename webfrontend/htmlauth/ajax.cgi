#!/usr/bin/perl

use strict;
use warnings;
use CGI;
use JSON;
use POSIX qw(setsid);
use LoxBerry::System;
use LoxBerry::IO;

my $cgi    = CGI->new;
my $action = $cgi->param('action') // $cgi->param('ajax') // '';

print $cgi->header(-type => 'application/json', -charset => 'UTF-8');

my $pid_file    = '/dev/shm/navimow_gateway.pid';
my $plugin_cfg  = "$lbpconfigdir/pluginconfig.json";

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

    my $plugin_folder = $lbpplugindir;
    $plugin_folder =~ s{.*/plugins/}{};
    my $gateway  = "$lbhomedir/bin/plugins/$plugin_folder/navimow_gateway.py";
    my $logfile  = "$lbplogdir/navimow_gateway.log";
    my $logdbkey = "navimow_${plugin_folder}_gateway";
    my $lbsconf  = "$lbhomedir/config/system";

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
    my $cfg = {};
    if (-f $plugin_cfg) {
        local $/;
        open(my $fh, '<', $plugin_cfg) or do {
            print encode_json({ ok => 0, error => 'Cannot read config' });
            return;
        };
        eval { $cfg = decode_json(<$fh>); };
    }

    my $token      = $cfg->{access_token} // '';
    my $expires_at = $cfg->{expires_at}   // 0;
    my $now        = time();
    my $valid      = ($token ne '' && $expires_at > $now) ? 1 : 0;
    my $expires_in = $expires_at > $now ? $expires_at - $now : 0;

    print encode_json({
        ok         => $valid,
        masked     => $token,
        expires_in => $expires_in+0,
    });
}
