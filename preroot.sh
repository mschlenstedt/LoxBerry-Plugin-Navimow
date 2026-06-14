#!/bin/bash
# preroot.sh - Runs as ROOT before plugin files are (re)installed.
# Stops a running gateway. As root this always works, regardless of which
# user the gateway was started as (root from an old boot, or loxberry).
# Does NOT touch the gateway_stopped flag — a manual stop stays a manual stop.
PIDFILE="/dev/shm/navimow_gateway.pid"
if [ -f "$PIDFILE" ]; then
    kill "$(cat "$PIDFILE")" 2>/dev/null
    rm -f "$PIDFILE"
fi
exit 0
