#!/usr/bin/env bash
# CyberAlpha — Lance l'API + le frontend en arrière-plan.
# Usage : ./start.sh [interface_wifi]
#   interface_wifi : interface en mode monitor (ex. wlan1mon). Optionnel.
#                   Si fourni, le collecteur est aussi lancé (nécessite root).
#
# Arrêt propre : ./stop.sh   ou   ./start.sh stop
# Logs         : logs/api.log, logs/frontend.log, logs/collector.log
#
# Port UI (défaut 3780) : CYBERALPHA_WEB_PORT=4000 ./start.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Couleurs ──────────────────────────────────────────────────────────────────
GRN='\033[0;32m'; YLW='\033[0;33m'; RED='\033[0;31m'; BLD='\033[1m'; RST='\033[0m'

# ── Config ────────────────────────────────────────────────────────────────────
VENV="$SCRIPT_DIR/venv"
API_PORT=8001
# Port UI Vite (voir frontend/vite.config.ts)
WEB_PORT="${CYBERALPHA_WEB_PORT:-3780}"
export CYBERALPHA_WEB_PORT="$WEB_PORT"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
LOG_DIR="$SCRIPT_DIR/logs"
PID_API="$LOG_DIR/api.pid"
PID_FRONT="$LOG_DIR/frontend.pid"
PID_COL="$LOG_DIR/collector.pid"

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

# ── Commande stop ─────────────────────────────────────────────────────────────
if [ "${1:-}" = "stop" ]; then
  echo -e "${YLW}Arrêt de CyberAlpha…${RST}"
  stop_pid "$PID_COL"
  stop_pid "$PID_API"
  stop_pid "$PID_FRONT"
  echo -e "${GRN}Tout arrêté.${RST}"
  exit 0
fi

WIFI_IFACE="${1:-}"

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

# ── gpsd check ────────────────────────────────────────────────────────────────
if systemctl is-active --quiet gpsd 2>/dev/null; then
  echo -e "  ${GRN}✓ gpsd actif${RST}"
else
  echo -e "  ${YLW}⚠ gpsd inactif — lance : sudo systemctl start gpsd${RST}"
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
    # Évite « vite: Permission denied » si node_modules/.bin/vite n’est pas exécutable (Pi, FS)
    exec node ./node_modules/vite/bin/vite.js --host 0.0.0.0
  ) > "$LOG_DIR/frontend.log" 2>&1 &
  echo $! > "$PID_FRONT"
  echo -e "  ${GRN}✓ Frontend lancé${RST}  (PID $(cat $PID_FRONT), port $WEB_PORT)"
  # Attendre que Vite écoute (sinon npm --prefix / race nohup)
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

# ── Collecteur (optionnel) ─────────────────────────────────────────────────────
if [ -n "$WIFI_IFACE" ]; then
  if is_running "$PID_COL"; then
    echo -e "  ${YLW}Collecteur déjà en cours (PID $(cat $PID_COL))${RST}"
  else
    if [ "$(id -u)" -ne 0 ]; then
      echo -e "  ${YLW}⚠ Collecteur nécessite root — relance avec : sudo ./start.sh $WIFI_IFACE${RST}"
    else
      nohup "$VENV/bin/python" collector.py -i "$WIFI_IFACE" --gps-wait 300 \
        > "$LOG_DIR/collector.log" 2>&1 &
      echo $! > "$PID_COL"
      echo -e "  ${GRN}✓ Collecteur démarré${RST}  interface=$WIFI_IFACE (PID $(cat $PID_COL))"
    fi
  fi
else
  echo -e "  ${YLW}ℹ Collecteur non lancé${RST} (passe l'interface monitor en argument)"
  echo    "    ex. : sudo ./start.sh wlan1mon"
fi

# ── URLs ──────────────────────────────────────────────────────────────────────
IP=$(get_ip || echo "?")
sleep 1   # laisser le frontend démarrer avant d'afficher le port
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
