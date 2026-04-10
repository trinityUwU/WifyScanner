#!/usr/bin/env python3
"""
WiFi Heatmap API
Sert les données SQLite au frontend + routes /control (panneau d'orchestration).

Usage:
  uvicorn api:app --host 0.0.0.0 --port 8001 --reload
"""

import math
import sqlite3
from contextlib import contextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from control import router as control_router
from paths import get_db_path

DB_PATH = get_db_path()

app = FastAPI(title="WiFi Heatmap API", version="1.0.0")
app.include_router(control_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ─── DB ───────────────────────────────────────────────────────────────────────

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/networks")
def get_networks():
    """
    Liste de tous les réseaux détectés avec stats agrégées.
    """
    with get_db() as conn:
        rows = conn.execute("""
            SELECT
                ssid,
                bssid,
                COUNT(*)        AS samples,
                ROUND(AVG(rssi), 1) AS avg_rssi,
                MAX(rssi)       AS max_rssi,
                MIN(rssi)       AS min_rssi,
                MAX(channel)    AS channel,
                MAX(encryption) AS encryption,
                MAX(timestamp)  AS last_seen
            FROM scan_points
            GROUP BY bssid
            ORDER BY samples DESC
        """).fetchall()

    return [dict(r) for r in rows]


@app.get("/heatmap")
def get_heatmap(
    bssid: Optional[str] = Query(None, description="Filtrer par BSSID"),
    min_rssi: int = Query(-100, description="RSSI minimum"),
):
    """
    Retourne les points [lat, lng, intensity] pour leaflet.heat.
    intensity est normalisée entre 0 et 1 à partir du RSSI.
    """
    with get_db() as conn:
        if bssid:
            rows = conn.execute("""
                SELECT lat, lng, rssi
                FROM scan_points
                WHERE bssid = ? AND rssi >= ?
            """, (bssid, min_rssi)).fetchall()
        else:
            rows = conn.execute("""
                SELECT lat, lng, MAX(rssi) as rssi
                FROM scan_points
                WHERE rssi >= ?
                GROUP BY ROUND(lat, 5), ROUND(lng, 5), bssid
            """, (min_rssi,)).fetchall()

    # Normalisation RSSI → intensité
    # -30 dBm (excellent) = 1.0, -90 dBm (très faible) = 0.0
    RSSI_MIN = -90
    RSSI_MAX = -30
    span = RSSI_MAX - RSSI_MIN

    points = []
    for row in rows:
        lat, lng, rssi = row["lat"], row["lng"], row["rssi"]
        intensity = max(0.0, min(1.0, (rssi - RSSI_MIN) / span))
        points.append([lat, lng, round(intensity, 3)])

    return points


@app.get("/stats")
def get_stats():
    """
    Stats globales de la session de collecte.
    """
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM scan_points").fetchone()[0]
        networks = conn.execute("SELECT COUNT(DISTINCT bssid) FROM scan_points").fetchone()[0]
        bounds = conn.execute("""
            SELECT MIN(lat), MAX(lat), MIN(lng), MAX(lng)
            FROM scan_points
        """).fetchone()
        time_range = conn.execute("""
            SELECT MIN(timestamp), MAX(timestamp) FROM scan_points
        """).fetchone()

    return {
        "total_points": total,
        "unique_networks": networks,
        "bounds": {
            "min_lat": bounds[0],
            "max_lat": bounds[1],
            "min_lng": bounds[2],
            "max_lng": bounds[3],
        } if bounds[0] else None,
        "started_at": time_range[0],
        "last_point_at": time_range[1],
    }


def _locate_ap(rows: list) -> dict:
    """
    Estime la position d'un AP à partir de mesures (lat, lng, rssi).

    Algorithme :
      1. Déduplication spatiale : on garde le RSSI max par cellule ~5 m²
         (arrondi lat/lng à 4 décimales ≈ 11 m → on prend le meilleur par case).
         Cela évite qu'un long séjour immobile gonfle le poids d'un seul endroit.
      2. Centroïde pondéré sur puissance linéaire (pas les dBm) :
         w = 10^(rssi/10) — les points proches (fort signal) tirent plus.
      3. Trilatération moindres carrés (scipy optionnel) si ≥ 3 points distincts ;
         sinon on retourne le centroïde.
    """
    # ── 1. Déduplication spatiale ──────────────────────────────────────────────
    cell: dict[tuple, tuple] = {}          # (round_lat, round_lng) → (lat, lng, rssi)
    for r in rows:
        lat, lng, rssi = r["lat"], r["lng"], r["rssi"]
        key = (round(lat, 4), round(lng, 4))
        if key not in cell or rssi > cell[key][2]:
            cell[key] = (lat, lng, rssi)

    pts = list(cell.values())              # [(lat, lng, rssi), ...]
    n = len(pts)

    # ── 2. Centroïde pondéré ──────────────────────────────────────────────────
    weights = [10 ** (rssi / 10) for _, _, rssi in pts]
    total_w = sum(weights)
    c_lat = sum(w * lat for w, (lat, _, _) in zip(weights, pts)) / total_w
    c_lng = sum(w * lng for w, (_, lng, _) in zip(weights, pts)) / total_w
    best_rssi = max(rssi for _, _, rssi in pts)

    result = {
        "method": "weighted_centroid",
        "lat": round(c_lat, 7),
        "lng": round(c_lng, 7),
        "points_used": n,
        "best_rssi": best_rssi,
        "confidence": min(1.0, round(n / 10, 2)),  # 0→1 selon nb de mesures
    }

    # ── 3. Trilatération (optionnelle, nécessite scipy) ────────────────────────
    if n >= 3:
        try:
            from scipy.optimize import minimize  # type: ignore
            import numpy as np  # type: ignore

            # Modèle log-distance : d = d0 * 10^((rssi0 - rssi) / (10*n_exp))
            # On suppose rssi0 = -30 dBm à 1 m, n_exp = 2.5 (semi-urbain)
            RSSI0, N_EXP, D0 = -30.0, 2.5, 1.0

            # Conversion (lat,lng) → mètres relatifs (projection plate)
            lat0 = sum(lat for lat, _, _ in pts) / n
            lng0 = sum(lng for _, lng, _ in pts) / n
            M_LAT = 111_320.0
            M_LNG = 111_320.0 * math.cos(math.radians(lat0))

            coords = np.array([
                ((lat - lat0) * M_LAT, (lng - lng0) * M_LNG)
                for lat, lng, _ in pts
            ])
            dists = np.array([
                D0 * 10 ** ((RSSI0 - rssi) / (10 * N_EXP))
                for _, _, rssi in pts
            ])
            # Contraindre les distances estimées (1 m – 500 m)
            dists = np.clip(dists, 1.0, 500.0)

            def cost(xy: np.ndarray) -> float:
                diff = np.sqrt(np.sum((coords - xy) ** 2, axis=1)) - dists
                return float(np.sum(diff ** 2))

            x0 = np.array([0.0, 0.0])
            res = minimize(cost, x0, method="Nelder-Mead",
                           options={"xatol": 0.5, "fatol": 0.5, "maxiter": 5000})
            if res.success or res.fun < 1e6:
                t_lat = round(lat0 + res.x[0] / M_LAT, 7)
                t_lng = round(lng0 + res.x[1] / M_LNG, 7)
                result.update({
                    "method": "trilateration",
                    "lat": t_lat,
                    "lng": t_lng,
                    "centroid_lat": round(c_lat, 7),
                    "centroid_lng": round(c_lng, 7),
                    "residual": round(float(res.fun), 2),
                })
        except ImportError:
            pass   # scipy absent → on garde le centroïde

    return result


@app.get("/network/{bssid}/locate")
def locate_ap(bssid: str):
    """
    Estime la position géographique d'un AP (access point) à partir
    des mesures RSSI enregistrées lors du parcours.

    Retourne lat/lng estimée, méthode utilisée, nombre de points distincts,
    et un indice de confiance (0–1).
    Requiert au minimum 1 point ; trilatération activée dès 3 points distincts
    (si scipy est installé).
    """
    with get_db() as conn:
        rows = conn.execute("""
            SELECT lat, lng, rssi
            FROM scan_points
            WHERE bssid = ?
            ORDER BY rssi DESC
        """, (bssid,)).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="BSSID non trouvé")

    rows = [{"lat": r[0], "lng": r[1], "rssi": r[2]} for r in rows]
    return _locate_ap(rows)


@app.get("/networks/locate")
def locate_all_aps(min_points: int = Query(3, description="Nb minimum de points distincts")):
    """
    Calcule la position estimée de tous les AP ayant au moins min_points
    mesures spatiales distinctes. Utile pour afficher les marqueurs sur la carte.
    """
    with get_db() as conn:
        bssids = conn.execute("""
            SELECT bssid, COUNT(*) as c
            FROM scan_points
            GROUP BY bssid
            HAVING c >= ?
            ORDER BY c DESC
        """, (min_points,)).fetchall()

    results = []
    with get_db() as conn:
        for row in bssids:
            bssid = row[0]
            pts = conn.execute("""
                SELECT lat, lng, rssi FROM scan_points WHERE bssid = ?
            """, (bssid,)).fetchall()
            pts_dicts = [{"lat": r[0], "lng": r[1], "rssi": r[2]} for r in pts]
            loc = _locate_ap(pts_dicts)
            # Récupérer SSID et chiffrement
            meta = conn.execute("""
                SELECT ssid, encryption FROM scan_points
                WHERE bssid = ? ORDER BY timestamp DESC LIMIT 1
            """, (bssid,)).fetchone()
            results.append({
                "bssid": bssid,
                "ssid": meta[0] if meta else "",
                "encryption": meta[1] if meta else "",
                **loc,
            })

    return results


@app.get("/network/{bssid}/timeline")
def get_network_timeline(bssid: str):
    """
    Évolution du RSSI dans le temps pour un BSSID donné.
    """
    with get_db() as conn:
        rows = conn.execute("""
            SELECT timestamp, lat, lng, rssi
            FROM scan_points
            WHERE bssid = ?
            ORDER BY timestamp
        """, (bssid,)).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="BSSID non trouvé")

    return [dict(r) for r in rows]
