#!/bin/bash
# Runs as root after plugin installation.
# Installs Python dependencies globally (no venv).

echo "Navimow: installing Python dependencies..."

# Try without --break-system-packages first (pre-PEP-668 systems / pip < 23).
# Fall back with the flag on Debian 12+ / Ubuntu 23+ where it is required.
pip3 install --quiet \
    "navimow-sdk>=0.1.2,<0.2" \
    aiomqtt \
    aiohttp 2>/dev/null \
|| pip3 install --break-system-packages --quiet \
    "navimow-sdk>=0.1.2,<0.2" \
    aiomqtt \
    aiohttp

if [ $? -ne 0 ]; then
    echo "Navimow: pip3 install failed" >&2
    exit 1
fi

echo "Navimow: Python dependencies installed successfully"
exit 0
