#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 1. FONDAMENTALE: Patching per le performance (deve essere la prima riga!)
import eventlet
eventlet.monkey_patch()

from flask import Flask, send_from_directory
from flask_cors import CORS
from werkzeug.utils import safe_join

# Importiamo la configurazione e le utility
from config import SECRET_KEY, SESSION_COOKIE_SAMESITE, SESSION_COOKIE_SECURE, API_VERSION, OTA_MAX_PACKAGE_BYTES, PIPER_MAX_UPLOAD_BYTES
from core.utils import log, request_shutdown
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
from api.auth import auth_bp
from api.jobs import jobs_bp
from api.diag import diag_bp
from api.rfid import rfid_bp
from api.rss import rss_bp
from api.audio import audio_bp
from api.wizard import wizard_bp
from api.tts import tts_bp

import os
import signal
import socket

# Percorso alla build del frontend Vue (generata da `npm run build`)
_FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")

def create_app():
    """Configura e assembla l'applicazione Flask principale"""
    app = Flask(__name__, static_folder=None)
    
    # Sicurezza e Sessioni
    app.secret_key = SECRET_KEY
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = SESSION_COOKIE_SAMESITE
    app.config["SESSION_COOKIE_SECURE"] = SESSION_COOKIE_SECURE
    app.config["MAX_CONTENT_LENGTH"] = max(OTA_MAX_PACKAGE_BYTES, PIPER_MAX_UPLOAD_BYTES)
    
    # Abilitiamo CORS per far comunicare il frontend Vue con il backend Python
    CORS(app, supports_credentials=True)

    # Registriamo tutte le rotte API
    log("Registrazione dei moduli API (Blueprints)...", "info")
    app.register_blueprint(system_bp, url_prefix='/api')
    # rfid_bp must be registered before media_bp: both define POST /rfid/trigger and
    # Flask uses the first match in the URL map.  rfid_bp carries the full profile
    # implementation (media_folder, webradio, ai_chat, rss_feed, edu_ai, web_media,
    # voice_recording) with automatic fallback to the legacy rfid_map; media_bp only
    # handles the legacy map and must not shadow the full implementation.
    app.register_blueprint(rfid_bp, url_prefix='/api')
    app.register_blueprint(media_bp, url_prefix='/api')
    app.register_blueprint(files_bp, url_prefix='/api')
    app.register_blueprint(ai_bp, url_prefix='/api')
    app.register_blueprint(network_bp, url_prefix='/api')
    app.register_blueprint(settings_bp, url_prefix='/api')
    app.register_blueprint(voice_bp, url_prefix='/api')
    app.register_blueprint(led_bp, url_prefix='/api')
    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(jobs_bp, url_prefix='/api')
    app.register_blueprint(diag_bp, url_prefix='/api')
    app.register_blueprint(rss_bp, url_prefix='/api')
    app.register_blueprint(audio_bp, url_prefix='/api')
    app.register_blueprint(wizard_bp, url_prefix='/api')
    app.register_blueprint(tts_bp, url_prefix='/api')

    # Servi i file statici del frontend Vue (build produzione)
    if os.path.isdir(_FRONTEND_DIST):
        log(f"Frontend Vue build trovata in {_FRONTEND_DIST} — verrà servita da Flask.", "info")

        @app.route("/", defaults={"path": ""})
        @app.route("/<path:path>")
        def serve_frontend(path):
            """Serve il frontend Vue buildato o l'index.html per SPA routing."""
            # Risorse statiche (js, css, img, ecc.) — serve il file direttamente
            # Usa safe_join per prevenire path traversal attacks
            if path:
                try:
                    safe_path = safe_join(_FRONTEND_DIST, path)
                except Exception:
                    safe_path = None
                if safe_path and os.path.isfile(safe_path):
                    return send_from_directory(_FRONTEND_DIST, path)
            # Catch-all per SPA: tutte le rotte non-API servono index.html
            return send_from_directory(_FRONTEND_DIST, "index.html")
    else:
        log(f"Frontend Vue build NON trovata in {_FRONTEND_DIST} — modalità API-only.", "warning")

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

    # Registra handler per SIGTERM (usato da systemd e Docker) e SIGINT (Ctrl+C)
    def _signal_handler(signum, frame):
        log(f"Segnale {signum} ricevuto — avvio shutdown ordinato.", "warning")
        request_shutdown()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

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

        # Notifica audio di benvenuto (best-effort: non blocca l'avvio)
        def _play_welcome():
            try:
                from hw.battery import play_ai_notification
                play_ai_notification(
                    "Uhuuu! Ciao amichetto! Il tuo gufetto si è svegliato "
                    "ed è pronto a giocare! Che bello vederti!"
                )
            except Exception as e:
                log(f"Notifica benvenuto non disponibile: {e}", "warning")
        eventlet.spawn(_play_welcome)

        # 4. Avvia il server web in ascolto su tutte le interfacce (0.0.0.0) sulla porta 5000
        log("Server pronto! In attesa di connessioni...", "info")

        # Controlla se la porta 5000 è già occupata prima di avviare il server
        _port = 5000
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _probe:
            if _probe.connect_ex(("127.0.0.1", _port)) == 0:
                log(
                    f"❌ ERRORE: La porta {_port} è già in uso! "
                    f"Per liberarla esegui: sudo fuser -k {_port}/tcp "
                    f"oppure: sudo lsof -ti :{_port} | xargs kill",
                    "error",
                )
                try:
                    import subprocess
                    result = subprocess.run(
                        ["fuser", f"{_port}/tcp"],
                        capture_output=True, text=True, timeout=3
                    )
                    pids = result.stdout.strip()
                    if pids:
                        log(f"PID che occupa la porta {_port}: {pids}", "error")
                except Exception:
                    pass
                raise OSError(f"[Errno 98] Address already in use: porta {_port} occupata")

        # Usiamo socketio.run invece di app.run per supportare i WebSocket con eventlet
        socketio.run(app, host="0.0.0.0", port=_port, debug=False)
        
    except KeyboardInterrupt:
        log("Spegnimento manuale rilevato. Chiusura servizi...", "warning")
        request_shutdown()
    finally:
        # Notifica audio di spegnimento (best-effort)
        try:
            from hw.battery import play_ai_notification
            play_ai_notification(
                "Zzz... Il gufetto va a fare la nanna! A presto amichetto! Sogni d'oro!"
            )
            eventlet.sleep(3)  # Piccola attesa per far finire la notifica
        except Exception:
            pass
        # Segnala a tutti i worker di terminare e dai loro un momento per farlo
        request_shutdown()
        log("Attendo la terminazione dei worker...", "info")
        eventlet.sleep(1)
        # Pulisce l'annuncio mDNS quando spegni il server
        cleanup_mdns()
        log("GufoBox spenta correttamente.", "info")

