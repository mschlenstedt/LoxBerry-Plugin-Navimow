#!/bin/bash
# Runs as root after plugin installation.
# Installs Python dependencies globally (no venv).

echo "Navimow: installing Python dependencies..."

pip3 install --break-system-packages --quiet \
    navimow-sdk \
    aiomqtt \
    aiohttp

if [ $? -ne 0 ]; then
    echo "Navimow: pip3 install failed" >&2
    exit 1
fi

echo "Navimow: Python dependencies installed successfully"
exit 0
