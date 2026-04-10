"""
Panneau de contrôle HTTP : dépendances projet, statut, lancement du collecteur.

Sécurité : réseau local (ex. Raspberry Pi + téléphone). Si CYBERALPHA_CONTROL_TOKEN
est défini, les requêtes POST vers /control/* exigent Authorization: Bearer <token>.
Les GET (statut, preflight, logs) restent ouverts.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
from collections import deque
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from pathlib import Path

from paths import ROOT, get_db_path

router = APIRouter(prefix="/control", tags=["control"])

VENV_PY = ROOT / "venv" / "bin" / "python"
COLLECTOR_SCRIPT = ROOT / "collector.py"
FRONTEND_DIR = ROOT / "frontend"
REQ_FILE = ROOT / "requirements.txt"

LOG_LINES: deque[str] = deque(maxlen=500)
_state_lock = threading.Lock()
_collector_proc: Optional[subprocess.Popen[str]] = None


def _token_configured() -> bool:
    return bool(os.environ.get("CYBERALPHA_CONTROL_TOKEN", "").strip())


def _check_write_token(authorization: Optional[str]) -> None:
    tok = os.environ.get("CYBERALPHA_CONTROL_TOKEN", "").strip()
    if not tok:
        return
    if authorization != f"Bearer {tok}":
        raise HTTPException(status_code=401, detail="Token d'accès invalide ou manquant")


def _append_log(line: str) -> None:
    with _state_lock:
        LOG_LINES.append(line.rstrip())


def _run_cmd(
    args: list[str],
    cwd: str,
    timeout: int = 600,
) -> dict[str, Any]:
    try:
        r = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (r.stdout or "") + (r.stderr or "")
        return {
            "ok": r.returncode == 0,
            "returncode": r.returncode,
            "output": out[-20000:] if len(out) > 20000 else out,
        }
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "returncode": -1, "output": str(e)}
    except FileNotFoundError as e:
        return {"ok": False, "returncode": -1, "output": f"Commande introuvable: {e}"}


def _which(name: str) -> Optional[str]:
    return shutil.which(name)


def _iw_interfaces() -> list[dict[str, str]]:
    r = _run_cmd(["iw", "dev"], cwd=str(ROOT), timeout=8)
    if not r["ok"]:
        return []
    interfaces: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in r["output"].splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"Interface\s+(\S+)", line)
        if m:
            if current.get("name"):
                interfaces.append(current)
            current = {"name": m.group(1), "type": ""}
            continue
        if "name" not in current:
            continue
        if line.startswith("type "):
            current["type"] = line.split(None, 1)[-1].strip()
        if line.startswith("addr "):
            current["addr"] = line.split(None, 1)[-1].strip()
    if current.get("name"):
        interfaces.append(current)
    return interfaces


def _list_serial_usb() -> list[str]:
    dev = Path("/dev")
    if not dev.is_dir():
        return []
    out: list[str] = []
    for pat in ("ttyACM*", "ttyUSB*"):
        out.extend(str(p) for p in sorted(dev.glob(pat)) if p.exists())
    return sorted(set(out))


def _read_etc_default_gpsd_devices_line() -> Optional[str]:
    try:
        text = Path("/etc/default/gpsd").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("DEVICES="):
            return s
    return None


def _gpsd_active() -> Optional[bool]:
    try:
        p = subprocess.run(
            ["systemctl", "is-active", "gpsd"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        return None
    out = (p.stdout or "").strip()
    if out == "active":
        return True
    if out in ("inactive", "failed", "dead"):
        return False
    return None


def collector_running() -> tuple[bool, Optional[int]]:
    global _collector_proc
    with _state_lock:
        if _collector_proc is None:
            return False, None
        poll = _collector_proc.poll()
        if poll is not None:
            _collector_proc = None
            return False, None
        return True, _collector_proc.pid


def _read_output_thread(proc: subprocess.Popen[str]) -> None:
    assert proc.stdout
    try:
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            _append_log(line)
    except Exception as e:
        _append_log(f"[log thread] {e}")
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass


@router.get("/status")
def control_status() -> dict[str, Any]:
    running, pid = collector_running()
    venv_ok = VENV_PY.is_file()
    node_modules = (FRONTEND_DIR / "node_modules").is_dir()
    gpsd = _gpsd_active()
    return {
        "project_root": str(ROOT),
        "db_path": get_db_path(),
        "venv_python": str(VENV_PY),
        "venv_ready": venv_ok,
        "frontend_node_modules": node_modules,
        "collector": {"running": running, "pid": pid},
        "gpsd_active": gpsd,
        "sudo_collector": os.environ.get("CYBERALPHA_SUDO_COLLECTOR", "").lower()
        in ("1", "true", "yes"),
        "control_token_set": _token_configured(),
    }


@router.get("/gps/status")
def gps_status() -> dict[str, Any]:
    """
    État clé GPS : ports série, ligne DEVICES dans /etc/default/gpsd,
    échantillon TPV via gpspipe (nécessite un fix pour mode >= 2).
    """
    serial = _list_serial_usb()
    dev_line = _read_etc_default_gpsd_devices_line()
    devices_empty = False
    if dev_line:
        m = re.match(r"DEVICES=(.*)", dev_line.strip())
        if m:
            val = m.group(1).strip().strip('"').strip("'")
            devices_empty = val == ""
        else:
            devices_empty = True

    best: Optional[dict[str, Any]] = None
    gpspipe_err: Optional[str] = None
    gpspipe_bin = _which("gpspipe")
    if gpspipe_bin:
        try:
            r = subprocess.run(
                [gpspipe_bin, "-w", "-n", "40"],
                capture_output=True,
                text=True,
                timeout=14,
            )
            for line in r.stdout.splitlines():
                try:
                    j = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if j.get("class") != "TPV":
                    continue
                mode = int(j.get("mode") or 0)
                if best is None or mode > int(best.get("mode") or 0):
                    best = {
                        "mode": mode,
                        "lat": j.get("lat"),
                        "lon": j.get("lon"),
                    }
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            gpspipe_err = str(e)
    else:
        gpspipe_err = "gpspipe introuvable (paquet gpsd)"

    hints: list[str] = []
    if not serial:
        hints.append("Aucun port /dev/ttyACM* ou /dev/ttyUSB* détecté — branchez la clé USB.")
    if devices_empty:
        hints.append(
            "DEVICES est vide dans /etc/default/gpsd : systemd ne sait pas quel port utiliser. "
            "Exécutez la commande « Configurer gpsd » ci-dessous (sudo)."
        )
    if best is None and not gpspipe_err:
        hints.append("Aucun message TPV reçu — vérifier systemctl status gpsd.")
    elif best is not None and int(best.get("mode") or 0) < 2:
        hints.append(
            "Mode TPV < 2 : pas encore de position. Vue ciel / fenêtre, 1–3 min au démarrage ; "
            "essayez sudo systemctl stop ModemManager si le port est bloqué."
        )

    script = ROOT / "scripts" / "configure_gpsd.sh"
    if serial:
        suggest = f"sudo bash {script} {serial[0]}"
    else:
        suggest = f"sudo bash {script} /dev/ttyACM0"

    return {
        "serial_devices": serial,
        "etc_default_gpsd_devices_line": dev_line,
        "devices_config_empty": devices_empty,
        "gpsd_active": _gpsd_active(),
        "tpv_sample": best,
        "fix_ok": bool(best and int(best.get("mode") or 0) >= 2),
        "gpspipe_error": gpspipe_err,
        "configure_gpsd_command": str(suggest) if script.is_file() else None,
        "hints": hints,
    }


@router.get("/gps/live")
def gps_live() -> dict[str, Any]:
    """
    Snapshot GPS temps réel : dernier TPV (position, vitesse, précision) + dernier SKY
    (DOP, satellites). Prévu pour un polling court (~2 s) côté frontend.
    Renvoie {"tpv": {...}, "sky": {...}, "satellites": [...], "error": null | str}.
    """
    gpspipe_bin = _which("gpspipe")
    if not gpspipe_bin:
        return {"tpv": None, "sky": None, "satellites": [], "error": "gpspipe introuvable"}

    try:
        r = subprocess.run(
            [gpspipe_bin, "-w", "-n", "30"],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return {"tpv": None, "sky": None, "satellites": [], "error": "gpspipe timeout"}
    except FileNotFoundError as e:
        return {"tpv": None, "sky": None, "satellites": [], "error": str(e)}

    tpv: Optional[dict[str, Any]] = None
    sky: Optional[dict[str, Any]] = None

    for line in r.stdout.splitlines():
        try:
            j = json.loads(line)
        except json.JSONDecodeError:
            continue
        cls = j.get("class")
        if cls == "TPV":
            mode = int(j.get("mode") or 0)
            if tpv is None or mode > int(tpv.get("mode") or 0):
                tpv = j
        elif cls == "SKY":
            if sky is None or len(j.get("satellites") or []) > len((sky or {}).get("satellites") or []):
                sky = j

    sats = []
    if sky and sky.get("satellites"):
        for s in sky["satellites"]:
            gnssid = s.get("gnssid", 0)
            constellation = {0: "GP", 1: "SB", 2: "GA", 3: "BD", 5: "QZ", 6: "GL"}.get(gnssid, "??")
            sats.append({
                "constellation": constellation,
                "prn": s.get("PRN"),
                "el": s.get("el"),
                "az": s.get("az"),
                "ss": s.get("ss"),
                "used": s.get("used", False),
            })
        sats.sort(key=lambda x: (not x["used"], -(x["ss"] or 0)))

    tpv_out: Optional[dict[str, Any]] = None
    if tpv:
        tpv_out = {
            "mode": tpv.get("mode"),
            "time": tpv.get("time"),
            "lat": tpv.get("lat"),
            "lon": tpv.get("lon"),
            "altHAE": tpv.get("altHAE"),
            "altMSL": tpv.get("altMSL") or tpv.get("alt"),
            "speed": tpv.get("speed"),
            "track": tpv.get("track"),
            "climb": tpv.get("climb"),
            "epx": tpv.get("epx"),
            "epy": tpv.get("epy"),
            "epv": tpv.get("epv"),
            "eph": tpv.get("eph"),
            "sep": tpv.get("sep"),
            "leapseconds": tpv.get("leapseconds"),
        }

    sky_out: Optional[dict[str, Any]] = None
    if sky:
        sky_out = {
            "nSat": sky.get("nSat"),
            "uSat": sky.get("uSat"),
            "hdop": sky.get("hdop"),
            "vdop": sky.get("vdop"),
            "pdop": sky.get("pdop"),
            "tdop": sky.get("tdop"),
            "xdop": sky.get("xdop"),
            "ydop": sky.get("ydop"),
            "gdop": sky.get("gdop"),
        }

    return {"tpv": tpv_out, "sky": sky_out, "satellites": sats, "error": None}


@router.get("/preflight")
def preflight() -> dict[str, Any]:
    missing: list[str] = []
    for cmd in ("iw", "npm"):
        if not _which(cmd):
            missing.append(cmd)
    hints: list[str] = []
    if "iw" in missing:
        hints.append("Installez iw (ex. Arch: sudo pacman -S iw)")
    if "npm" in missing:
        hints.append("Installez Node.js / npm (ex. sudo pacman -S nodejs npm)")
    return {
        "missing_commands": missing,
        "hints": hints,
        "interfaces": _iw_interfaces(),
    }


@router.post("/tasks/python-deps")
def task_python_deps(authorization: Optional[str] = Header(None, alias="Authorization")) -> dict[str, Any]:
    _check_write_token(authorization)
    if not VENV_PY.is_file():
        raise HTTPException(
            status_code=400,
            detail="venv/bin/python introuvable. Créez le venv: python3.11 -m venv venv",
        )
    if not REQ_FILE.is_file():
        raise HTTPException(status_code=400, detail="requirements.txt introuvable")
    res = _run_cmd(
        [str(VENV_PY), "-m", "pip", "install", "--upgrade", "pip"],
        cwd=str(ROOT),
        timeout=300,
    )
    if not res["ok"]:
        return {"step": "pip_upgrade", **res}
    res2 = _run_cmd(
        [str(VENV_PY), "-m", "pip", "install", "-r", str(REQ_FILE)],
        cwd=str(ROOT),
        timeout=600,
    )
    return {"step": "requirements", **res2}


@router.post("/tasks/frontend-deps")
def task_frontend_deps(authorization: Optional[str] = Header(None, alias="Authorization")) -> dict[str, Any]:
    _check_write_token(authorization)
    if not FRONTEND_DIR.is_dir():
        raise HTTPException(status_code=400, detail="Dossier frontend introuvable")
    npm = _which("npm")
    if not npm:
        raise HTTPException(status_code=400, detail="npm introuvable dans le PATH")
    res = _run_cmd([npm, "install"], cwd=str(FRONTEND_DIR), timeout=600)
    return {"step": "npm_install", **res}


class CollectorStartBody(BaseModel):
    interface: str = Field(..., min_length=1, description="Interface monitor (ex. wlan0mon)")
    db: Optional[str] = Field(None, description="Chemin SQLite (défaut: CYBERALPHA_DB / wifi_heatmap.db)")


@router.post("/collector/start")
def collector_start(
    body: CollectorStartBody,
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _check_write_token(authorization)
    global _collector_proc
    if not COLLECTOR_SCRIPT.is_file():
        raise HTTPException(status_code=500, detail="collector.py introuvable")
    if not VENV_PY.is_file():
        raise HTTPException(status_code=400, detail="venv/bin/python introuvable")

    running, _ = collector_running()
    if running:
        raise HTTPException(status_code=409, detail="Le collecteur tourne déjà")

    if not re.match(r"^[a-zA-Z0-9._-]+$", body.interface):
        raise HTTPException(status_code=400, detail="Nom d'interface invalide")

    db_path = body.db or get_db_path()

    cmd: list[str] = [str(VENV_PY), str(COLLECTOR_SCRIPT), "-i", body.interface, "--db", db_path]
    if os.environ.get("CYBERALPHA_SUDO_COLLECTOR", "").lower() in ("1", "true", "yes"):
        cmd = ["sudo", "-n", *cmd]

    _append_log(f"$ {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    with _state_lock:
        _collector_proc = proc

    t = threading.Thread(target=_read_output_thread, args=(proc,), daemon=True)
    t.start()

    return {"started": True, "pid": proc.pid, "interface": body.interface, "db": db_path}


@router.post("/collector/stop")
def collector_stop(authorization: Optional[str] = Header(None, alias="Authorization")) -> dict[str, Any]:
    _check_write_token(authorization)
    global _collector_proc
    with _state_lock:
        proc = _collector_proc
    if proc is None or proc.poll() is not None:
        with _state_lock:
            _collector_proc = None
        return {"stopped": False, "message": "Aucun collecteur actif"}
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        raise HTTPException(
            status_code=500,
            detail="Permission refusée pour arrêter le processus (essayez le même utilisateur / sudo)",
        )
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    with _state_lock:
        _collector_proc = None
    _append_log("[*] Collecteur arrêté (SIGTERM/SIGKILL)")
    return {"stopped": True}


@router.get("/collector/logs")
def collector_logs(tail: int = 200) -> dict[str, Any]:
    with _state_lock:
        lines = list(LOG_LINES)
    if tail > 0:
        lines = lines[-tail:]
    return {"lines": lines}


@router.post("/collector/logs/clear")
def collector_logs_clear(authorization: Optional[str] = Header(None, alias="Authorization")) -> dict[str, str]:
    _check_write_token(authorization)
    with _state_lock:
        LOG_LINES.clear()
    return {"ok": "true"}
