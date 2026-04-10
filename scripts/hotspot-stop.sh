#!/usr/bin/env bash
# scripts/hotspot-stop.sh — Arrête le hotspot et remet wlan0 en mode client WiFi
#
# Usage : sudo bash scripts/hotspot-stop.sh
#
# 1) Arrêt hostapd/dnsmasq ou profil NetworkManager WifyScanner (comme hotspot.sh stop)
# 2) Réactive le WiFi client : rescan + tentative de reconnexion au réseau enregistré

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IFACE="${WIFY_WLAN:-wlan0}"

GRN='\033[0;32m'; YLW='\033[1;33m'; RED='\033[0;31m'; BLD='\033[1m'; RST='\033[0m'
info()  { echo -e "${GRN}[+]${RST} $*"; }
warn()  { echo -e "${YLW}[!]${RST} $*"; }
error() { echo -e "${RED}[✗]${RST} $*" >&2; }

[[ $EUID -ne 0 ]] && { error "Lance avec : sudo bash $0"; exit 1; }

if ! ip link show "$IFACE" &>/dev/null; then
    error "Interface $IFACE introuvable (variable WIFY_WLAN pour en changer)."
    exit 1
fi

# ─── 1. Arrêt hotspot (logique partagée avec hotspot.sh) ─────────────────────
info "Arrêt du hotspot…"
bash "$SCRIPT_DIR/hotspot.sh" stop

# ─── 2. Retour mode client WiFi ─────────────────────────────────────────────
rfkill unblock wifi 2>/dev/null || true

if command -v nmcli &>/dev/null && systemctl is-active --quiet NetworkManager 2>/dev/null; then
    info "NetworkManager : réactivation WiFi client sur $IFACE…"
    nmcli radio wifi on
    nmcli networking on
    nmcli device set "$IFACE" managed yes 2>/dev/null || true
    nmcli device wifi rescan 2>/dev/null || true
    sleep 2

    state=$(nmcli -t -f STATE device show "$IFACE" 2>/dev/null || echo "")
    if echo "$state" | grep -qi connected; then
        info "Déjà connecté sur $IFACE."
    else
        info "Tentative de connexion automatique (profil enregistré)…"
        if nmcli device connect "$IFACE" 2>/dev/null; then
            info "Connexion lancée sur $IFACE."
        else
            warn "Pas de reconnexion auto. Choisis le réseau :"
            echo "    ${BLD}sudo nmtui${RST}   ou   ${BLD}nmcli device wifi list${RST} puis ${BLD}nmcli device wifi connect \"SSID\" password \"…\"${RST}"
        fi
    fi

elif command -v dhcpcd &>/dev/null; then
    info "Redémarrage de dhcpcd pour $IFACE…"
    ip addr flush dev "$IFACE" 2>/dev/null || true
    ip link set "$IFACE" up
    systemctl restart dhcpcd 2>/dev/null || dhcpcd -n "$IFACE" 2>/dev/null || warn "dhcpcd : vérifie la config."
else
    info "Pas de NetworkManager : interface remise à plat."
    ip addr flush dev "$IFACE" 2>/dev/null || true
    ip link set "$IFACE" up
    warn "Configure le WiFi client manuellement (wpa_supplicant, dhcpcd, etc.)."
fi

echo ""
echo -e "${BLD}━━━ État $IFACE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
ip -4 addr show "$IFACE" 2>/dev/null || true
echo ""
info "Terminé. Hotspot arrêté, $IFACE disponible en client WiFi."
echo ""
