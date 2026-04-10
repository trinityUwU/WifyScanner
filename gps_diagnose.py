#!/usr/bin/env python3
"""
Vérifie gpsd : messages SKY (satellites) et TPV (position).

Usage : venv/bin/python gps_diagnose.py
        (gpsd doit tourner : sudo systemctl status gpsd)

Interprétation rapide :
  - mode TPV 0/1 = pas de position ; 2 = fix 2D ; 3 = fix 3D
  - SKY satellites_visible = 0 → aucun signal satellite (intérieur, antenne, matériel)
"""
import json
import sys

try:
    from gpsdclient import GPSDClient
except ImportError:
    print("Installez les deps : venv/bin/pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    host = "127.0.0.1"
    port = 2947
    print(f"Connexion à gpsd {host}:{port}… (Ctrl+C pour arrêter)\n")
    last_sky_key: tuple[int, int] | None = None
    try:
        with GPSDClient(host=host, port=port) as client:
            for result in client.dict_stream(convert_datetime=True):
                cls = result.get("class")
                if cls == "SKY":
                    sats = result.get("satellites") or []
                    n = len(sats)
                    u = sum(1 for s in sats if s.get("used"))
                    key = (n, u)
                    if key != last_sky_key:
                        last_sky_key = key
                        print(
                            json.dumps(
                                {
                                    "class": "SKY",
                                    "satellites_visible": n,
                                    "satellites_used": u,
                                }
                            ),
                            flush=True,
                        )
                elif cls == "TPV":
                    slim = {
                        "class": "TPV",
                        "mode": result.get("mode"),
                        "lat": result.get("lat"),
                        "lon": result.get("lon"),
                        "time": str(result.get("time", "")),
                    }
                    print(json.dumps(slim, default=str), flush=True)
    except ConnectionRefusedError:
        print(
            "Connexion refusée — gpsd ne tourne pas ou n’écoute pas sur 2947.\n"
            "  sudo systemctl status gpsd\n"
            "  sudo systemctl restart gpsd",
            file=sys.stderr,
        )
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nOK.")


if __name__ == "__main__":
    main()
