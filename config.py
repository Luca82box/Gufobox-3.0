import os

# =========================================================
# CONFIGURAZIONI GLOBALI E PERCORSI
# =========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Hotspot Wi-Fi
HOTSPOT_SSID = os.environ.get("GUFOBOX_HOTSPOT_SSID", "GUFOBOX")
HOTSPOT_PASS = os.environ.get("GUFOBOX_HOTSPOT_PASS", "gufobox123")
HOTSPOT_CONN_NAME = os.environ.get("GUFOBOX_HOTSPOT_CONN", "GUFOBOX-AP")

# Percorsi Media
MEDIA_ROOT = "/home/gufobox/media"
FIGURINE_IMAGES_ROOT = os.path.join(MEDIA_ROOT, "immagini_statuine")
CONTENT_ROOT = os.path.join(MEDIA_ROOT, "contenuti")

# File di Sistema e Cache
TMP_UPLOADS_ROOT = os.path.join(DATA_DIR, "tmp_uploads")
CHUNK_UPLOAD_ROOT = os.path.join(DATA_DIR, "chunk_uploads")
LED_EFFECTS_CUSTOM_DIR = os.path.join(DATA_DIR, "led_effects_custom")
AI_TTS_CACHE_DIR = os.path.join(DATA_DIR, "ai_tts_cache")
LOG_DIR = os.path.join(DATA_DIR, "logs")

# Assicuriamoci che le cartelle esistano
for p in [MEDIA_ROOT, FIGURINE_IMAGES_ROOT, CONTENT_ROOT, TMP_UPLOADS_ROOT,
          CHUNK_UPLOAD_ROOT, LED_EFFECTS_CUSTOM_DIR, AI_TTS_CACHE_DIR, LOG_DIR]:
    os.makedirs(p, exist_ok=True)

FILE_MANAGER_ROOTS = [
    "/home/gufobox",
    "/home/gufobox/media",
    "/mnt",
    "/media",
]
FILE_MANAGER_DEFAULT_PATH = "/home/gufobox/media"
for p in FILE_MANAGER_ROOTS:
    os.makedirs(p, exist_ok=True)

# Autenticazione & API Keys
SECRET_KEY = os.environ.get("GUFOBOX_SECRET_KEY", "change-me-in-production")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()

# Percorsi File JSON (Stato)
STATE_FILE = os.path.join(DATA_DIR, "state.json")
MEDIA_RUNTIME_FILE = os.path.join(DATA_DIR, "media_runtime.json")
LED_RUNTIME_FILE = os.path.join(DATA_DIR, "led_runtime.json")
AI_RUNTIME_FILE = os.path.join(DATA_DIR, "ai_runtime.json")
AI_SETTINGS_FILE = os.path.join(DATA_DIR, "ai_settings.json")
ALARMS_FILE = os.path.join(DATA_DIR, "alarms.json")
JOB_STATE_FILE = os.path.join(DATA_DIR, "jobs_state.json")
RFID_MAP_FILE = os.path.join(DATA_DIR, "rfid_map.json")
RFID_PROFILES_FILE = os.path.join(DATA_DIR, "rfid_profiles.json")
RSS_RUNTIME_FILE = os.path.join(DATA_DIR, "rss_runtime.json")

# Resume avanzato
RESUME_MAX_AGE_SEC = 30 * 24 * 3600  # 30 giorni

# Estensioni media supportate per playlist cartella
MEDIA_EXTENSIONS = {".mp3", ".ogg", ".flac", ".wav", ".m4a", ".aac", ".opus", ".mp4", ".mkv", ".avi"}

# Impostazioni Ottimizzazione
STATE_SAVE_DEBOUNCE_SEC = 2
API_VERSION = "18.1.0"

# OTA / Backup
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
OTA_LOG_FILE = os.path.join(DATA_DIR, "ota.log")
OTA_STATE_FILE = os.path.join(DATA_DIR, "ota_state.json")
OTA_STAGING_DIR = os.path.join(DATA_DIR, "ota_staging")
OTA_MAX_PACKAGE_BYTES = 100 * 1024 * 1024  # 100 MB
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(OTA_STAGING_DIR, exist_ok=True)

# Event log (operational ring buffer)
EVENT_LOG_FILE = os.path.join(LOG_DIR, "events.jsonl")

# LED Master
LED_MASTER_FILE = os.path.join(DATA_DIR, "led_master.json")


# Cookie Settings
SESSION_COOKIE_SECURE = os.environ.get("GUFOBOX_COOKIE_SECURE", "0") == "1"
SESSION_COOKIE_SAMESITE = os.environ.get("GUFOBOX_COOKIE_SAMESITE", "Lax")
