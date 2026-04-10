#!/usr/bin/env bash
# scripts/hotspot.sh — Point d'accès WiFi sur wlan0 (Raspberry Pi OS, Debian)
#
# Usage :
#   sudo bash scripts/hotspot.sh start    — démarre le hotspot
#   sudo bash scripts/hotspot.sh stop     — arrête le hotspot
#   sudo bash scripts/hotspot.sh status   — affiche l'état
#   sudo bash scripts/hotspot.sh install  — installe hostapd/dnsmasq si besoin (Bullseye)
#
# Méthode auto-détectée :
#   • NetworkManager disponible  → nmcli hotspot (Bookworm par défaut)
#   • Sinon                      → hostapd + dnsmasq (Bullseye / legacy)

set -euo pipefail

# ─── Configuration ────────────────────────────────────────────────────────────
SSID="WifyScanner"
PASSWORD="chris"
IFACE="wlan0"
HOTSPOT_IP="192.168.4.1"
DHCP_START="192.168.4.10"
DHCP_END="192.168.4.100"
CHANNEL="6"

# ─── Couleurs ─────────────────────────────────────────────────────────────────
GRN='\033[0;32m'; YLW='\033[1;33m'; RED='\033[0;31m'; BLD='\033[1m'; RST='\033[0m'
info()  { echo -e "${GRN}[+]${RST} $*"; }
warn()  { echo -e "${YLW}[!]${RST} $*"; }
error() { echo -e "${RED}[✗]${RST} $*" >&2; }

# ─── Vérifications préalables ─────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && { error "Ce script nécessite sudo."; echo "  Relance : sudo bash $0 ${1:-start}"; exit 1; }

if ! ip link show "$IFACE" &>/dev/null; then
    error "Interface '$IFACE' introuvable."
    warn  "Interfaces disponibles :"
    ip -o link show | awk -F': ' '{print "  •", $2}'
    exit 1
fi

# ─── Détection de la méthode ──────────────────────────────────────────────────
use_nm() {
    command -v nmcli &>/dev/null && systemctl is-active --quiet NetworkManager 2>/dev/null
}

# ═══════════════════════════════════════════════════════════════════════════════
#  MÉTHODE A — NetworkManager (Raspberry Pi OS Bookworm, recommandée)
# ═══════════════════════════════════════════════════════════════════════════════

nm_start() {
    info "NetworkManager détecté — démarrage du hotspot..."

    # Supprimer l'ancienne connexion du même nom si elle existe
    nmcli connection delete "$SSID" &>/dev/null || true

    nmcli device wifi hotspot \
        ifname   "$IFACE"    \
        ssid     "$SSID"     \
        password "$PASSWORD" \
        band     bg          \
        con-name "$SSID"

    # Persistance au démarrage
    nmcli connection modify "$SSID" \
        connection.autoconnect          yes \
        connection.autoconnect-priority 10

    _print_summary
}

nm_stop() {
    info "Arrêt du hotspot (NetworkManager)..."
    nmcli connection down "$SSID" 2>/dev/null && info "Hotspot '$SSID' arrêté." || warn "Hotspot non actif."
}

nm_status() {
    echo ""
    echo -e "${BLD}── État NetworkManager ──────────────────────────${RST}"
    local active
    active=$(nmcli -g GENERAL.STATE connection show --active "$SSID" 2>/dev/null || echo "—")
    echo -e "  Connexion '$SSID' : $active"
    local ip
    ip=$(nmcli -g IP4.ADDRESS device show "$IFACE" 2>/dev/null | head -1 | cut -d'/' -f1 || echo "—")
    echo -e "  IP $IFACE     : $ip"
    echo ""
}

# ═══════════════════════════════════════════════════════════════════════════════
#  MÉTHODE B — hostapd + dnsmasq (Raspberry Pi OS Bullseye / legacy)
# ═══════════════════════════════════════════════════════════════════════════════

legacy_install() {
    info "Installation de hostapd et dnsmasq..."
    apt-get update -qq
    apt-get install -y hostapd dnsmasq
    systemctl unmask hostapd 2>/dev/null || true
    # On ne les active pas au boot — start.sh les contrôle manuellement
    systemctl disable hostapd dnsmasq 2>/dev/null || true

    # ── /etc/hostapd/hostapd.conf ─────────────────────────────────────────────
    info "Écriture de /etc/hostapd/hostapd.conf..."
    cat > /etc/hostapd/hostapd.conf <<EOF
interface=$IFACE
driver=nl80211
ssid=$SSID
hw_mode=g
channel=$CHANNEL
ieee80211n=1
wmm_enabled=1
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
wpa=2
wpa_passphrase=$PASSWORD
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF
    sed -i 's|#DAEMON_CONF=""|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd

    # ── /etc/dnsmasq.d/hotspot.conf ───────────────────────────────────────────
    info "Écriture de /etc/dnsmasq.d/hotspot.conf..."
    mkdir -p /etc/dnsmasq.d
    cat > /etc/dnsmasq.d/hotspot.conf <<EOF
interface=$IFACE
bind-interfaces
dhcp-range=$DHCP_START,$DHCP_END,255.255.255.0,24h
dhcp-option=3,$HOTSPOT_IP
dhcp-option=6,8.8.8.8,8.8.4.4
EOF

    # ── IP statique pour wlan0 (dhcpcd) ──────────────────────────────────────
    if command -v dhcpcd &>/dev/null && [ -f /etc/dhcpcd.conf ]; then
        info "Ajout de l'IP statique dans /etc/dhcpcd.conf..."
        # Éviter les doublons
        if ! grep -q "^interface $IFACE" /etc/dhcpcd.conf; then
            cat >> /etc/dhcpcd.conf <<EOF

# WifyScanner hotspot
interface $IFACE
    static ip_address=$HOTSPOT_IP/24
    nohook wpa_supplicant
EOF
        else
            warn "Une entrée pour $IFACE existe déjà dans /etc/dhcpcd.conf — vérifiez manuellement."
        fi
    else
        warn "dhcpcd non trouvé — assignez manuellement $HOTSPOT_IP/24 à $IFACE avant de lancer 'start'."
    fi

    echo ""
    info "Installation terminée."
    info "Lance maintenant : sudo bash $0 start"
}

legacy_start() {
    info "Démarrage du hotspot (hostapd + dnsmasq)..."

    # Vérifier que hostapd est installé
    if ! command -v hostapd &>/dev/null; then
        error "hostapd non installé. Lance d'abord : sudo bash $0 install"
        exit 1
    fi

    # Assigner l'IP si dhcpcd ne l'a pas encore fait
    if ! ip addr show "$IFACE" | grep -q "$HOTSPOT_IP"; then
        info "Assignation de $HOTSPOT_IP sur $IFACE..."
        ip link set "$IFACE" up
        ip addr add "$HOTSPOT_IP/24" dev "$IFACE" 2>/dev/null || true
    fi

    info "Démarrage de hostapd..."
    systemctl start hostapd

    info "Démarrage de dnsmasq..."
    systemctl start dnsmasq

    _print_summary
}

legacy_stop() {
    info "Arrêt de hostapd et dnsmasq..."
    systemctl stop hostapd 2>/dev/null && info "hostapd arrêté." || warn "hostapd non actif."
    systemctl stop dnsmasq 2>/dev/null && info "dnsmasq arrêté."  || warn "dnsmasq non actif."
}

legacy_status() {
    echo ""
    echo -e "${BLD}── État hostapd / dnsmasq ───────────────────────${RST}"
    echo -e "  hostapd : $(systemctl is-active hostapd 2>/dev/null || echo inactif)"
    echo -e "  dnsmasq : $(systemctl is-active dnsmasq 2>/dev/null || echo inactif)"
    echo -e "  IP $IFACE : $(ip -4 addr show "$IFACE" 2>/dev/null | awk '/inet /{print $2}' | head -1 || echo '—')"
    echo ""
}

# ─── Résumé affiché après start ───────────────────────────────────────────────
_print_summary() {
    local ip
    # Tenter de lire l'IP effective, sinon utiliser la valeur configurée
    ip=$(ip -4 addr show "$IFACE" 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1 | head -1 || echo "$HOTSPOT_IP")
    echo ""
    echo -e "${BLD}━━━ Hotspot démarré ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
    echo -e "  ${GRN}SSID         :${RST} ${BLD}$SSID${RST}"
    echo -e "  ${GRN}Mot de passe :${RST} ${BLD}$PASSWORD${RST}"
    echo -e "  ${GRN}IP du Pi     :${RST} ${BLD}$ip${RST}"
    echo ""
    echo -e "  Depuis ton iPhone connecté au WiFi '${BLD}$SSID${RST}' :"
    echo -e "    SSH  : ${BLD}ssh pi@$ip${RST}"
    echo -e "    Web  : ${BLD}http://$ip:3780${RST}"
    echo -e "${BLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
    echo ""
}

# ─── Dispatch ─────────────────────────────────────────────────────────────────
ACTION="${1:-help}"

case "$ACTION" in
    install)
        if use_nm; then
            info "NetworkManager est disponible — pas d'installation requise."
            info "Lance directement : sudo bash $0 start"
        else
            legacy_install
        fi
        ;;
    start)
        if use_nm; then nm_start;       else legacy_start;  fi ;;
    stop)
        if use_nm; then nm_stop;        else legacy_stop;   fi ;;
    status)
        if use_nm; then nm_status;      else legacy_status; fi ;;
    help|--help|-h|*)
        echo ""
        echo -e "${BLD}Usage :${RST} sudo bash $0 [commande]"
        echo ""
        echo "  install   Installe hostapd/dnsmasq si NetworkManager absent (Bullseye)"
        echo "  start     Démarre le hotspot WiFi '$SSID'"
        echo "  stop      Arrête le hotspot"
        echo "  status    Affiche l'état"
        echo ""
        echo "  SSID : $SSID  |  Mot de passe : $PASSWORD  |  IP : $HOTSPOT_IP"
        echo ""
        ;;
esac
