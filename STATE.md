# État du projet

*Dernière mise à jour : avril 2026*

## Réalisé

- Chaîne collecte → SQLite → API → carte heatmap.
- Script `setup.sh` (Arch) : venv, pip, frontend npm, gpsd.
- Documentation racine : `README.md`, `PROJECT.md`, `CONTEXTE.md`.
- API `/control` : statut, preflight, `pip` / `npm install`, start/stop collecteur, logs.
- Frontend : onglets **Heatmap** et **Contrôle** ; case **Temps réel (~3s)** sur la heatmap ; script `npm run dev:host` pour accès téléphone sur le LAN.

## En cours / à valider sur Raspberry Pi

- Lancer l’API en `0.0.0.0` et le frontend Vite en `--host` (ou build statique servi par nginx).
- `CYBERALPHA_SUDO_COLLECTOR=1` + règle **sudoers** pour `sudo -n` sur le collecteur si l’API ne tourne pas en root.
- Test terrain : fix GPS, interface monitor stable (`wlan0mon` vs `iw` sans renommage).

## Prochaines idées

- Build frontend production + service systemd pour API + (option) serveur de fichiers statiques.
- Jeton de contrôle obligatoire en exposition sur Internet (non recommandé sans TLS + auth).
