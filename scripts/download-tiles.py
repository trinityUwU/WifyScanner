#!/usr/bin/env python3
"""
Pré-télécharge les tuiles Carto dark pour une zone et les stocke dans tiles/{z}/{x}/{y}.png.
À lancer AVANT de passer en hotspot (quand internet est disponible).

Usage :
    python scripts/download-tiles.py --bbox 48.80 2.25 48.92 2.42 --zoom 12 16
    python scripts/download-tiles.py --bbox 43.27 5.35 43.33 5.42 --zoom 13 17
    python scripts/download-tiles.py --lat 48.866 --lon 2.333 --radius 5 --zoom 12 16

Options :
    --bbox  lat_min lon_min lat_max lon_max
    --lat / --lon / --radius km : zone centrée sur un point (approximatif)
    --zoom  z_min [z_max]       : niveaux de zoom (inclus). Ex. 12 16 → 12,13,14,15,16
    --url   URL template        : CDN (défaut Carto dark)
    --delay secondes            : délai entre requêtes (défaut 0.05)
    --out   répertoire          : dossier de sortie (défaut : ../tiles relatif au script)
    --dry   : simulation, affiche le nombre de tuiles sans télécharger
"""

import argparse
import math
import os
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
CDN_HOSTS = ["a", "b", "c", "d"]
_host_idx = 0


def _cdn_url(template: str, z: int, x: int, y: int) -> str:
    global _host_idx
    host = CDN_HOSTS[_host_idx % len(CDN_HOSTS)]
    _host_idx += 1
    return template.format(s=host, z=z, x=x, y=y)


def deg2tile(lat: float, lon: float, z: int) -> tuple[int, int]:
    lat_r = math.radians(lat)
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return x, y


def tile_count_for_bbox(lat_min: float, lon_min: float, lat_max: float, lon_max: float,
                        z_min: int, z_max: int) -> int:
    total = 0
    for z in range(z_min, z_max + 1):
        x0, y1 = deg2tile(lat_max, lon_min, z)
        x1, y0 = deg2tile(lat_min, lon_max, z)
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        total += (x1 - x0 + 1) * (y1 - y0 + 1)
    return total


def download_bbox(lat_min: float, lon_min: float, lat_max: float, lon_max: float,
                  z_min: int, z_max: int, out_dir: Path,
                  url_tpl: str, delay: float, dry: bool) -> None:
    total = tile_count_for_bbox(lat_min, lon_min, lat_max, lon_max, z_min, z_max)
    print(f"Zone : lat [{lat_min},{lat_max}]  lon [{lon_min},{lon_max}]  zoom {z_min}-{z_max}")
    print(f"Tuiles à télécharger : {total}")
    if dry:
        print("[dry-run] Aucun fichier écrit.")
        return

    done = skip = err = 0
    for z in range(z_min, z_max + 1):
        x0, y1 = deg2tile(lat_max, lon_min, z)
        x1, y0 = deg2tile(lat_min, lon_max, z)
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                tile_path = out_dir / str(z) / str(x) / f"{y}.png"
                if tile_path.exists():
                    skip += 1
                    continue
                url = _cdn_url(url_tpl, z, x, y)
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "CyberAlpha/1.0"})
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = resp.read()
                    tile_path.parent.mkdir(parents=True, exist_ok=True)
                    tile_path.write_bytes(data)
                    done += 1
                    if done % 50 == 0:
                        pct = (done + skip) / total * 100
                        print(f"  {done + skip}/{total}  ({pct:.0f}%)  z={z} x={x} y={y}", flush=True)
                    if delay > 0:
                        time.sleep(delay)
                except Exception as e:
                    err += 1
                    print(f"  [!] Erreur z={z} x={x} y={y} : {e}", file=sys.stderr)

    print(f"\nTerminé : {done} téléchargées, {skip} existantes ignorées, {err} erreurs")
    size_mb = sum(f.stat().st_size for f in out_dir.rglob("*.png")) / 1_048_576
    print(f"Taille dossier tiles : {size_mb:.1f} Mo")


def bbox_from_center(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    d_lat = radius_km / 111.0
    d_lon = radius_km / (111.0 * math.cos(math.radians(lat)))
    return lat - d_lat, lon - d_lon, lat + d_lat, lon + d_lon


def main() -> None:
    parser = argparse.ArgumentParser(description="Télécharge les tuiles carte pour usage hors ligne.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bbox", nargs=4, metavar=("LAT_MIN", "LON_MIN", "LAT_MAX", "LON_MAX"),
                       type=float, help="Bounding box")
    group.add_argument("--lat", type=float, help="Latitude centre (avec --lon et --radius)")
    parser.add_argument("--lon", type=float)
    parser.add_argument("--radius", type=float, default=3.0, metavar="KM",
                        help="Rayon en km (défaut: 3)")
    parser.add_argument("--zoom", nargs="+", type=int, default=[13, 17],
                        metavar="Z", help="Niveaux de zoom min [max] (défaut: 13 17)")
    parser.add_argument("--url", default=DEFAULT_URL, help="Template URL tuile")
    parser.add_argument("--delay", type=float, default=0.05,
                        help="Délai entre requêtes en s (défaut: 0.05)")
    parser.add_argument("--out", type=Path, default=None,
                        help="Dossier de sortie (défaut: <repo>/tiles)")
    parser.add_argument("--dry", action="store_true", help="Simulation sans téléchargement")
    args = parser.parse_args()

    if args.lat is not None:
        if args.lon is None:
            parser.error("--lat requiert --lon")
        lat_min, lon_min, lat_max, lon_max = bbox_from_center(args.lat, args.lon, args.radius)
    else:
        lat_min, lon_min, lat_max, lon_max = args.bbox  # type: ignore[misc]

    if len(args.zoom) == 1:
        z_min = z_max = args.zoom[0]
    else:
        z_min, z_max = args.zoom[0], args.zoom[-1]

    if z_max > 18:
        print("[!] zoom > 18 risque de générer des centaines de milliers de tuiles — réduis la zone ou le zoom", file=sys.stderr)

    if args.out is None:
        script_dir = Path(__file__).resolve().parent
        out_dir = script_dir.parent / "tiles"
    else:
        out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    download_bbox(lat_min, lon_min, lat_max, lon_max, z_min, z_max, out_dir,
                  args.url, args.delay, args.dry)


if __name__ == "__main__":
    main()
