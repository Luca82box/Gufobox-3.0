"""
api/diag.py — Endpoints per metriche di sistema e diagnostica.

  GET /api/admin/metrics   — CPU, RAM, disco, batteria, temperatura
  GET /api/diag/summary    — riepilogo diagnostico
  GET /api/diag/tools      — verifica strumenti di sistema disponibili
"""

import os
import shutil

from flask import jsonify

from flask import Blueprint
from core.utils import log, run_cmd

diag_bp = Blueprint("diag", __name__)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _cpu_temperature() -> float | None:
    """Legge la temperatura CPU dal sysfs (funziona su RPi e molte SBC)."""
    thermal_path = "/sys/class/thermal/thermal_zone0/temp"
    try:
        with open(thermal_path, "r") as f:
            millideg = int(f.read().strip())
        return round(millideg / 1000.0, 1)
    except Exception:
        return None


def _ram_info() -> dict:
    """Legge le info RAM da /proc/meminfo (disponibile su Linux)."""
    info = {"total_mb": None, "available_mb": None, "used_mb": None, "percent": None}
    try:
        with open("/proc/meminfo", "r") as f:
            lines = f.readlines()
        mem = {}
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                mem[parts[0].rstrip(":")] = int(parts[1])
        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", 0)
        used = total - available
        info["total_mb"] = round(total / 1024, 1)
        info["available_mb"] = round(available / 1024, 1)
        info["used_mb"] = round(used / 1024, 1)
        info["percent"] = round(used / total * 100, 1) if total > 0 else None
    except Exception:
        pass
    return info


def _disk_info(path: str = "/") -> dict:
    """Legge utilizzo disco tramite shutil.disk_usage."""
    info = {"total_gb": None, "used_gb": None, "free_gb": None, "percent": None}
    try:
        usage = shutil.disk_usage(path)
        info["total_gb"] = round(usage.total / (1024 ** 3), 2)
        info["used_gb"] = round(usage.used / (1024 ** 3), 2)
        info["free_gb"] = round(usage.free / (1024 ** 3), 2)
        info["percent"] = round(usage.used / usage.total * 100, 1) if usage.total > 0 else None
    except Exception:
        pass
    return info


def _battery_info() -> dict | None:
    """
    Tenta di leggere info batteria dallo stato globale (se disponibile).
    Ritorna None se non c'è un modulo batteria.
    """
    try:
        from core.state import state
        battery = state.get("battery")
        if battery:
            return battery
    except Exception:
        pass
    return None


def _cpu_load() -> dict:
    """Legge il load average da /proc/loadavg."""
    info = {"load_1": None, "load_5": None, "load_15": None}
    try:
        with open("/proc/loadavg", "r") as f:
            parts = f.read().split()
        info["load_1"] = float(parts[0])
        info["load_5"] = float(parts[1])
        info["load_15"] = float(parts[2])
    except Exception:
        pass
    return info


def _uptime_seconds() -> int | None:
    try:
        with open("/proc/uptime", "r") as f:
            return int(float(f.read().split()[0]))
    except Exception:
        return None


def _check_tool(name: str) -> bool:
    return shutil.which(name) is not None


def _readiness_audio() -> dict:
    """
    Verifica la readiness audio in modo best-effort.
    Ritorna: {ok: bool, mpv: bool, amixer: bool, aplay: bool, note: str|None}
    """
    mpv = _check_tool("mpv")
    amixer = _check_tool("amixer")
    aplay = _check_tool("aplay")
    ok = mpv and amixer
    note = None
    if not mpv:
        note = "mpv non trovato: la riproduzione audio non funzionerà"
    elif not amixer:
        note = "amixer non trovato: il controllo volume potrebbe non funzionare"
    return {"ok": ok, "mpv": mpv, "amixer": amixer, "aplay": aplay, "note": note}


def _readiness_bluetooth() -> dict:
    """
    Verifica la readiness Bluetooth in modo best-effort.
    Ritorna: {ok: bool, bluetoothctl: bool, rfkill: bool, controller_available: bool, note: str|None}
    """
    bt_tool = _check_tool("bluetoothctl")
    rfkill = _check_tool("rfkill")

    controller_available = False
    if bt_tool:
        try:
            code, stdout, _ = run_cmd(["bluetoothctl", "show"], timeout=3)
            controller_available = code == 0 and "Controller" in stdout
        except Exception:
            pass

    ok = bt_tool and controller_available
    note = None
    if not bt_tool:
        note = "bluetoothctl non trovato: funzionalità Bluetooth non disponibili"
    elif not controller_available:
        note = "Controller Bluetooth non rilevato (best-effort: potrebbe essere rfkill bloccato)"
    return {
        "ok": ok,
        "bluetoothctl": bt_tool,
        "rfkill": rfkill,
        "controller_available": controller_available,
        "note": note,
    }


def _readiness_network() -> dict:
    """
    Verifica la readiness network in modo best-effort.
    Ritorna: {ok: bool, nmcli: bool, note: str|None}
    """
    nmcli = _check_tool("nmcli")
    ok = nmcli
    note = None if nmcli else "nmcli non trovato: gestione Wi-Fi/hotspot non disponibile"
    return {"ok": ok, "nmcli": nmcli, "note": note}


def _readiness_standby_alarm() -> dict:
    """
    Verifica la readiness del percorso standby/alarm in modo best-effort.
    Ritorna: {ok: bool, vcgencmd: bool, cpufreq_set: bool, note: str|None}
    """
    vcgencmd = _check_tool("vcgencmd")
    cpufreq = _check_tool("cpufreq-set")
    # Su RPi entrambi dovrebbero essere presenti; su CI/desktop saranno assenti
    ok = vcgencmd and cpufreq
    note = None
    if not vcgencmd and not cpufreq:
        note = "vcgencmd/cpufreq-set assenti: standby funziona in modalità software-only"
    elif not vcgencmd:
        note = "vcgencmd non trovato: HDMI power management non disponibile"
    elif not cpufreq:
        note = "cpufreq-set non trovato: CPU frequency scaling non disponibile"
    return {"ok": ok, "vcgencmd": vcgencmd, "cpufreq_set": cpufreq, "note": note}


# ─── endpoints ───────────────────────────────────────────────────────────────

@diag_bp.route("/admin/metrics", methods=["GET"])
def api_admin_metrics():
    """
    Restituisce metriche di sistema: CPU temp, RAM, disco, batteria, load.
    Best-effort: i campi mancanti (es. su ambienti non-RPi) saranno null.
    """
    return jsonify({
        "cpu_temp_celsius": _cpu_temperature(),
        "cpu_load": _cpu_load(),
        "ram": _ram_info(),
        "disk": _disk_info(),
        "battery": _battery_info(),
        "uptime_seconds": _uptime_seconds(),
    })


@diag_bp.route("/diag/summary", methods=["GET"])
def api_diag_summary():
    """
    Riepilogo diagnostico sintetico dello stato del sistema.
    """
    import os as _os
    from core.state import state, media_runtime, led_runtime, alarms_list, jobs_state
    from config import API_VERSION, BACKUP_DIR, OTA_STATE_FILE

    cpu_temp = _cpu_temperature()
    ram = _ram_info()
    disk = _disk_info()

    warnings = []
    if cpu_temp and cpu_temp > 75:
        warnings.append(f"Temperatura CPU elevata: {cpu_temp}°C")
    if ram.get("percent") and ram["percent"] > 90:
        warnings.append(f"RAM quasi esaurita: {ram['percent']}%")
    if disk.get("percent") and disk["percent"] > 90:
        warnings.append(f"Disco quasi pieno: {disk['percent']}%")

    # IP corrente (best-effort)
    ip = None
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
    except Exception:
        pass

    # OTA state (best-effort)
    ota_status = "idle"
    ota_running = False
    try:
        import json
        if _os.path.exists(OTA_STATE_FILE):
            with open(OTA_STATE_FILE, "r", encoding="utf-8") as f:
                ota_data = json.load(f)
            ota_status = ota_data.get("status", "idle")
            ota_running = ota_data.get("status") == "running"
    except Exception:
        pass

    # Backup count (best-effort)
    backup_count = 0
    try:
        if _os.path.isdir(BACKUP_DIR):
            backup_count = sum(
                1 for n in _os.listdir(BACKUP_DIR)
                if _os.path.isdir(_os.path.join(BACKUP_DIR, n))
            )
    except Exception:
        pass

    # Standby state
    in_standby = False
    standby_state = "awake"
    try:
        from core.hardware import is_in_standby, get_standby_state
        in_standby = is_in_standby()
        standby_state = get_standby_state()
    except Exception:
        pass

    # Counts
    active_jobs = sum(
        1 for j in jobs_state.values()
        if j.get("status") not in ("done", "error", "canceled")
    )
    alarm_count = len(alarms_list)

    # Readiness summary (best-effort, non crasha in ambienti non-RPi)
    readiness = {
        "audio": _readiness_audio(),
        "bluetooth": _readiness_bluetooth(),
        "network": _readiness_network(),
        "standby_alarm": _readiness_standby_alarm(),
    }

    return jsonify({
        "ok": len(warnings) == 0,
        "warnings": warnings,
        "api_version": API_VERSION,
        "ip": ip,
        "cpu_temp_celsius": cpu_temp,
        "ram_percent": ram.get("percent"),
        "disk_percent": disk.get("percent"),
        "uptime_seconds": _uptime_seconds(),
        "player_running": media_runtime.get("player_running", False),
        "player_mode": media_runtime.get("current_mode", "idle"),
        "led_master_enabled": led_runtime.get("master_enabled", True),
        "pin_enabled": state.get("pin_enabled", True),
        "in_standby": in_standby,
        "standby_state": standby_state,
        "ota_status": ota_status,
        "ota_running": ota_running,
        "backup_count": backup_count,
        "active_jobs": active_jobs,
        "alarm_count": alarm_count,
        "readiness": readiness,
    })


@diag_bp.route("/diag/tools", methods=["GET"])
def api_diag_tools():
    """
    Controlla la disponibilità degli strumenti di sistema usati da GufoBox.
    """
    tools = [
        "mpv", "ffmpeg", "git", "pip", "python3",
        "nmcli", "rfkill", "amixer", "aplay",
        "reboot", "shutdown", "cpufreq-set",
        "bluetoothctl",
    ]
    result = {tool: _check_tool(tool) for tool in tools}
    # python3 is always required; other tools are best-effort on non-RPi environments
    all_critical = result.get("python3", False)
    return jsonify({
        "tools": result,
        "all_critical_ok": all_critical,
    })
