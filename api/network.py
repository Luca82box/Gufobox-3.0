from flask import Blueprint, request, jsonify
from core.utils import run_cmd, log
from core.state import bus

network_bp = Blueprint('network', __name__)

# =========================================================
# GESTIONE WI-FI
# =========================================================
@network_bp.route("/network/status", methods=["GET"])
def api_network_status():
    """Restituisce lo stato attuale della connessione Wi-Fi"""
    code, stdout, _ = run_cmd(["iwgetid", "-r"])
    ssid = stdout.strip() if code == 0 else None
    
    code_ip, stdout_ip, _ = run_cmd(["hostname", "-I"])
    ip = stdout_ip.split()[0] if code_ip == 0 and stdout_ip else "Sconosciuto"
    
    return jsonify({
        "connected": bool(ssid),
        "ssid": ssid,
        "ip": ip,
        "signal": 85 if ssid else 0 # Mock del segnale (da implementare con iwconfig se necessario)
    })

@network_bp.route("/network/scan", methods=["GET"])
def api_network_scan():
    """Scansiona le reti Wi-Fi vicine usando nmcli (NetworkManager)"""
    # Esempio usando nmcli (standard su Raspberry Pi OS moderni)
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
    
    # Comando NetworkManager per connettersi
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
# GESTIONE BLUETOOTH
# =========================================================
@network_bp.route("/bluetooth/status", methods=["GET"])
def api_bluetooth_status():
    """Mock dello stato Bluetooth (implementare con bluetoothctl)"""
    return jsonify({
        "enabled": True,
        "connected_device": None,
        "paired_devices": []
    })

@network_bp.route("/bluetooth/scan", methods=["GET"])
def api_bluetooth_scan():
    """Mock scansione Bluetooth"""
    return jsonify({"devices": []})

