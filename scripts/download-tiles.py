#!/usr/bin/env python3
"""
Pré-télécharge les tuiles Carto dark pour une zone et les stocke dans tiles/{z}/{x}/{y}.png.
À lancer AVANT de passer en hotspot (quand internet est disponible).

Usage :
    python scripts/download-tiles.py --bbox 48.80 2.25 48.92 2.42 --zoom 12 16
    python scripts/download-tiles.py --lat 48.866 --lon 2.333 --radius 5 --zoom 12 16
    python scripts/download-tiles.py --lat 48.374 --lon 2.793 --radius 20 --zoom 12 17

Options :
    --bbox  lat_min lon_min lat_max lon_max
    --lat / --lon / --radius km  zone centrée sur un point
    --zoom  z_min [z_max]        niveaux de zoom (inclus). Ex. 12 16
    --workers N                  téléchargements parallèles (défaut : 16)
    --url   URL template         CDN (défaut : Carto dark)
    --out   répertoire           dossier de sortie (défaut : ../tiles)
    --dry                        simulation, compte les tuiles sans télécharger
"""

import argparse
import math
import socket
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

DEFAULT_URL = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
CDN_HOSTS = ["a", "b", "c", "d"]

_host_lock = Lock()
_host_idx = 0

_counter_lock = Lock()
_done = 0
_skip = 0
_err = 0

# IPs résolues une seule fois avant le pool de threads (évite DNS storm)
_cdn_ips: dict[str, str] = {}


def _resolve_cdn_hosts(template: str) -> None:
    """Résout chaque sous-domaine CDN une seule fois et met en cache les IPs."""
    for h in CDN_HOSTS:
        hostname = template.format(s=h, z=0, x=0, y=0)
        # extrait seulement le hostname de l'URL
        hostname = hostname.split("//")[1].split("/")[0]
        try:
            ip = socket.gethostbyname(hostname)
            _cdn_ips[hostname] = ip
        except socket.gaierror as e:
            print(f"[!] DNS échoué pour {hostname}: {e}", file=sys.stderr)
            sys.exit(1)


def _cdn_url(template: str, z: int, x: int, y: int) -> str:
    global _host_idx
    with _host_lock:
        host = CDN_HOSTS[_host_idx % len(CDN_HOSTS)]
        _host_idx += 1
    return template.format(s=host, z=z, x=x, y=y)


def deg2tile(lat: float, lon: float, z: int) -> tuple[int, int]:
    lat_r = math.radians(lat)
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return x, y


def bbox_from_center(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    d_lat = radius_km / 111.0
    d_lon = radius_km / (111.0 * math.cos(math.radians(lat)))
    return lat - d_lat, lon - d_lon, lat + d_lat, lon + d_lon


def tile_jobs(lat_min: float, lon_min: float, lat_max: float, lon_max: float,
              z_min: int, z_max: int) -> list[tuple[int, int, int]]:
    jobs = []
    for z in range(z_min, z_max + 1):
        x0, y1 = deg2tile(lat_max, lon_min, z)
        x1, y0 = deg2tile(lat_min, lon_max, z)
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                jobs.append((z, x, y))
    return jobs


def download_one(job: tuple[int, int, int], out_dir: Path, url_tpl: str,
                 retries: int = 3) -> str:
    """Télécharge une tuile avec retry. Retourne 'done', 'skip' ou 'err:<msg>'."""
    global _done, _skip, _err
    z, x, y = job
    tile_path = out_dir / str(z) / str(x) / f"{y}.png"
    if tile_path.exists():
        with _counter_lock:
            _skip += 1
        return "skip"
    url = _cdn_url(url_tpl, z, x, y)
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CyberAlpha/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            tile_path.parent.mkdir(parents=True, exist_ok=True)
            tile_path.write_bytes(data)
            with _counter_lock:
                _done += 1
            return "done"
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))  # back-off: 0.5s, 1s
    with _counter_lock:
        _err += 1
    return f"err:{last_err}"


def download_bbox(lat_min: float, lon_min: float, lat_max: float, lon_max: float,
                  z_min: int, z_max: int, out_dir: Path,
                  url_tpl: str, workers: int, dry: bool) -> None:
    jobs = tile_jobs(lat_min, lon_min, lat_max, lon_max, z_min, z_max)
    total = len(jobs)
    print(f"Zone     : lat [{lat_min:.5f}, {lat_max:.5f}]  lon [{lon_min:.5f}, {lon_max:.5f}]")
    print(f"Zoom     : {z_min} → {z_max}")
    print(f"Tuiles   : {total:,}  |  workers parallèles : {workers}")
    if dry:
        print("[dry-run] Aucun fichier écrit.")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    # Résolution DNS avant de démarrer le pool (évite le DNS storm avec N threads)
    print("Résolution DNS... ", end="", flush=True)
    _resolve_cdn_hosts(url_tpl)
    print("OK")

    t0 = time.time()
    last_report = [0]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_one, job, out_dir, url_tpl): job for job in jobs}
        for fut in as_completed(futures):
            result = fut.result()
            if result.startswith("err:"):
                job = futures[fut]
                print(f"  [!] z={job[0]} x={job[1]} y={job[2]} : {result[4:]}", file=sys.stderr)

            with _counter_lock:
                finished = _done + _skip + _err

            if finished - last_report[0] >= max(total // 40, 100):
                last_report[0] = finished
                elapsed = time.time() - t0
                rate = _done / elapsed if elapsed > 0 else 0
                eta = (total - finished) / rate if rate > 0 else 0
                pct = finished / total * 100
                print(
                    f"  {finished:>6}/{total}  ({pct:.0f}%)  "
                    f"{rate:.0f} tuiles/s  ETA ~{eta/60:.0f} min",
                    flush=True,
                )

    elapsed = time.time() - t0
    rate = _done / elapsed if elapsed > 0 else 0
    print(f"\nTerminé en {elapsed/60:.1f} min  |  {_done} téléchargées, {_skip} ignorées, {_err} erreurs  |  {rate:.0f} tuiles/s")
    size_mb = sum(f.stat().st_size for f in out_dir.rglob("*.png")) / 1_048_576
    print(f"Taille dossier tiles : {size_mb:.0f} Mo")


def main() -> None:
    parser = argparse.ArgumentParser(description="Télécharge les tuiles carte pour usage hors ligne.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bbox", nargs=4, metavar=("LAT_MIN", "LON_MIN", "LAT_MAX", "LON_MAX"),
                       type=float)
    group.add_argument("--lat", type=float, help="Latitude centre (avec --lon et --radius)")
    parser.add_argument("--lon", type=float)
    parser.add_argument("--radius", type=float, default=3.0, metavar="KM")
    parser.add_argument("--zoom", nargs="+", type=int, default=[13, 17], metavar="Z")
    parser.add_argument("--workers", type=int, default=16, metavar="N",
                        help="Téléchargements parallèles (défaut : 16)")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()

    if args.lat is not None:
        if args.lon is None:
            parser.error("--lat requiert --lon")
        lat_min, lon_min, lat_max, lon_max = bbox_from_center(args.lat, args.lon, args.radius)
    else:
        lat_min, lon_min, lat_max, lon_max = args.bbox  # type: ignore[misc]

    z_min, z_max = (args.zoom[0], args.zoom[-1]) if len(args.zoom) > 1 else (args.zoom[0], args.zoom[0])

    if args.out is None:
        out_dir = Path(__file__).resolve().parent.parent / "tiles"
    else:
        out_dir = args.out

    download_bbox(lat_min, lon_min, lat_max, lon_max, z_min, z_max, out_dir,
                  args.url, args.workers, args.dry)


if __name__ == "__main__":
    main()
