#!/bin/bash

ARGV0=$0 # Zero argument is shell command
ARGV1=$1 # First argument is temp folder during install
ARGV2=$2 # Second argument is Plugin-Name for scipts etc.
ARGV3=$3 # Third argument is Plugin installation folder
ARGV4=$4 # Forth argument is Plugin version
ARGV5=$5 # Fifth argument is Base folder of LoxBerry

echo "<INFO> Copy back existing config files"
cp -p -v -r /tmp/$ARGV1\_upgrade/config/$ARGV3/* $ARGV5/config/plugins/$ARGV3/

echo "<INFO> Copy back existing log files"
cp -p -v -r /tmp/$ARGV1\_upgrade/log/$ARGV3/* $ARGV5/log/plugins/$ARGV3/

echo "<INFO> Copy back existing data files"
cp -p -v -r /tmp/$ARGV1\_upgrade/data/$ARGV3/* $ARGV5/data/plugins/$ARGV3/

echo "<INFO> Remove temporary folders"
rm -r /tmp/$ARGV1\_upgrade

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
