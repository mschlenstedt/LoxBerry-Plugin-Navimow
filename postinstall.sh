#!/bin/bash
# postinstall.sh - Runs as user "loxberry" after plugin files are installed.
# Python dependencies are installed by postroot.sh (runs as root).

COMMAND=$0
PTEMPDIR=$1
PSHNAME=$2
PDIR=$3
PVERSION=$4
PTEMPPATH=$6

echo "<INFO> Navimow postinstall: nothing to do (Python deps handled by postroot.sh)"
exit 0
