#!/usr/bin/env bash
# Écrit /etc/default/gpsd (Arch / Debian systemd) et redémarre gpsd.
# Usage : sudo bash scripts/configure_gpsd.sh /dev/ttyACM0
set -euo pipefail

DEV="${1:?Usage: sudo bash scripts/configure_gpsd.sh /dev/ttyACM0}"

if [[ ! -e "$DEV" ]]; then
  echo "[!] Périphérique introuvable: $DEV"
  exit 1
fi

tee /etc/default/gpsd >/dev/null << EOF
# CyberAlpha / gpsd — lu par systemd (EnvironmentFile)
START_DAEMON="true"
GPSD_OPTIONS="-n"
OPTIONS=""
DEVICES="$DEV"
USBAUTO="true"
EOF

systemctl restart gpsd
echo "[*] gpsd redémarré avec DEVICES=$DEV"
echo "    Test : cgps   ou   venv/bin/python gps_diagnose.py"
