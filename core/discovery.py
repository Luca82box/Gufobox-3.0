import socket
import eventlet
from zeroconf import ServiceInfo, Zeroconf
from core.utils import log

_zeroconf = None

def get_local_ip():
    """Trova l'indirizzo IP reale del Raspberry sulla rete WiFi"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)) # Simula una connessione esterna
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def init_mdns_discovery():
    global _zeroconf
    try:
        ip_addr = get_local_ip()
        
        # Le specifiche per Bonjour / Avahi (mDNS)
        info = ServiceInfo(
            "_http._tcp.local.",
            "GufoBox API._http._tcp.local.",
            addresses=[socket.inet_aton(ip_addr)],
            port=5000,
            properties={"version": "1.0", "type": "smart_speaker_kids"},
            server="gufobox.local."
        )

        _zeroconf = Zeroconf()
        _zeroconf.register_service(info)
        
        log(f"🌍 mDNS Discovery attivato! Raggiungibile su: http://gufobox.local:5000 (IP: {ip_addr})", "info")
        
    except Exception as e:
        log(f"Errore attivazione mDNS: {e}", "warning")

def cleanup_mdns():
    """Da chiamare quando il server si spegne per rimuovere l'annuncio dalla rete"""
    global _zeroconf
    if _zeroconf:
        _zeroconf.unregister_all_services()
        _zeroconf.close()

