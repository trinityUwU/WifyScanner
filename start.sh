#!/usr/bin/env bash
# CyberAlpha — Lance l'API + le frontend + (en root) gpsd, wlan1 monitor, collecteur.
# Usage : ./start.sh [interface_monitor]
#   Sans argument (recommandé avec sudo) : prépare CYBERALPHA_WIFI_IFACE (défaut wlan1)
#   en mode monitor, démarre gpsd si besoin, lance le collecteur sur cette interface.
#   Avec argument : utilise cette interface telle quelle (pas de iw), ex. wlan1mon.
#
# Arrêt propre : ./stop.sh   ou   ./start.sh stop
# Logs         : logs/api.log, logs/frontend.log, logs/collector.log
#
# Variables :
#   CYBERALPHA_WEB_PORT   Port UI Vite (défaut 3780)
#   CYBERALPHA_WIFI_IFACE Interface physique à passer en monitor (défaut wlan1)
#   CYBERALPHA_SKIP_GPS=1 Ne pas tenter systemctl start gpsd
#   CYBERALPHA_SKIP_MONITOR=1 Ne pas exécuter iw (iface déjà en monitor)
#   CYBERALPHA_SKIP_COLLECTOR=1 Ne pas lancer collector.py (API + UI seulement)

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Couleurs ──────────────────────────────────────────────────────────────────
GRN='\033[0;32m'; YLW='\033[0;33m'; RED='\033[0;31m'; BLD='\033[1m'; RST='\033[0m'

# ── Config ────────────────────────────────────────────────────────────────────
VENV="$SCRIPT_DIR/venv"
API_PORT=8001
WEB_PORT="${CYBERALPHA_WEB_PORT:-3780}"
export CYBERALPHA_WEB_PORT="$WEB_PORT"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
LOG_DIR="$SCRIPT_DIR/logs"
PID_API="$LOG_DIR/api.pid"
PID_FRONT="$LOG_DIR/frontend.pid"
PID_COL="$LOG_DIR/collector.pid"

PHY_WIFI="${CYBERALPHA_WIFI_IFACE:-wlan1}"

mkdir -p "$LOG_DIR"

# ── Fonctions ─────────────────────────────────────────────────────────────────
is_running() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

stop_pid() {
  if is_running "$1"; then
    pid=$(cat "$1")
    kill "$pid" 2>/dev/null && echo -e "  ${YLW}Arrêté PID $pid${RST}"
    rm -f "$1"
  fi
}

get_ip() {
  ip -4 addr show scope global | awk '/inet /{print $2}' | cut -d/ -f1 | head -1
}

ensure_gpsd() {
  if [ "${CYBERALPHA_SKIP_GPS:-0}" = "1" ]; then
    echo -e "  ${YLW}ℹ gpsd ignoré (CYBERALPHA_SKIP_GPS=1)${RST}"
    return 0
  fi
  if systemctl is-active --quiet gpsd 2>/dev/null; then
    echo -e "  ${GRN}✓ gpsd déjà actif${RST}"
    return 0
  fi
  if systemctl start gpsd 2>/dev/null; then
    sleep 0.5
    if systemctl is-active --quiet gpsd 2>/dev/null; then
      echo -e "  ${GRN}✓ gpsd démarré${RST}"
      return 0
    fi
  fi
  echo -e "  ${RED}[!] gpsd non actif — vérifier : sudo systemctl status gpsd  |  ./setup.sh${RST}"
  return 1
}

ensure_monitor_mode() {
  local iface="$1"
  if [ "${CYBERALPHA_SKIP_MONITOR:-0}" = "1" ]; then
    echo -e "  ${YLW}ℹ Mode monitor non appliqué (CYBERALPHA_SKIP_MONITOR=1) — iface $iface${RST}"
    return 0
  fi
  if ! command -v iw &>/dev/null; then
    echo -e "  ${RED}[!] iw absent — paquet : iw (pacman/apt)${RST}"
    return 1
  fi
  if ! ip link show "$iface" &>/dev/null; then
    echo -e "  ${RED}[!] Interface $iface absente (ip link)${RST}"
    return 1
  fi
  local cur
  cur=$(iw dev "$iface" info 2>/dev/null | awk '/type /{print $2}' || echo "")
  if [ "$cur" = "monitor" ]; then
    ip link set "$iface" up 2>/dev/null || true
    echo -e "  ${GRN}✓ $iface déjà en mode monitor${RST}"
    return 0
  fi
  if command -v nmcli &>/dev/null; then
    nmcli device set "$iface" managed no 2>/dev/null || true
  fi
  rfkill unblock wifi 2>/dev/null || true
  ip link set "$iface" down
  if ! iw dev "$iface" set type monitor; then
    ip link set "$iface" up 2>/dev/null || true
    echo -e "  ${RED}[!] iw set type monitor a échoué sur $iface${RST}"
    return 1
  fi
  ip link set "$iface" up
  echo -e "  ${GRN}✓ $iface passée en mode monitor${RST}"
  return 0
}

# ── Commande stop ─────────────────────────────────────────────────────────────
if [ "${1:-}" = "stop" ]; then
  echo -e "${YLW}Arrêt de CyberAlpha…${RST}"
  stop_pid "$PID_COL"
  stop_pid "$PID_API"
  stop_pid "$PID_FRONT"
  echo -e "${GRN}Tout arrêté.${RST}"
  exit 0
fi

echo ""
echo -e "${BLD}━━━ CyberAlpha — Démarrage ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
echo ""

# ── Prérequis ─────────────────────────────────────────────────────────────────
if [ ! -f "$VENV/bin/python" ]; then
  echo -e "${RED}[!] venv introuvable.${RST} Lance d'abord :"
  echo "    python3 -m venv venv && venv/bin/pip install -r requirements.txt"
  exit 1
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo -e "${RED}[!] node_modules frontend absent.${RST} Lance d'abord :"
  echo "    cd frontend && npm install"
  exit 1
fi

# ── Collecteur : gpsd + interface (après prérequis pour ne pas toucher au WiFi avant) ─
# Sans argument + root : CYBERALPHA_WIFI_IFACE (défaut wlan1) → iw monitor, puis collecteur.
# Avec argument : interface telle quelle (ex. wlan1mon après airmon-ng), pas d’iw.
WIFI_IFACE=""
if [ "${CYBERALPHA_SKIP_COLLECTOR:-0}" != "1" ]; then
  if [ "$(id -u)" -eq 0 ]; then
    ensure_gpsd || true
    if [ -n "${1:-}" ]; then
      WIFI_IFACE="$1"
    else
      if ensure_monitor_mode "$PHY_WIFI"; then
        WIFI_IFACE="$PHY_WIFI"
      else
        echo -e "  ${YLW}⚠ Collecteur sans iface monitor — corrige $PHY_WIFI ou : sudo ./start.sh wlan1mon${RST}"
      fi
    fi
  else
    if [ -n "${1:-}" ]; then
      WIFI_IFACE="$1"
    fi
  fi
fi

# ── gpsd (affichage si pas root : pas d’ensure_gpsd ci-dessus) ────────────────
if [ "$(id -u)" -ne 0 ]; then
  if systemctl is-active --quiet gpsd 2>/dev/null; then
    echo -e "  ${GRN}✓ gpsd actif${RST}"
  else
    echo -e "  ${YLW}⚠ gpsd inactif — stack complète : ${BLD}sudo ./start.sh${RST}  ou  sudo systemctl start gpsd${RST}"
  fi
fi

# ── API ───────────────────────────────────────────────────────────────────────
if is_running "$PID_API"; then
  echo -e "  ${YLW}API déjà en cours (PID $(cat $PID_API))${RST}"
else
  nohup "$VENV/bin/uvicorn" api:app \
    --host 0.0.0.0 \
    --port "$API_PORT" \
    --log-level info \
    > "$LOG_DIR/api.log" 2>&1 &
  echo $! > "$PID_API"
  echo -e "  ${GRN}✓ API démarrée${RST}  →  http://0.0.0.0:$API_PORT  (PID $(cat $PID_API))"
fi

# ── Frontend (Vite) — cd explicite : --prefix peut échouer sur certains Pi/npm ─
if is_running "$PID_FRONT"; then
  echo -e "  ${YLW}Frontend déjà en cours (PID $(cat $PID_FRONT))${RST}"
else
  (
    cd "$FRONTEND_DIR"
    export CYBERALPHA_WEB_PORT="$WEB_PORT"
    exec node ./node_modules/vite/bin/vite.js --host 0.0.0.0
  ) > "$LOG_DIR/frontend.log" 2>&1 &
  echo $! > "$PID_FRONT"
  echo -e "  ${GRN}✓ Frontend lancé${RST}  (PID $(cat $PID_FRONT), port $WEB_PORT)"
  for _ in $(seq 1 15); do
    if ss -tln 2>/dev/null | grep -qE ":${WEB_PORT}\b"; then
      echo -e "  ${GRN}✓ Port $WEB_PORT ouvert (Vite prêt)${RST}"
      break
    fi
    sleep 1
  done
  if ! ss -tln 2>/dev/null | grep -qE ":${WEB_PORT}\b"; then
    echo -e "  ${RED}[!] Rien n’écoute sur $WEB_PORT — voir logs/frontend.log :${RST}"
    tail -20 "$LOG_DIR/frontend.log" 2>/dev/null || true
  fi
fi

# ── Collecteur ────────────────────────────────────────────────────────────────
if [ -n "$WIFI_IFACE" ]; then
  if is_running "$PID_COL"; then
    echo -e "  ${YLW}Collecteur déjà en cours (PID $(cat $PID_COL))${RST}"
  else
    if [ "$(id -u)" -ne 0 ]; then
      echo -e "  ${YLW}⚠ Collecteur nécessite root — ${BLD}sudo ./start.sh${RST} (ou sudo ./start.sh $WIFI_IFACE)${RST}"
    else
      nohup "$VENV/bin/python" collector.py -i "$WIFI_IFACE" --gps-wait 300 \
        > "$LOG_DIR/collector.log" 2>&1 &
      echo $! > "$PID_COL"
      echo -e "  ${GRN}✓ Collecteur démarré${RST}  interface=$WIFI_IFACE (PID $(cat $PID_COL))"
    fi
  fi
else
  if [ "$(id -u)" -ne 0 ]; then
    echo -e "  ${YLW}ℹ Collecteur non lancé${RST} — lance ${BLD}sudo ./start.sh${RST} pour wlan1 monitor + gpsd + collecteur"
  else
    echo -e "  ${YLW}ℹ Collecteur non lancé${RST} (CYBERALPHA_SKIP_COLLECTOR=1 ou échec monitor)"
  fi
fi

# ── URLs ──────────────────────────────────────────────────────────────────────
IP=$(get_ip || echo "?")
sleep 1
FRONT_PORT=$(grep -oP 'Local:.+:(\d+)' "$LOG_DIR/frontend.log" 2>/dev/null | tail -1 | grep -oP '\d+$' || echo "$WEB_PORT")

echo ""
echo -e "${BLD}━━━ Accès ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
echo -e "  UI locale   : ${BLD}http://localhost:$FRONT_PORT${RST}"
echo -e "  UI réseau   : ${BLD}http://$IP:$FRONT_PORT${RST}  ← depuis ton téléphone"
echo -e "  API         : http://$IP:$API_PORT"
echo -e "  Docs API    : http://$IP:$API_PORT/docs"
echo ""
echo -e "  Logs : tail -f $LOG_DIR/api.log"
echo -e "         tail -f $LOG_DIR/frontend.log"
[ -n "$WIFI_IFACE" ] && echo -e "         tail -f $LOG_DIR/collector.log"
echo ""
echo -e "  Arrêt : ${BLD}./stop.sh${RST}  ou  ${BLD}./start.sh stop${RST}"
echo -e "${BLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
echo ""
