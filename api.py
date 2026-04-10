#!/usr/bin/env python3
"""
WiFi Heatmap API
Sert les données SQLite au frontend + routes /control (panneau d'orchestration).

Usage:
  uvicorn api:app --host 0.0.0.0 --port 8001 --reload
"""

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
