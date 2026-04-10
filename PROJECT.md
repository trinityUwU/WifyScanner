# CyberAlpha — WiFi Heatmap

## Vision

Application mobile / terrain : cartographier la réception WiFi (RSSI) en fonction de la position GPS, afficher une heatmap sur une carte, et piloter l’installation et la collecte depuis une interface web (téléphone ou ordinateur), sans enchaîner plusieurs terminaux à la main.

## Périmètre actuel

- Collecte 802.11 (beacons) en mode monitor via **Scapy**, corrélation avec **gpsd**.
- Stockage **SQLite**, API **FastAPI**, interface **React + Leaflet**.
- Panneau **Contrôle** dans le frontend + API `/control/*` : dépendances Python/npm, statut, démarrage / arrêt du collecteur, journaux.

## Hors périmètre (pour l’instant)

- Installation automatique des paquets système (`pacman`, noyau, firmware) — trop dépendante de la machine ; documentée dans le README.
- Authentification utilisateur complète ; optionnel : jeton `CYBERALPHA_CONTROL_TOKEN` pour sécuriser les actions POST sur `/control`.

## Matériel cible

- Clé USB **Alfa AWUS036NHA** (AR9271) ou équivalent compatible monitor sous Linux.
- Récepteur GPS USB + **gpsd**.
- **Raspberry Pi** (ou PC portable) sous Linux, accès réseau local depuis le téléphone.

## Conformité

La capture radio et le mode monitor ne doivent être utilisés que dans un cadre **autorisé** (réseaux propres, labo, consentement).
