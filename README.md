# CyberAlpha — WiFi Heatmap

Carte de chaleur WiFi géolocalisée : beacons 802.11 + GPS, visualisation dans le navigateur, et **panneau de contrôle** web pour installer les dépendances projet et lancer / arrêter le collecteur.

## Prérequis système (Linux, ex. Arch / Raspberry Pi OS)

- Python **3.11** (`python3.11`)
- `gpsd`, clé GPS USB
- Interface WiFi compatible **mode monitor** (ex. Alfa AWUS036NHA, driver `ath9k_htc`)
- `iw`, recommandé : **aircrack-ng** pour `airmon-ng`
- **Node.js** / **npm** (pour le frontend)

Paquets système (exemple Arch) :

```bash
sudo pacman -S --needed python311 gpsd iw aircrack-ng nodejs npm
```

## Installation initiale

```bash
./setup.sh wlan0
```

(`wlan0` : remplacer par votre interface, ex. `wlx…`.) Le script configure **gpsd** et crée le venv ; la clé GPS doit être branchée.

Si plusieurs dongles USB série sont branchés, indique le bon port :

```bash
./setup.sh wlan0 /dev/ttyACM0
```

### GPS ne fixe pas / gpsd

Sur **Arch**, `gpsd` lit **`/etc/default/gpsd`** (variables `DEVICES`, `GPSD_OPTIONS`). Une ancienne version du script écrivait `/etc/gpsd.conf`, que systemd **n’utilise pas** : dans ce cas le GPS n’était jamais connecté à gpsd. Relance `./setup.sh` ou édite `/etc/default/gpsd`, puis `sudo systemctl restart gpsd`.

Vérifications :

```bash
sudo systemctl status gpsd
cat /etc/default/gpsd
venv/bin/python gps_diagnose.py
cgps
```

Configurer explicitement le port série (recommandé si `DEVICES=""`) :

```bash
sudo bash scripts/configure_gpsd.sh /dev/ttyACM0
```

Dans l’interface web : onglet **Contrôle** → **Clé GPS (gpsd)** → **Analyser le GPS**.

- **ModemManager** monopolise parfois `/dev/ttyUSB0` : `sudo systemctl stop ModemManager` (ou désactive-le si tu n’en as pas besoin).
- Premier fix : aller **dehors** ou près d’une fenêtre ; compte **1–3 minutes** (cold start).
- Attente côté collecteur : `sudo venv/bin/python collector.py -i wlan0mon --gps-wait 300`

#### `cgps` : « NO FIX » et **Seen 0 / Used 0**

Cela veut dire que le récepteur **ne voit aucun satellite** (pas seulement « pas encore de position »). Ce n’est en général **pas** un problème de config CyberAlpha ou de `DEVICES=` une fois `configure_gpsd.sh` passé.

À vérifier dans l’ordre :

1. **Vue ciel** : test **dehors**, antenne vers le ciel, **10–15 min** après branchement (cold start). En bâtiment blindé ou sans fenêtre, beaucoup de clés restent à 0 satellite.
2. **Antenne** : module avec antenne externe mal branchée ou câble HS → 0 satellite.
3. **USB / RF** : rallonge USB ou port frontal bruyant ; essayer un **port USB direct** sur la carte mère.
4. **NMEA brut** (gpsd **arrêté** le temps du test) :  
   `sudo systemctl stop gpsd` puis  
   `stty -F /dev/ttyACM0 9600 raw -echo && timeout 5 cat /dev/ttyACM0 | head -20`  
   Tu dois voir des lignes commençant par `$G` (GGA, RMC, etc.). Sinon : mauvais débit (essayer **38400** ou **115200** avec `stty`) ou clé défectueuse.  
   Puis : `sudo systemctl start gpsd`.

Le script **`gps_diagnose.py`** affiche aussi des lignes **`SKY`** avec `satellites_visible` / `satellites_used` : si ça reste **0**, le constat est le même que dans cgps.

## Démarrage classique (manuel)

1. Mode monitor sur l’interface WiFi (voir messages de `setup.sh`).
2. Collecteur (root souvent nécessaire) :

   ```bash
   sudo venv/bin/python collector.py -i wlan0mon
   ```

3. API :

   ```bash
   venv/bin/uvicorn api:app --host 0.0.0.0 --port 8001
   ```

4. Frontend (port **3780** par défaut, voir `CYBERALPHA_WEB_PORT`) :

   ```bash
   cd frontend && npm run dev -- --host 0.0.0.0
   ```

Puis ouvrir **`http://<IP>:3780`** (ou le port affiché par Vite) depuis le PC ou le téléphone.

## Panneau « Contrôle » (interface web)

Dans l’app : onglet **Contrôle**.

- **Dépendances** : installe les paquets **Python** (`venv` + `pip`) et **npm** du dossier `frontend` (pas les paquets `pacman`).
- **Prévol** : commandes manquantes, liste des interfaces (`iw dev`).
- **Collecteur** : saisir l’interface monitor, **Démarrer** / **Arrêter** ; les logs s’affichent dans la page.

Pour que le collecteur puisse capturer les paquets depuis l’API sans mot de passe :

```bash
export CYBERALPHA_SUDO_COLLECTOR=1
```

et configurer **sudoers** pour autoriser `sudo -n` sur  
`venv/bin/python …/collector.py` (voir la doc sudo de votre distribution).

Optionnel, pour exiger un jeton sur les actions POST du panneau :

```bash
export CYBERALPHA_CONTROL_TOKEN="votre-secret"
```

Le champ « Jeton API » dans l’interface envoie `Authorization: Bearer …`.

## Légalité

N’utilisez la capture WiFi et le mode monitor que sur des réseaux et dans un cadre **explicitement autorisés** par la loi et les responsables du réseau.

## Documentation

- `PROJECT.md` — vision et périmètre  
- `STATE.md` — jalons et suite  
- `CONTEXTE.md` — stack et variables d’environnement  
