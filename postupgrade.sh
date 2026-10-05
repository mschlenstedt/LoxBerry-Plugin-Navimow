#!/bin/bash

ARGV0=$0 # Zero argument is shell command
ARGV1=$1 # First argument is temp folder during install
ARGV2=$2 # Second argument is Plugin-Name for scipts etc.
ARGV3=$3 # Third argument is Plugin installation folder
ARGV4=$4 # Forth argument is Plugin version
ARGV5=$5 # Fifth argument is Base folder of LoxBerry

echo "<INFO> Restoring saved config (mirror — only backed-up files survive)"
# Mirror the config dir back from the backup instead of merge-copying it.
# --delete removes files the package shipped but the backup did NOT contain
# (e.g. the bundled config/gateway_stopped flag of a fresh install). If the
# flag WAS in the backup (user deliberately stopped the gateway), it is
# restored and survives the upgrade. Trailing slash = copy contents, not dir.
rsync -a --delete /tmp/$ARGV1\_upgrade/config/$ARGV3/ $ARGV5/config/plugins/$ARGV3/

echo "<INFO> Copy back existing log files"
cp -p -v -r /tmp/$ARGV1\_upgrade/log/$ARGV3/* $ARGV5/log/plugins/$ARGV3/

echo "<INFO> Copy back existing data files"
cp -p -v -r /tmp/$ARGV1\_upgrade/data/$ARGV3/* $ARGV5/data/plugins/$ARGV3/

echo "<INFO> Remove temporary folders"
rm -r /tmp/$ARGV1\_upgrade

# Up to 2.0.1 the gateway published the access token retained in
# {base_topic}/gateway. Re-publish that message without it, so the token does
# not linger on the broker — also when the gateway stays stopped below.
echo "<INFO> Removing access token from retained MQTT status (if present)"
NAVIMOW_CFG="$ARGV5/config/plugins/$ARGV3/pluginconfig.json" perl -e '
    use LoxBerry::IO;
    use JSON;
    my $base = "navimow";
    if (open(my $fh, "<", $ENV{NAVIMOW_CFG})) {
        local $/;
        my $cfg = eval { decode_json(<$fh>) };
        $base = $cfg->{base_topic} if ref $cfg eq "HASH" && $cfg->{base_topic};
    }
    my $topic = "$base/gateway";
    my $raw   = LoxBerry::IO::mqtt_get($topic);
    my $data  = (defined $raw && $raw ne "") ? eval { decode_json($raw) } : undef;
    if (ref $data eq "HASH" && exists $data->{token}) {
        delete $data->{token};
        LoxBerry::IO::mqtt_retain($topic, encode_json($data));
        print "<OK> Access token removed from $topic\n";
    } else {
        print "<INFO> No access token in $topic\n";
    }
'

# Restart the gateway unless it was manually stopped via the WebUI.
# postupgrade.sh runs as the loxberry user (only *root scripts run as root),
# so the gateway is started as loxberry — owner-consistent with the boot
# daemon and ajax.cgi. The gateway_stopped flag was just restored above.
STOPPED_FLAG="$ARGV5/config/plugins/$ARGV3/gateway_stopped"
GATEWAY="$ARGV5/bin/plugins/$ARGV3/navimow_gateway.py"

if [ -f "$STOPPED_FLAG" ]; then
    echo "<INFO> gateway_stopped flag set — leaving gateway stopped"
elif [ ! -f "$GATEWAY" ]; then
    echo "<WARNING> Gateway not found at $GATEWAY — not starting"
else
    LBPCONFIGDIR="$ARGV5/config/plugins/$ARGV3"
    LBPLOGDIR="$ARGV5/log/plugins/$ARGV3"
    LBSCONFIG="$ARGV5/config/system"
    mkdir -p "$LBPLOGDIR"

    # Register log entry in LoxBerry log database so loglist_html() finds it
    read LOGFILE LOGDBKEY < <(perl -e "
        use LoxBerry::Log;
        my \$log = LoxBerry::Log->new(name => 'gateway', package => '$ARGV5/data/plugins/$ARGV3', addtime => 1);
        \$log->LOGSTART('Navimow Gateway starting (after upgrade)');
        print \$log->{filename} . ' ' . (\$log->{dbkey} // 0) . \"\n\";
    ")
    if [ -z "$LOGFILE" ]; then
        LOGFILE="$LBPLOGDIR/navimow_gateway.log"
        LOGDBKEY="0"
    fi

    # setsid + redirected stdio detaches the gateway from the installer process
    # so it keeps running after this script exits.
    setsid python3 "$GATEWAY" \
        --logfile    "$LOGFILE" \
        --logdbkey   "$LOGDBKEY" \
        --configdir  "$LBPCONFIGDIR" \
        --lbsconfig  "$LBSCONFIG" \
        </dev/null >>"$LOGFILE" 2>&1 &

    echo "<OK> Gateway started (PID $!)"
fi

# Exit with Status 0
exit 0
