#!/usr/bin/env bash
# Vérifie que l'API et Vite écoutent bien sur toutes les interfaces.
# Usage : bash scripts/diagnose-network.sh

set -euo pipefail
echo "=== Ports en écoute (3780 UI, 8001 API) ==="
ss -tlnp 2>/dev/null | grep -E ':3780|:8001' || echo "(rien — lance ./start.sh)"
echo ""
echo "=== Test local (depuis le Pi) ==="
curl -sS -o /dev/null -w "HTTP %{http_code} sur http://127.0.0.1:3780\n" --connect-timeout 2 http://127.0.0.1:3780/ || echo "Échec : UI pas démarrée ou crash (voir logs/frontend.log)"
curl -sS -o /dev/null -w "HTTP %{http_code} sur http://127.0.0.1:8001/docs\n" --connect-timeout 2 http://127.0.0.1:8001/docs || echo "Échec : API pas démarrée (voir logs/api.log)"
echo ""
echo "=== Adresses IPv4 du Pi ==="
ip -4 addr show scope global | awk '/inet /{print $2}' | cut -d/ -f1
echo ""
echo "Si les tests locaux OK mais le téléphone refuse : même Wi-Fi que le Pi, pas de VPN sur le téléphone."
echo "Pare-feu Pi (sans ufw) : sudo iptables -L -n | head -20"
