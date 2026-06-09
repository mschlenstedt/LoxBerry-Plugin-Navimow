#!/bin/bash
# LoxBerry calls this at boot with PLUGINNAME set to the NAME from plugin.cfg.
# LBHOMEDIR and LBSCONFIG are set in /etc/environment.

PLUGIN_FOLDER=$(grep -A5 "NAME=$PLUGINNAME" "${LBHOMEDIR}/data/system/plugindatabase.dat" \
    | grep "^FOLDER=" | head -1 | cut -d= -f2)

if [ -z "$PLUGIN_FOLDER" ]; then
    logger "Navimow: could not find plugin folder in plugindatabase.dat"
    exit 1
fi

LBPBINDIR="${LBHOMEDIR}/bin/plugins/${PLUGIN_FOLDER}"
LBPCONFIGDIR="${LBHOMEDIR}/config/plugins/${PLUGIN_FOLDER}"
LBPLOGDIR="${LBHOMEDIR}/log/plugins/${PLUGIN_FOLDER}"

# Do not start if the gateway was manually stopped
if [ -f "${LBPCONFIGDIR}/gateway_stopped" ]; then
    logger "Navimow: gateway_stopped flag set — not starting"
    exit 0
fi

GATEWAY="${LBPBINDIR}/navimow_gateway.py"

if [ ! -f "$GATEWAY" ]; then
    logger "Navimow: gateway not found at $GATEWAY"
    exit 1
fi

# Register log entry in LoxBerry log database and get filename + dbkey
read LOGFILE LOGDBKEY < <(perl -e "
    use LoxBerry::Log;
    my \$log = LoxBerry::Log->new(name => 'gateway', package => '${LBHOMEDIR}/data/plugins/${PLUGIN_FOLDER}', addtime => 1);
    \$log->LOGSTART('Navimow Gateway starting (boot)');
    print \$log->{filename} . ' ' . (\$log->{dbkey} // 0) . \"\n\";
")

if [ -z "$LOGFILE" ]; then
    LOGFILE="${LBPLOGDIR}/navimow_gateway.log"
    LOGDBKEY="0"
fi

python3 "$GATEWAY" \
    --logfile    "$LOGFILE" \
    --logdbkey   "$LOGDBKEY" \
    --configdir  "$LBPCONFIGDIR" \
    --lbsconfig  "$LBSCONFIG" \
    &

logger "Navimow: gateway started (PID $!)"
exit 0
