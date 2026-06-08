#!/bin/bash
# Remove PID file if gateway is still running
PID_FILE="/dev/shm/navimow_gateway.pid"
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    kill -TERM "$PID" 2>/dev/null
    sleep 2
    kill -KILL "$PID" 2>/dev/null
    rm -f "$PID_FILE"
fi
exit 0
