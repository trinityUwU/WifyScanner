#!/usr/bin/env bash
# WiFi Heatmap — Setup Arch Linux
set -e

IFACE=${1:-wlan0}
# Optionnel 2e arg : périphérique série du GPS (ex. /dev/ttyACM0). Sinon auto-détection.
GPS_DEV_ARG=${2:-}
MON_IFACE="${IFACE}mon"
PYTHON=python3.11
VENV=venv

echo "=== WiFi Heatmap Setup ==="
echo ""

# Vérifier python3.11
if ! command -v $PYTHON &>/dev/null; then
  echo "[!] python3.11 non trouvé — installe-le avec: sudo pacman -S python311"
  exit 1
fi
echo "[*] Python: $($PYTHON --version)"

# ── 1. Dépendances système ─────────────────────────────────────────────────────
echo "[1/4] Paquets système..."
sudo pacman -S --needed --noconfirm gpsd nodejs npm

# ── 2. Virtualenv + Python deps ───────────────────────────────────────────────
echo "[2/4] Virtualenv + dépendances Python..."
$PYTHON -m venv $VENV
$VENV/bin/pip install --upgrade pip -q
$VENV/bin/pip install -r requirements.txt -q
echo "    venv prêt dans ./$VENV"

# ── 3. Frontend ────────────────────────────────────────────────────────────────
echo "[3/4] Frontend..."
cd frontend
npm install
cd ..

# ── 4. gpsd ────────────────────────────────────────────────────────────────────
echo "[4/4] Configuration gpsd..."

shopt -s nullglob
PORTS=(/dev/ttyUSB* /dev/ttyACM*)
shopt -u nullglob

if [ -n "$GPS_DEV_ARG" ]; then
  GPS_DEV="$GPS_DEV_ARG"
  if [ ! -e "$GPS_DEV" ]; then
    echo "[!] Périphérique inexistant: $GPS_DEV"
    exit 1
  fi
else
  if [ ${#PORTS[@]} -eq 0 ]; then
    echo "[!] Aucun /dev/ttyUSB* ni /dev/ttyACM* — branche la clé GPS et relance"
    exit 1
  fi
  if [ ${#PORTS[@]} -gt 1 ]; then
    echo "[*] Plusieurs ports série détectés : ${PORTS[*]}"
    echo "    Utilisation du premier. Pour en choisir un : ./setup.sh $IFACE /dev/ttyACM0"
  fi
  GPS_DEV="${PORTS[0]}"
fi
echo "    Clé GPS → $GPS_DEV"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sudo bash "$SCRIPT_DIR/scripts/configure_gpsd.sh" "$GPS_DEV"
sudo systemctl enable gpsd 2>/dev/null || true
echo "    Test rapide : venv/bin/python gps_diagnose.py   ou   cgps"

echo ""
echo "=== Setup OK ==="
echo ""
echo "Pour lancer la collecte:"
echo ""
echo "  # Terminal 1 — Passer en monitor mode"
echo "  sudo airmon-ng start $IFACE"
echo "  # ou manuellement:"
echo "  sudo ip link set $IFACE down"
echo "  sudo iw dev $IFACE set type monitor"
echo "  sudo ip link set $IFACE up"
echo ""
echo "  # Terminal 2 — Collector (root)"
echo "  sudo venv/bin/python collector.py -i $MON_IFACE"
echo ""
echo "  # Terminal 3 — API"
echo "  venv/bin/uvicorn api:app --port 8001"
echo ""
echo "  # Terminal 4 — Frontend"
echo "  cd frontend && npm run dev"
echo ""
echo "  Ouvrir: http://localhost:5173"
