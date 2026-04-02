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
    from core.state import state, media_runtime, led_runtime

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

    return jsonify({
        "ok": len(warnings) == 0,
        "warnings": warnings,
        "cpu_temp_celsius": cpu_temp,
        "ram_percent": ram.get("percent"),
        "disk_percent": disk.get("percent"),
        "player_running": media_runtime.get("player_running", False),
        "led_master_enabled": led_runtime.get("master_enabled", True),
        "pin_enabled": state.get("pin_enabled", True),
        "uptime_seconds": _uptime_seconds(),
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
    ]
    result = {tool: _check_tool(tool) for tool in tools}
    # python3 is always required; other tools are best-effort on non-RPi environments
    all_critical = result.get("python3", False)
    return jsonify({
        "tools": result,
        "all_critical_ok": all_critical,
    })
