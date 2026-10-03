#!/bin/bash
# postroot.sh - Runs as ROOT after all plugin files are installed.
# Installs Python dependencies globally into system site-packages.

COMMAND=$0
PTEMPDIR=$1
PSHNAME=$2
PDIR=$3
PVERSION=$4
PTEMPPATH=$6

echo "<INFO> Navimow: installing Python dependencies as root..."

pip3 install --quiet \
    "aiomqtt>=2.0,<3.0" \
    "paho-mqtt>=1.6,<3.0" \
    aiohttp 2>/dev/null \
|| pip3 install --break-system-packages --quiet \
    "aiomqtt>=2.0,<3.0" \
    "paho-mqtt>=1.6,<3.0" \
    aiohttp

if [ $? -ne 0 ]; then
    echo "<FAIL> Navimow: pip3 install failed"
    exit 1
fi

echo "<OK> Navimow: Python dependencies installed successfully"

# Optional: nur für die inoffizielle API. Ein Fehlschlag darf die Installation
# und den offiziellen Pfad nicht beeinträchtigen.
pip3 install --quiet "cryptography" 2>/dev/null \
|| pip3 install --break-system-packages --quiet "cryptography"
if [ $? -ne 0 ]; then
    echo "<WARNING> Navimow: cryptography could not be installed — unofficial API disabled, official API unaffected"
fi

exit 0
