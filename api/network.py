import eventlet

from flask import Blueprint, request, jsonify
from core.utils import run_cmd, log
from core.state import bus
from config import HOTSPOT_SSID, HOTSPOT_PASS, HOTSPOT_CONN_NAME

network_bp = Blueprint('network', __name__)

# =========================================================
# GESTIONE WI-FI
# =========================================================
@network_bp.route("/network/status", methods=["GET"])
def api_network_status():
    """Restituisce lo stato attuale della connessione Wi-Fi e hotspot"""
    code, stdout, _ = run_cmd(["iwgetid", "-r"])
    ssid = stdout.strip() if code == 0 else None
    
    code_ip, stdout_ip, _ = run_cmd(["hostname", "-I"])
    ip = stdout_ip.split()[0] if code_ip == 0 and stdout_ip else "Sconosciuto"

    # Stato hotspot: controlla se la connessione AP è attiva
    hotspot_active = False
    code_h, stdout_h, _ = run_cmd(
        ["sudo", "nmcli", "-t", "-f", "NAME,TYPE,STATE", "con", "show", "--active"],
        timeout=5
    )
    if code_h == 0:
        for line in stdout_h.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[0] == HOTSPOT_CONN_NAME and parts[2] == "activated":
                hotspot_active = True
                break

    return jsonify({
        "connected": bool(ssid),
        "ssid": ssid,
        "ip": ip,
        "signal": 85 if ssid else 0,
        "hotspot_active": hotspot_active,
        "hotspot_ssid": HOTSPOT_SSID if hotspot_active else None,
    })

@network_bp.route("/network/scan", methods=["GET"])
def api_network_scan():
    """Scansiona le reti Wi-Fi vicine usando nmcli (NetworkManager)"""
    code, stdout, _ = run_cmd(["sudo", "nmcli", "-t", "-f", "SSID,SECURITY,SIGNAL", "dev", "wifi"])
    networks = []
    
    if code == 0:
        for line in stdout.split("\n"):
            if not line: continue
            parts = line.split(":")
            if len(parts) >= 3 and parts[0]:
                networks.append({
                    "ssid": parts[0],
                    "secure": parts[1] != "" and parts[1] != "--",
                    "signal": int(parts[2]) if parts[2].isdigit() else 0
                })
                
    # Rimuove duplicati mantenendo il segnale migliore
    unique_nets = {n["ssid"]: n for n in sorted(networks, key=lambda x: x["signal"])}
    return jsonify({"networks": sorted(unique_nets.values(), key=lambda x: x["signal"], reverse=True)})

@network_bp.route("/network/connect", methods=["POST"])
def api_network_connect():
    data = request.get_json(silent=True) or {}
    ssid = data.get("ssid")
    password = data.get("password", "")
    
    if not ssid:
        return jsonify({"error": "SSID mancante"}), 400
        
    log(f"Tentativo di connessione a {ssid}...", "info")
    bus.emit_notification(f"Connessione a {ssid} in corso...", "info")
    
    cmd = ["sudo", "nmcli", "dev", "wifi", "connect", ssid]
    if password:
        cmd.extend(["password", password])
        
    code, _, err = run_cmd(cmd, timeout=30)
    
    if code == 0:
        bus.emit_notification("Connessione Wi-Fi stabilita!", "success")
        return jsonify({"status": "ok"})
    else:
        return jsonify({"error": f"Errore di connessione: {err}"}), 500

# =========================================================
# HOTSPOT (Access Point con nmcli)
# =========================================================

def _ensure_hotspot_connection():
    """
    Crea la connessione nmcli per l'hotspot se non esiste già.
    Usa 802-11-wireless.mode ap con ipv4.method shared e wpa-psk.
    """
    # Controlla se la connessione esiste già
    code, stdout, _ = run_cmd(
        ["sudo", "nmcli", "-t", "-f", "NAME", "con", "show"], timeout=5
    )
    if code == 0 and HOTSPOT_CONN_NAME in stdout.splitlines():
        return True  # Già creata

    log(f"Creazione connessione hotspot '{HOTSPOT_CONN_NAME}'...", "info")
    cmds = [
        ["sudo", "nmcli", "con", "add", "type", "wifi",
         "ifname", "wlan0", "con-name", HOTSPOT_CONN_NAME,
         "autoconnect", "no", "ssid", HOTSPOT_SSID],
        ["sudo", "nmcli", "con", "modify", HOTSPOT_CONN_NAME,
         "802-11-wireless.mode", "ap",
         "802-11-wireless.band", "bg",
         "ipv4.method", "shared"],
        ["sudo", "nmcli", "con", "modify", HOTSPOT_CONN_NAME,
         "wifi-sec.key-mgmt", "wpa-psk",
         "wifi-sec.psk", HOTSPOT_PASS],
    ]
    for cmd in cmds:
        code, _, err = run_cmd(cmd, timeout=10)
        if code != 0:
            log(f"Errore creazione hotspot: {err}", "warning")
            return False
    return True


@network_bp.route("/network/hotspot/start", methods=["POST"])
def api_hotspot_start():
    """Avvia l'hotspot Wi-Fi GufoBox tramite nmcli."""
    log("Avvio hotspot...", "info")
    if not _ensure_hotspot_connection():
        return jsonify({"error": "Impossibile creare la connessione hotspot"}), 500

    code, _, err = run_cmd(
        ["sudo", "nmcli", "con", "up", HOTSPOT_CONN_NAME], timeout=15
    )
    if code == 0:
        bus.emit_notification(f"Hotspot '{HOTSPOT_SSID}' attivo! 📡", "success")
        log(f"Hotspot '{HOTSPOT_SSID}' avviato", "info")
        return jsonify({"status": "ok", "ssid": HOTSPOT_SSID})
    else:
        log(f"Errore avvio hotspot: {err}", "warning")
        return jsonify({"error": "Impossibile avviare l'hotspot. Controlla il log per i dettagli."}), 500


@network_bp.route("/network/hotspot/stop", methods=["POST"])
def api_hotspot_stop():
    """Ferma l'hotspot Wi-Fi."""
    log("Arresto hotspot...", "info")
    code, _, err = run_cmd(
        ["sudo", "nmcli", "con", "down", HOTSPOT_CONN_NAME], timeout=10
    )
    if code == 0:
        bus.emit_notification("Hotspot disattivato", "info")
        log("Hotspot disattivato", "info")
        return jsonify({"status": "ok"})
    else:
        log(f"Errore arresto hotspot: {err}", "warning")
        return jsonify({"error": "Impossibile fermare l'hotspot. Controlla il log per i dettagli."}), 500

def _parse_bt_device_line(line):
    """
    Parsifica una riga nel formato 'Device AA:BB:CC:DD:EE:FF Nome'.
    Ritorna un dict {name, mac} oppure None se la riga non è valida.
    Il MAC viene usato come fallback per il nome se non è disponibile.
    """
    parts = line.strip().split(" ", 2)
    if len(parts) >= 2 and parts[0] == "Device":
        mac = parts[1]
        name = parts[2].strip() if len(parts) >= 3 else mac
        if not name:
            name = mac
        return {"name": name, "mac": mac}
    return None

def _detect_bt_mode(paired_devices):
    """
    Determina se GufoBox sta inviando audio (sink), ricevendo audio (source) o è idle.
    - sink:   GufoBox è connesso a un device esterno come uscita audio (casse/cuffie)
    - source: GufoBox riceve audio da una sorgente esterna (telefono/tablet) — modalità speaker
    - idle:   nessuna connessione audio attiva

    La rilevazione avviene controllando il profilo A2DP di ogni device connesso via bluetoothctl.
    """
    for dev in paired_devices:
        code_i, stdout_i, _ = run_cmd(["bluetoothctl", "info", dev["mac"]], timeout=5)
        if code_i != 0 or "Connected: yes" not in stdout_i:
            continue
        # Se il profilo A2DP sink è attivo, GufoBox invia audio verso quel device
        if "0000110b" in stdout_i.lower() or "a2dp-sink" in stdout_i.lower():
            return "sink"
        # Se il profilo A2DP source è attivo, GufoBox riceve audio da quel device
        if "0000110a" in stdout_i.lower() or "a2dp-source" in stdout_i.lower():
            return "source"
    return "idle"

# =========================================================
# GESTIONE BLUETOOTH — rotte
# =========================================================

@network_bp.route("/bluetooth/status", methods=["GET"])
def api_bluetooth_status():
    """
    Restituisce lo stato Bluetooth completo.

    Payload:
    {
      "enabled": true,
      "connected_device": {"name": "...", "mac": "AA:BB:..."} | null,
      "paired_devices": [{"name": "...", "mac": "AA:BB:..."}],
      "mode": "sink" | "source" | "idle"
    }
    """
    enabled = False
    connected_device = None
    paired_devices = []

    try:
        code, stdout, _ = run_cmd(["bluetoothctl", "show"], timeout=5)
        if code == 0:
            enabled = "Powered: yes" in stdout

        if enabled:
            code_p, stdout_p, _ = run_cmd(["bluetoothctl", "paired-devices"], timeout=5)
            if code_p == 0:
                for line in stdout_p.splitlines():
                    dev = _parse_bt_device_line(line)
                    if dev:
                        paired_devices.append(dev)

                        # Controlla se questo device è attualmente connesso
                        if connected_device is None:
                            code_i, stdout_i, _ = run_cmd(
                                ["bluetoothctl", "info", dev["mac"]], timeout=5
                            )
                            if code_i == 0 and "Connected: yes" in stdout_i:
                                connected_device = dev

    except Exception as e:
        log(f"Errore lettura stato Bluetooth: {e}", "warning")

    mode = _detect_bt_mode(paired_devices) if enabled else "idle"

    return jsonify({
        "enabled": enabled,
        "connected_device": connected_device,
        "paired_devices": paired_devices,
        "mode": mode,
    })

@network_bp.route("/bluetooth/toggle", methods=["POST"])
def api_bluetooth_toggle():
    """Accende o spegne il controller Bluetooth."""
    data = request.get_json(silent=True) or {}
    enable = data.get("enabled", True)
    cmd_arg = "power on" if enable else "power off"
    code, _, err = run_cmd(["bluetoothctl", cmd_arg], timeout=5)
    if code != 0:
        log(f"Bluetooth toggle fallito: {err}", "warning")
        return jsonify({"error": "Impossibile cambiare stato Bluetooth"}), 500
    return jsonify({"status": "ok", "enabled": enable})

@network_bp.route("/bluetooth/scan", methods=["GET"])
def api_bluetooth_scan():
    """
    Avvia una scansione Bluetooth e ritorna i dispositivi trovati.

    Payload:
    {"devices": [{"name": "...", "mac": "AA:BB:..."}]}
    """
    devices = []

    try:
        run_cmd(["bluetoothctl", "scan", "on"], timeout=3)
        eventlet.sleep(5)
        run_cmd(["bluetoothctl", "scan", "off"], timeout=3)

        code, stdout, _ = run_cmd(["bluetoothctl", "devices"], timeout=5)
        if code == 0:
            for line in stdout.splitlines():
                dev = _parse_bt_device_line(line)
                if dev:
                    devices.append(dev)

    except Exception as e:
        log(f"Errore scansione Bluetooth: {e}", "warning")
        return jsonify({"devices": [], "error": "Scansione Bluetooth non disponibile"})

    return jsonify({"devices": devices})

@network_bp.route("/bluetooth/connect", methods=["POST"])
def api_bluetooth_connect():
    """
    Connette GufoBox a un device Bluetooth esterno (casse/cuffie).
    Payload: {"mac": "AA:BB:CC:DD:EE:FF"}
    """
    data = request.get_json(silent=True) or {}
    mac = data.get("mac", "").strip()
    if not mac:
        return jsonify({"error": "MAC mancante"}), 400

    log(f"Bluetooth: tentativo connessione a {mac}", "info")

    # Prima accoppia se non già paired, poi connetti
    run_cmd(["bluetoothctl", "pair", mac], timeout=15)
    run_cmd(["bluetoothctl", "trust", mac], timeout=5)
    code, _, err = run_cmd(["bluetoothctl", "connect", mac], timeout=15)

    if code == 0:
        bus.emit_notification(f"Bluetooth connesso a {mac}!", "success")
        return jsonify({"status": "ok", "mac": mac})
    else:
        log(f"Bluetooth: connessione a {mac} fallita: {err}", "warning")
        return jsonify({"error": f"Impossibile connettersi al dispositivo {mac}"}), 500

@network_bp.route("/bluetooth/disconnect", methods=["POST"])
def api_bluetooth_disconnect():
    """Disconnette il device Bluetooth attualmente connesso."""
    # Trova il device connesso
    try:
        code_p, stdout_p, _ = run_cmd(["bluetoothctl", "paired-devices"], timeout=5)
        if code_p == 0:
            for line in stdout_p.splitlines():
                dev = _parse_bt_device_line(line)
                if dev:
                    code_i, stdout_i, _ = run_cmd(
                        ["bluetoothctl", "info", dev["mac"]], timeout=5
                    )
                    if code_i == 0 and "Connected: yes" in stdout_i:
                        run_cmd(["bluetoothctl", "disconnect", dev["mac"]], timeout=10)
                        log(f"Bluetooth: disconnesso da {dev['mac']}", "info")
                        return jsonify({"status": "ok"})
    except Exception as e:
        log(f"Bluetooth: errore disconnessione: {e}", "warning")
        return jsonify({"error": "Errore durante la disconnessione Bluetooth"}), 500

    return jsonify({"status": "ok", "info": "Nessun device connesso"})

@network_bp.route("/bluetooth/forget", methods=["POST"])
def api_bluetooth_forget():
    """
    Rimuove (unpair) un device Bluetooth.
    Payload: {"mac": "AA:BB:CC:DD:EE:FF"}
    """
    data = request.get_json(silent=True) or {}
    mac = data.get("mac", "").strip()
    if not mac:
        return jsonify({"error": "MAC mancante"}), 400

    # Disconnetti prima se connesso
    run_cmd(["bluetoothctl", "disconnect", mac], timeout=10)
    code, _, err = run_cmd(["bluetoothctl", "remove", mac], timeout=10)

    if code == 0:
        log(f"Bluetooth: rimosso device {mac}", "info")
        return jsonify({"status": "ok", "mac": mac})
    else:
        log(f"Bluetooth: impossibile rimuovere {mac}: {err}", "warning")
        return jsonify({"error": f"Impossibile rimuovere il dispositivo {mac}"}), 500

# =========================================================
# BLUETOOTH MODALITÀ SPEAKER (GufoBox come cassa/ricevitore)
# =========================================================

@network_bp.route("/bluetooth/source-mode", methods=["GET"])
def api_bluetooth_source_mode_get():
    """
    Restituisce lo stato della modalità ricevitore Bluetooth.
    In questa modalità GufoBox si presenta come speaker/cassa per sorgenti esterne
    (telefono, tablet, ecc.).

    Nota: la modalità A2DP sink lato sistema richiede BlueALSA / PipeWire configurato.
    Qui gestiamo discoverable + pairable che sono i prerequisiti necessari.
    """
    discoverable = False
    pairable = False
    try:
        code, stdout, _ = run_cmd(["bluetoothctl", "show"], timeout=5)
        if code == 0:
            discoverable = "Discoverable: yes" in stdout
            pairable = "Pairable: yes" in stdout
    except Exception as e:
        log(f"Bluetooth source-mode GET errore: {e}", "warning")

    enabled = discoverable and pairable
    return jsonify({
        "enabled": enabled,
        "discoverable": discoverable,
        "pairable": pairable,
        "mode": "source" if enabled else "idle",
    })

@network_bp.route("/bluetooth/source-mode", methods=["POST"])
def api_bluetooth_source_mode_post():
    """
    Abilita o disabilita la modalità speaker Bluetooth (GufoBox come cassa).
    Payload: {"enabled": true}

    Quando abilitata:
    - rende GufoBox discoverable e pairable
    - un telefono/tablet potrà trovarlo e collegarlo come speaker Bluetooth

    Nota: per l'audio A2DP lato sistema è necessario BlueALSA o PipeWire con profilo A2DP sink.
    Questo endpoint gestisce la parte BlueZ (visibilità) in modo best-effort.
    """
    data = request.get_json(silent=True) or {}
    enable = data.get("enabled", True)

    errors = []

    if enable:
        c1, _, e1 = run_cmd(["bluetoothctl", "discoverable", "on"], timeout=5)
        c2, _, e2 = run_cmd(["bluetoothctl", "pairable", "on"], timeout=5)
        if c1 != 0:
            errors.append(f"discoverable: {e1}")
        if c2 != 0:
            errors.append(f"pairable: {e2}")
        log("Bluetooth source-mode: GufoBox ora visibile come speaker", "info")
    else:
        c1, _, e1 = run_cmd(["bluetoothctl", "discoverable", "off"], timeout=5)
        c2, _, e2 = run_cmd(["bluetoothctl", "pairable", "off"], timeout=5)
        if c1 != 0:
            errors.append(f"discoverable: {e1}")
        if c2 != 0:
            errors.append(f"pairable: {e2}")
        log("Bluetooth source-mode: GufoBox non più visibile come speaker", "info")

    if errors:
        log(f"Bluetooth source-mode errori parziali: {errors}", "warning")

    return jsonify({
        "enabled": enable,
        "discoverable": enable,
        "pairable": enable,
        "mode": "source" if enable else "idle",
        "partial_failure": bool(errors),
    })

