#!/usr/bin/env python3
"""
WiFi Heatmap Collector
Capture les beacons WiFi + position GPS et stocke dans SQLite.

Prérequis:
  - Interface en monitor mode (ex: wlan0mon)
  - gpsd en cours + clé GPS branchée
  - root

Usage:
  sudo python3 collector.py -i wlan0mon
  sudo python3 collector.py -i wlan0mon --db /chemin/custom.db
"""

import sqlite3
import time
import math
import argparse
import threading
import signal
import sys
from datetime import datetime

from scapy.all import sniff, Dot11Beacon, Dot11, Dot11Elt, RadioTap
from gpsdclient import GPSDClient

# ─── Config ───────────────────────────────────────────────────────────────────

DEFAULT_DB = "wifi_heatmap.db"
GPS_STALE_THRESHOLD = 5.0   # secondes avant de considérer le fix comme périmé
DEDUP_WINDOW = 2.0           # ignorer le même BSSID dans cette fenêtre (secondes)

# ─── État partagé ─────────────────────────────────────────────────────────────

gps_lock = threading.Lock()
current_gps = {
    "lat": None,
    "lng": None,
    "fix": False,
    "last_update": 0.0,
    "hdop": None,  # précision horizontale
    "mode": 0,     # 0=inconnu, 2=2D, 3=3D (dernier TPV)
}

running = True
dedup_cache: dict[str, float] = {}  # bssid -> last_seen timestamp


# ─── DB ───────────────────────────────────────────────────────────────────────

def init_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_points (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   REAL    NOT NULL,
            lat         REAL    NOT NULL,
            lng         REAL    NOT NULL,
            ssid        TEXT,
            bssid       TEXT    NOT NULL,
            rssi        INTEGER NOT NULL,
            channel     INTEGER,
            encryption  TEXT,
            hdop        REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bssid ON scan_points(bssid)")
    conn.commit()
    conn.close()


def insert_point(db_path: str, ts, lat, lng, ssid, bssid, rssi, channel, encryption, hdop):
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO scan_points (timestamp, lat, lng, ssid, bssid, rssi, channel, encryption, hdop)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (ts, lat, lng, ssid, bssid, rssi, channel, encryption, hdop))
    conn.commit()
    conn.close()


# ─── GPS thread ───────────────────────────────────────────────────────────────

def gps_thread():
    global running
    while running:
        try:
            with GPSDClient(host="127.0.0.1", port=2947) as client:
                for result in client.dict_stream(convert_datetime=True):
                    if not running:
                        break
                    if result.get("class") == "TPV":
                        lat = result.get("lat")
                        lon = result.get("lon")
                        mode = int(result.get("mode") or 0)
                        with gps_lock:
                            current_gps["mode"] = mode
                        # mode 2 = fix 2D, mode 3 = fix 3D ; rejeter NaN / invalides
                        ok = (
                            lat is not None and lon is not None
                            and mode >= 2
                            and math.isfinite(float(lat)) and math.isfinite(float(lon))
                        )
                        if ok:
                            with gps_lock:
                                current_gps["lat"] = float(lat)
                                current_gps["lng"] = float(lon)
                                current_gps["fix"] = True
                                current_gps["last_update"] = time.time()
                                current_gps["hdop"] = result.get("hdop")
        except Exception as e:
            if running:
                print(f"\r[GPS] Erreur: {e} — reconnexion dans 2s...", flush=True)
                time.sleep(2)


def get_gps_snapshot():
    with gps_lock:
        if not current_gps["fix"]:
            return None
        age = time.time() - current_gps["last_update"]
        if age > GPS_STALE_THRESHOLD:
            return None
        return (
            current_gps["lat"],
            current_gps["lng"],
            current_gps["hdop"],
        )


# ─── WiFi parsing ─────────────────────────────────────────────────────────────

def get_channel(pkt) -> int | None:
    try:
        freq = pkt[RadioTap].Channel
        if freq:
            if freq == 2484:
                return 14
            elif 2412 <= freq <= 2472:
                return (freq - 2407) // 5
            elif freq >= 5180:
                return (freq - 5000) // 5
    except Exception:
        pass
    return None


def get_encryption(pkt) -> str:
    crypto = set()
    elt = pkt.getlayer(Dot11Elt)
    while elt:
        if elt.ID == 48:
            crypto.add("WPA2")
        elif elt.ID == 221:
            try:
                if elt.info[:4] == b'\x00P\xf2\x01':
                    crypto.add("WPA")
            except Exception:
                pass
        elt = elt.payload.getlayer(Dot11Elt) if elt.payload else None

    if not crypto:
        try:
            cap = pkt[Dot11Beacon].cap
            if cap & 0x0010:  # Privacy bit
                return "WEP"
        except Exception:
            pass
        return "OPEN"

    return "/".join(sorted(crypto))


def make_packet_handler(db_path: str):
    def handler(pkt):
        if not pkt.haslayer(Dot11Beacon):
            return

        gps = get_gps_snapshot()
        if not gps:
            return

        lat, lng, hdop = gps

        try:
            bssid = pkt[Dot11].addr2
            if not bssid:
                return

            # Déduplication par fenêtre temporelle
            now = time.time()
            last = dedup_cache.get(bssid, 0)
            if now - last < DEDUP_WINDOW:
                return
            dedup_cache[bssid] = now

            # SSID
            elt = pkt.getlayer(Dot11Elt)
            ssid = ""
            if elt and elt.ID == 0:
                try:
                    ssid = elt.info.decode("utf-8", errors="replace").strip()
                except Exception:
                    ssid = ""
            if not ssid:
                ssid = "<hidden>"

            # RSSI
            try:
                rssi = int(pkt[RadioTap].dBm_AntSignal)
            except Exception:
                return  # Sans RSSI, le point est inutile

            channel = get_channel(pkt)
            encryption = get_encryption(pkt)

            insert_point(db_path, now, lat, lng, ssid, bssid, rssi, channel, encryption, hdop)

            rssi_color = "\033[92m" if rssi >= -60 else "\033[93m" if rssi >= -75 else "\033[91m"
            print(
                f"\r[+] {ssid[:30]:<30} {bssid}  "
                f"{rssi_color}{rssi:>4}dBm\033[0m  "
                f"Ch:{str(channel or '?'):>3}  "
                f"{encryption:<8}  "
                f"\033[90m{lat:.5f},{lng:.5f}\033[0m",
                flush=True
            )

        except Exception:
            pass

    return handler


# ─── Main ─────────────────────────────────────────────────────────────────────

def signal_handler(sig, frame):
    global running
    print("\n[*] Arrêt...")
    running = False
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="WiFi Heatmap Collector")
    parser.add_argument("-i", "--interface", required=True,
                        help="Interface en monitor mode (ex: wlan0mon)")
    parser.add_argument("--db", default=DEFAULT_DB,
                        help=f"Chemin SQLite (défaut: {DEFAULT_DB})")
    parser.add_argument("--gps-wait", type=int, default=180, metavar="SEC",
                        help="Secondes max d'attente d'un fix GPS avant abandon (défaut: 180)")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, signal_handler)

    print(f"[*] DB: {args.db}")
    init_db(args.db)

    # GPS thread
    t = threading.Thread(target=gps_thread, daemon=True)
    t.start()

    # Attente du fix GPS (ciel dégagé / fenêtre : parfois plusieurs minutes au démarrage)
    print(f"[*] Attente fix GPS (max {args.gps_wait}s) — mode gpsd: 0=aucun, 2=2D, 3=3D")
    elapsed = 0
    while not current_gps["fix"] and elapsed < args.gps_wait:
        time.sleep(1)
        elapsed += 1
        if elapsed == 1 or elapsed % 15 == 0:
            with gps_lock:
                m = current_gps["mode"]
            print(f"[*] Attente fix… {elapsed}s (mode TPV={m}, 0=aucun fix, 2+=2D/3D)", flush=True)

    if not current_gps["fix"]:
        print(
            f"\n[!] Pas de fix GPS après {args.gps_wait}s.\n"
            "    Vérifier : sudo systemctl status gpsd  |  cat /etc/default/gpsd\n"
            "    Bon port USB ?  ./setup.sh wlan0 /dev/ttyACM0\n"
            "    ModemManager bloque parfois le port :  sudo systemctl stop ModemManager\n"
            "    Test :  venv/bin/python gps_diagnose.py  ou  cgps",
            flush=True,
        )
        sys.exit(1)

    with gps_lock:
        lat, lng = current_gps["lat"], current_gps["lng"]
    print(f"\n[*] Fix GPS OK — {lat:.5f},{lng:.5f}")
    print(f"[*] Collecte sur {args.interface} — Ctrl+C pour arrêter\n")

    sniff(
        iface=args.interface,
        prn=make_packet_handler(args.db),
        store=False,
        stop_filter=lambda _: not running,
    )


if __name__ == "__main__":
    main()
