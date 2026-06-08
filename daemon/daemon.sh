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

GATEWAY="${LBPBINDIR}/navimow_gateway.py"

if [ ! -f "$GATEWAY" ]; then
    logger "Navimow: gateway not found at $GATEWAY"
    exit 1
fi

# Create log directory if missing
mkdir -p "$LBPLOGDIR"

LOGFILE="${LBPLOGDIR}/navimow_gateway.log"
LOGDBKEY="navimow_${PLUGIN_FOLDER}_gateway"

python3 "$GATEWAY" \
    --logfile    "$LOGFILE" \
    --logdbkey   "$LOGDBKEY" \
    --configdir  "$LBPCONFIGDIR" \
    --lbsconfig  "$LBSCONFIG" \
    &

logger "Navimow: gateway started (PID $!)"
exit 0
