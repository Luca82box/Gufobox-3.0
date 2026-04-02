#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 1. FONDAMENTALE: Patching per le performance (deve essere la prima riga!)
import eventlet
eventlet.monkey_patch()

from flask import Flask
from flask_cors import CORS

# Importiamo la configurazione e le utility
from config import SECRET_KEY, SESSION_COOKIE_SAMESITE, SESSION_COOKIE_SECURE, API_VERSION
from core.utils import log
from core.extensions import socketio

# Importiamo i gestori dello stato e i database
from core.state import build_public_snapshot, build_admin_snapshot
from core.database import init_db
from core.discovery import init_mdns_discovery, cleanup_mdns

# Importiamo i processi in background (Software)
from core.hardware import init_hardware_workers
from core.media import init_media_workers

# Importiamo i driver hardware fisici (GPIO, SPI, PWM, I2C)
from hw.buttons import init_buttons
from hw.rfid import init_rfid
from hw.led import init_leds
from hw.battery import init_battery

# Importiamo i Blueprint (Le nostre API modulari)
from api.system import system_bp
from api.media import media_bp
from api.files import files_bp
from api.ai import ai_bp
from api.network import network_bp
from api.settings import settings_bp
from api.voice import voice_bp  # <-- NUOVO: API per la registrazione vocale
from api.led import led_bp

def create_app():
    """Configura e assembla l'applicazione Flask principale"""
    app = Flask(__name__)
    
    # Sicurezza e Sessioni
    app.secret_key = SECRET_KEY
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = SESSION_COOKIE_SAMESITE
    app.config["SESSION_COOKIE_SECURE"] = SESSION_COOKIE_SECURE
    
    # Abilitiamo CORS per far comunicare il frontend Vue con il backend Python
    CORS(app, supports_credentials=True)

    # Registriamo tutte le rotte API
    log("Registrazione dei moduli API (Blueprints)...", "info")
    app.register_blueprint(system_bp, url_prefix='/api')
    app.register_blueprint(media_bp, url_prefix='/api')
    app.register_blueprint(files_bp, url_prefix='/api')
    app.register_blueprint(ai_bp, url_prefix='/api')
    app.register_blueprint(network_bp, url_prefix='/api')
    app.register_blueprint(settings_bp, url_prefix='/api')
    app.register_blueprint(voice_bp, url_prefix='/api') # <-- NUOVO: Registrato
    app.register_blueprint(led_bp, url_prefix='/api')

    # Colleghiamo Socket.io all'app Flask per le comunicazioni in tempo reale
    socketio.init_app(app, cors_allowed_origins="*", async_mode="eventlet", ping_interval=25, ping_timeout=20)

    return app

# Creazione dell'app
app = create_app()

# =========================================================
# EVENTI SOCKET.IO PRINCIPALI
# =========================================================
@socketio.on("connect")
def socket_connect():
    """Quando il frontend Vue o l'app mobile si connettono, mandiamo subito lo stato attuale"""
    socketio.emit("public_snapshot", build_public_snapshot())
    socketio.emit("admin_snapshot", build_admin_snapshot())
    log("Nuovo client connesso al WebSocket.", "info")

# =========================================================
# AVVIO DEL SERVER E DEI MOTORI HARDWARE
# =========================================================
if __name__ == "__main__":
    log(f"🚀 Avvio GufoBox API v{API_VERSION} (Modular Eventlet Mode)...", "info")
    
    try:
        # 1. Inizializza Database SQLite e Servizi di Rete (mDNS)
        log("Inizializzazione Database e Rete Locale...", "info")
        init_db()
        init_mdns_discovery()

        # 2. Avvia i processi software in background (Sleep Timer, Watchdog MPV, EventBus)
        log("Inizializzazione worker software (Media & System)...", "info")
        init_hardware_workers()
        init_media_workers()
        
        # 3. Avvia i driver fisici che leggono i Pin del Raspberry Pi
        log("Inizializzazione driver hardware fisici (Pulsanti, RFID, LED, Batteria)...", "info")
        init_buttons()
        init_rfid()
        init_leds()
        init_battery()  # <-- NUOVO: Controllo batteria I2C
        
        # 4. Avvia il server web in ascolto su tutte le interfacce (0.0.0.0) sulla porta 5000
        log("Server pronto! In attesa di connessioni...", "info")
        
        # Usiamo socketio.run invece di app.run per supportare i WebSocket con eventlet
        socketio.run(app, host="0.0.0.0", port=5000, debug=False)
        
    except KeyboardInterrupt:
        log("Spegnimento manuale rilevato. Chiusura servizi...", "warning")
    finally:
        # Pulisce l'annuncio mDNS quando spegni il server
        cleanup_mdns()
        log("GufoBox spenta correttamente.", "info")

