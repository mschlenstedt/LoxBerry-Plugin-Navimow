#!/bin/bash
# navimow_sdk_update.sh - Upgrades navimow-sdk to the latest version.
# Runs as root via sudo (granted automatically for sbin/ scripts by LoxBerry).

echo "Navimow: upgrading navimow-sdk..."

pip3 install --upgrade --quiet navimow-sdk 2>/dev/null \
|| pip3 install --upgrade --quiet --break-system-packages navimow-sdk

if [ $? -ne 0 ]; then
    echo "Navimow: navimow-sdk upgrade failed" >&2
    exit 1
fi

echo "Navimow: navimow-sdk upgraded successfully"
exit 0
