"""
api/diag.py — Endpoints per metriche di sistema e diagnostica.

  GET  /api/admin/metrics     — CPU, RAM, disco, batteria, temperatura
  GET  /api/diag/summary      — riepilogo diagnostico
  GET  /api/diag/tools        — verifica strumenti di sistema disponibili
  GET  /api/diag/events       — event log operativo (ring buffer)
  POST /api/diag/selfcheck    — self-check operativo completo
  GET  /api/diag/export       — export diagnostica JSON
  GET  /api/gpio/pinout       — mappa pin GPIO usati dalla GufoBox
"""

import os
import shutil
from datetime import datetime, timezone

from flask import jsonify, request

from flask import Blueprint
from core.utils import log, run_cmd
from core.event_log import get_events, log_event

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
        # Audio readiness quick-access (anche disponibile in readiness.audio)
        "audio_ready": readiness["audio"].get("ok", False),
        "audio_note": readiness["audio"].get("note"),
    })


@diag_bp.route("/diag/tools", methods=["GET"])
def api_diag_tools():
    """
    Controlla la disponibilità degli strumenti di sistema usati da GufoBox.
    """
    tools = [
        "mpv", "ffmpeg", "git", "pip", "python3",
        "nmcli", "rfkill", "amixer", "aplay", "pactl",
        "reboot", "shutdown", "cpufreq-set", "vcgencmd",
        "bluetoothctl",
    ]
    result = {tool: _check_tool(tool) for tool in tools}
    # python3 is always required; other tools are best-effort on non-RPi environments
    all_critical = result.get("python3", False)
    return jsonify({
        "tools": result,
        "all_critical_ok": all_critical,
    })


# ─── event log ───────────────────────────────────────────────────────────────

@diag_bp.route("/diag/events", methods=["GET"])
def api_diag_events():
    """
    Restituisce gli eventi operativi recenti (ring buffer).
    Query param: ?limit=N  (default 100, max 500)
    """
    try:
        limit = int(request.args.get("limit", 100))
        limit = max(1, min(limit, 500))
    except (ValueError, TypeError):
        limit = 100
    events = get_events(limit=limit)
    return jsonify({"events": events, "count": len(events)})


# ─── self-check ──────────────────────────────────────────────────────────────

def _run_selfcheck() -> dict:
    """
    Esegue un self-check operativo completo.
    Restituisce un dizionario con ok, checks, warnings, errors e note.
    """
    checks = []
    warnings = []
    errors = []

    def _add(name: str, ok: bool, note: str | None = None, detail: str | None = None):
        entry = {"name": name, "ok": ok}
        if note:
            entry["note"] = note
        if detail:
            entry["detail"] = detail
        checks.append(entry)
        if not ok:
            if note:
                errors.append(f"{name}: {note}")
            else:
                errors.append(name)

    # --- essential tools ---
    for tool in ("mpv", "git", "python3"):
        present = _check_tool(tool)
        _add(f"tool:{tool}", present,
             note=None if present else f"{tool} non trovato")

    # --- audio readiness ---
    audio = _readiness_audio()
    _add("audio:mpv", audio["mpv"],
         note="mpv non trovato: riproduzione audio non disponibile" if not audio["mpv"] else None)
    _add("audio:amixer", audio["amixer"],
         note="amixer non trovato: controllo volume potrebbe non funzionare" if not audio["amixer"] else None)
    if audio.get("note") and not audio["ok"]:
        warnings.append(f"Audio: {audio['note']}")

    # --- network readiness ---
    net = _readiness_network()
    _add("network:nmcli", net["nmcli"],
         note=net.get("note") if not net["nmcli"] else None)
    if not net["nmcli"]:
        warnings.append("Network: nmcli non trovato — gestione Wi-Fi/hotspot non disponibile")

    # --- bluetooth readiness ---
    bt = _readiness_bluetooth()
    _add("bluetooth:bluetoothctl", bt["bluetoothctl"],
         note=bt.get("note") if not bt["bluetoothctl"] else None)
    _add("bluetooth:controller", bt["controller_available"],
         note="Controller Bluetooth non rilevato" if not bt["controller_available"] else None)
    if bt.get("note") and not bt["ok"]:
        warnings.append(f"Bluetooth: {bt['note']}")

    # --- standby / alarm readiness ---
    sa = _readiness_standby_alarm()
    _add("standby:vcgencmd", sa["vcgencmd"],
         note="vcgencmd non trovato: HDMI power management non disponibile" if not sa["vcgencmd"] else None)
    _add("standby:cpufreq-set", sa["cpufreq_set"],
         note="cpufreq-set non trovato: CPU scaling non disponibile" if not sa["cpufreq_set"] else None)
    if sa.get("note"):
        warnings.append(f"Standby: {sa['note']}")

    # --- system resources ---
    ram = _ram_info()
    disk = _disk_info()
    cpu_temp = _cpu_temperature()

    ram_ok = ram.get("percent") is None or ram["percent"] < 90
    disk_ok = disk.get("percent") is None or disk["percent"] < 90
    temp_ok = cpu_temp is None or cpu_temp < 75

    _add("system:ram", ram_ok,
         note=f"RAM elevata: {ram.get('percent')}%" if not ram_ok else None)
    _add("system:disk", disk_ok,
         note=f"Disco quasi pieno: {disk.get('percent')}%" if not disk_ok else None)
    _add("system:cpu_temp", temp_ok,
         note=f"Temperatura CPU elevata: {cpu_temp}°C" if not temp_ok else None)

    if not ram_ok:
        warnings.append(f"RAM quasi esaurita: {ram.get('percent')}%")
    if not disk_ok:
        warnings.append(f"Disco quasi pieno: {disk.get('percent')}%")
    if not temp_ok:
        warnings.append(f"Temperatura CPU elevata: {cpu_temp}°C")

    overall_ok = len(errors) == 0
    return {
        "ok": overall_ok,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "note": "Self-check completato — alcuni strumenti potrebbero essere assenti fuori da RPi" if not overall_ok else "Tutti i controlli principali superati",
    }


@diag_bp.route("/diag/selfcheck", methods=["POST"])
def api_diag_selfcheck():
    """
    Esegue un self-check operativo completo e registra il risultato nel log eventi.
    """
    result = _run_selfcheck()
    severity = "info" if result["ok"] else ("warning" if result["warnings"] else "error")
    log_event(
        area="selfcheck",
        severity=severity,
        message="Self-check completato" if result["ok"] else f"Self-check: {len(result['errors'])} errore/i",
        details={"ok": result["ok"], "error_count": len(result["errors"]), "warning_count": len(result["warnings"])},
    )
    return jsonify(result)


# ─── GPIO pinout ─────────────────────────────────────────────────────────────

@diag_bp.route("/gpio/pinout", methods=["GET"])
def api_gpio_pinout():
    """Ritorna la mappa dei pin GPIO usati dalla GufoBox."""
    pinout = [
        {"peripheral": "Pulsante Play/Pausa",    "gpio": 5,  "physical_pin": 29, "protocol": "GPIO Input",  "source": "hw/buttons.py"},
        {"peripheral": "Pulsante Next",           "gpio": 6,  "physical_pin": 31, "protocol": "GPIO Input",  "source": "hw/buttons.py"},
        {"peripheral": "Pulsante Prev",           "gpio": 13, "physical_pin": 33, "protocol": "GPIO Input",  "source": "hw/buttons.py"},
        {"peripheral": "Pulsante Power",          "gpio": 3,  "physical_pin": 5,  "protocol": "GPIO Input",  "source": "hw/buttons.py"},
        {"peripheral": "LED WS2813",              "gpio": 12, "physical_pin": 32, "protocol": "PWM0",        "source": "hw/led.py"},
        {"peripheral": "Amplificatore ON/OFF",    "gpio": 20, "physical_pin": 38, "protocol": "GPIO Output", "source": "hw/amp.py"},
        {"peripheral": "Amplificatore Mute",      "gpio": 26, "physical_pin": 37, "protocol": "GPIO Output", "source": "hw/amp.py"},
        {"peripheral": "RFID RC522 (CS)",         "gpio": 8,  "physical_pin": 24, "protocol": "SPI0",        "source": "hw/rfid.py"},
        {"peripheral": "RFID RC522 (SCK)",        "gpio": 11, "physical_pin": 23, "protocol": "SPI0",        "source": "hw/rfid.py"},
        {"peripheral": "RFID RC522 (MOSI)",       "gpio": 10, "physical_pin": 19, "protocol": "SPI0",        "source": "hw/rfid.py"},
        {"peripheral": "RFID RC522 (MISO)",       "gpio": 9,  "physical_pin": 21, "protocol": "SPI0",        "source": "hw/rfid.py"},
        {"peripheral": "Batteria MAX17048 (SDA)", "gpio": 2,  "physical_pin": 3,  "protocol": "I2C1",        "source": "hw/battery.py"},
        {"peripheral": "Batteria MAX17048 (SCL)", "gpio": 3,  "physical_pin": 5,  "protocol": "I2C1",        "source": "hw/battery.py"},
    ]
    return jsonify({
        "pinout": pinout,
        "notes": [
            "GPIO 3 è condiviso: funge sia da I2C1 SCL per il MAX17048, "
            "sia da pulsante Power/Wake (pull-up hardware 1.8kΩ)."
        ],
    })


# ─── export diagnostica ──────────────────────────────────────────────────────

@diag_bp.route("/diag/export", methods=["GET"])
def api_diag_export():
    """
    Esporta un snapshot diagnostico completo in JSON.
    Include: summary, tools, self-check, eventi recenti.
    """
    import json as _json

    # Summary (inline, no HTTP roundtrip)
    try:
        import os as _os
        from core.state import state, media_runtime, led_runtime, alarms_list, jobs_state
        from config import API_VERSION, BACKUP_DIR, OTA_STATE_FILE

        cpu_temp = _cpu_temperature()
        ram = _ram_info()
        disk = _disk_info()

        exp_warnings = []
        if cpu_temp and cpu_temp > 75:
            exp_warnings.append(f"Temperatura CPU elevata: {cpu_temp}°C")
        if ram.get("percent") and ram["percent"] > 90:
            exp_warnings.append(f"RAM quasi esaurita: {ram['percent']}%")
        if disk.get("percent") and disk["percent"] > 90:
            exp_warnings.append(f"Disco quasi pieno: {disk['percent']}%")

        ota_status = "idle"
        ota_running = False
        try:
            if _os.path.exists(OTA_STATE_FILE):
                with open(OTA_STATE_FILE, "r", encoding="utf-8") as f:
                    ota_data = _json.load(f)
                ota_status = ota_data.get("status", "idle")
                ota_running = ota_data.get("status") == "running"
        except Exception:
            pass

        backup_count = 0
        try:
            if _os.path.isdir(BACKUP_DIR):
                backup_count = sum(
                    1 for n in _os.listdir(BACKUP_DIR)
                    if _os.path.isdir(_os.path.join(BACKUP_DIR, n))
                )
        except Exception:
            pass

        in_standby = False
        standby_state_val = "awake"
        try:
            from core.hardware import is_in_standby, get_standby_state
            in_standby = is_in_standby()
            standby_state_val = get_standby_state()
        except Exception:
            pass

        active_jobs = sum(
            1 for j in jobs_state.values()
            if j.get("status") not in ("done", "error", "canceled")
        )

        summary_data = {
            "api_version": API_VERSION,
            "cpu_temp_celsius": cpu_temp,
            "ram_percent": ram.get("percent"),
            "disk_percent": disk.get("percent"),
            "uptime_seconds": _uptime_seconds(),
            "warnings": exp_warnings,
            "in_standby": in_standby,
            "standby_state": standby_state_val,
            "ota_status": ota_status,
            "ota_running": ota_running,
            "backup_count": backup_count,
            "active_jobs": active_jobs,
            "alarm_count": len(alarms_list),
        }
    except Exception as e:
        log(f"Errore raccolta summary per export: {e}", "warning")
        summary_data = {"error": "Impossibile raccogliere il riepilogo di sistema"}

    # Tools
    tools_list = [
        "mpv", "ffmpeg", "git", "pip", "python3",
        "nmcli", "rfkill", "amixer", "aplay", "pactl",
        "reboot", "shutdown", "cpufreq-set", "vcgencmd", "bluetoothctl",
    ]
    tools_data = {tool: _check_tool(tool) for tool in tools_list}

    # Self-check (non-destructive, no side effects)
    selfcheck_data = _run_selfcheck()

    # Recent events
    events_data = get_events(limit=50)

    return jsonify({
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary_data,
        "tools": tools_data,
        "selfcheck": selfcheck_data,
        "recent_events": events_data,
    })
