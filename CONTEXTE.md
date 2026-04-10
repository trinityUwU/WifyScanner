# Contexte technique

## Stack

| Couche | Technologie |
|--------|-------------|
| Collecte | Python 3.11, Scapy, gpsdclient, root généralement requis pour la capture |
| Données | SQLite (`wifi_heatmap.db` par défaut, chemin via `CYBERALPHA_DB` ou racine projet) |
| API | FastAPI + Uvicorn |
| UI | Vite, React 18, Leaflet, leaflet.heat (CDN) |

## Variables d’environnement

| Variable | Rôle |
|----------|------|
| `CYBERALPHA_ROOT` | Racine du dépôt (défaut : répertoire de `paths.py`) |
| `CYBERALPHA_DB` | Fichier ou chemin DB relatif à la racine |
| `CYBERALPHA_SUDO_COLLECTOR` | `1` / `true` : préfixe `sudo -n` pour lancer `collector.py` depuis l’API |
| `CYBERALPHA_CONTROL_TOKEN` | Si défini : en-tête `Authorization: Bearer <token>` requis pour les **POST** `/control/*` |

## Réseau (développement)

- Frontend dev : `http://localhost:5173`, proxy Vite `/api` → `http://localhost:8001` (le **8000** est souvent pris par ChromaDB ou d’autres services).
- Accès téléphone : `uvicorn api:app --host 0.0.0.0 --port 8001` et `npm run dev -- --host` dans `frontend` ; ouvrir l’IP du Pi dans le navigateur du téléphone.

## GPS / gpsd (Arch)

- Systemd lance `gpsd` avec les variables de **`/etc/default/gpsd`** (`DEVICES=…`, `GPSD_OPTIONS="-n"`). Le fichier **`/etc/gpsd.conf` seul ne suffit pas** sur une install Arch standard.
- Diagnostic projet : `venv/bin/python gps_diagnose.py`.

## WiFi monitor

- Souvent : `sudo airmon-ng start <iface>` (paquet **aircrack-ng**) ou `iw dev <iface> set type monitor`.
- Le nom d’interface monitor peut ne **pas** finir par `mon` si configuration manuelle ; le collecteur doit utiliser le nom réel (`iw dev`).
