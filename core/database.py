import sqlite3
import os
import time
import threading
from datetime import datetime
from config import DATA_DIR, RESUME_MAX_AGE_SEC
from core.utils import log

DB_PATH = os.path.join(DATA_DIR, "gufobox.db")

# Thread-local storage per il riuso della connessione SQLite
_tls = threading.local()


def _get_conn():
    """
    Ritorna la connessione SQLite per il thread corrente, creandola se necessario.
    La connessione viene riutilizzata ad ogni chiamata successiva dello stesso thread.
    La prima chiamata abilita anche WAL per migliori performance concorrenti.
    Se DB_PATH è cambiato (es. in test), la vecchia connessione viene chiusa e ricreata.
    """
    conn = getattr(_tls, "conn", None)
    cached_path = getattr(_tls, "db_path", None)
    if conn is None or cached_path != DB_PATH:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _tls.conn = conn
        _tls.db_path = DB_PATH
    return conn


def close_db():
    """Chiude la connessione SQLite del thread corrente (opzionale, usato allo shutdown)."""
    conn = getattr(_tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _tls.conn = None

def init_db():
    """Inizializza le tabelle del database se non esistono"""
    try:
        with _get_conn() as conn:
            # Tabella per le statistiche di ascolto (#11)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS listening_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT,
                    rfid_uid TEXT,
                    duration_seconds INTEGER,
                    hour INTEGER
                )
            ''')
            # Migrazione per database esistenti (prima dell'aggiunta della colonna hour):
            # fresh installs già avranno la colonna dal CREATE TABLE sopra,
            # quindi il "duplicate column" viene ignorato (identico pattern di playlist_index)
            try:
                conn.execute("ALTER TABLE listening_stats ADD COLUMN hour INTEGER")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
            # Tabella per il Resume Intelligente degli Audiolibri (#8) — versione avanzata
            conn.execute('''
                CREATE TABLE IF NOT EXISTS smart_resume (
                    rfid_uid TEXT PRIMARY KEY,
                    target_path TEXT,
                    position_seconds INTEGER,
                    playlist_index INTEGER DEFAULT 0,
                    last_played_ts INTEGER
                )
            ''')
            # Aggiunge la colonna playlist_index se non esiste (migrazione da versione precedente)
            try:
                conn.execute("ALTER TABLE smart_resume ADD COLUMN playlist_index INTEGER DEFAULT 0")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise
            # Tabella storico batteria per il grafico nel tempo
            conn.execute('''
                CREATE TABLE IF NOT EXISTS battery_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER,
                    percent REAL,
                    voltage REAL,
                    charging INTEGER
                )
            ''')
        log("Database SQLite (Statistiche, Resume e Batteria) inizializzato.", "info")
    except Exception as e:
        log(f"Errore inizializzazione DB: {e}", "error")

# --- FUNZIONI STATISTICHE (#11) ---
def log_listening_session(rfid_uid, duration_seconds):
    """Salva una sessione di ascolto conclusa"""
    if duration_seconds < 10: return # Ignora ascolti troppo brevi

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    hour = now.hour
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO listening_stats (date, rfid_uid, duration_seconds, hour) VALUES (?, ?, ?, ?)",
                (today, rfid_uid, duration_seconds, hour)
            )
    except Exception as e:
        log(f"Errore salvataggio stat: {e}", "warning")

def get_daily_stats():
    """Recupera i minuti totali ascoltati per ogni giorno (per il grafico frontend)"""
    try:
        with _get_conn() as conn:
            cursor = conn.execute('''
                SELECT date, SUM(duration_seconds) as total_sec 
                FROM listening_stats 
                GROUP BY date 
                ORDER BY date DESC LIMIT 7
            ''')
            return [{"date": row["date"], "minutes": round(row["total_sec"]/60)} for row in cursor]
    except Exception as e:
        log(f"Errore nel recupero statistiche settimanali: {e}", "warning")
        return []

def get_top_figurines(n=5):
    """Recupera le statuine più usate per tempo di ascolto (top N)"""
    try:
        with _get_conn() as conn:
            cursor = conn.execute('''
                SELECT rfid_uid, SUM(duration_seconds) as total_sec, COUNT(*) as sessions
                FROM listening_stats
                WHERE rfid_uid IS NOT NULL AND rfid_uid != ''
                GROUP BY rfid_uid
                ORDER BY total_sec DESC
                LIMIT ?
            ''', (n,))
            return [
                {
                    "rfid_uid": row["rfid_uid"],
                    "minutes": round(row["total_sec"] / 60),
                    "sessions": row["sessions"],
                }
                for row in cursor
            ]
    except Exception as e:
        log(f"Errore nel recupero statuine top: {e}", "warning")
        return []

def get_hourly_stats():
    """Recupera i minuti totali ascoltati per fascia oraria (0-23)"""
    try:
        with _get_conn() as conn:
            cursor = conn.execute('''
                SELECT hour, SUM(duration_seconds) as total_sec
                FROM listening_stats
                WHERE hour IS NOT NULL
                GROUP BY hour
                ORDER BY hour ASC
            ''')
            # Inizializza tutte le 24 ore a 0
            result = {h: 0 for h in range(24)}
            for row in cursor:
                result[row["hour"]] = round(row["total_sec"] / 60)
            return [{"hour": h, "minutes": result[h]} for h in range(24)]
    except Exception as e:
        log(f"Errore nel recupero statistiche orarie: {e}", "warning")
        return [{"hour": h, "minutes": 0} for h in range(24)]

# --- FUNZIONI STORICO BATTERIA ---
def log_battery_reading(percent, voltage, charging):
    """Salva una lettura della batteria nel database (chiamata ogni minuto dal watchdog)"""
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO battery_history (ts, percent, voltage, charging) VALUES (?, ?, ?, ?)",
                (int(time.time()), percent, voltage, 1 if charging else 0)
            )
            # Mantieni solo le ultime 48 ore di dati (ogni minuto = max 2880 righe)
            cutoff = int(time.time()) - 48 * 3600
            conn.execute("DELETE FROM battery_history WHERE ts < ?", (cutoff,))
    except Exception as e:
        log(f"Errore salvataggio storico batteria: {e}", "warning")

def get_battery_history(hours=24):
    """Recupera lo storico batteria delle ultime N ore (campionato ogni ~5 minuti)"""
    try:
        cutoff = int(time.time()) - hours * 3600
        with _get_conn() as conn:
            cursor = conn.execute('''
                SELECT ts, percent, voltage, charging
                FROM battery_history
                WHERE ts >= ?
                ORDER BY ts ASC
            ''', (cutoff,))
            rows = cursor.fetchall()
            # Campionamento: restituisce al massimo 300 punti (circa ogni 5 min su 24h)
            if len(rows) > 300:
                step = len(rows) // 300
                rows = rows[::step]
            return [
                {
                    "ts": row["ts"],
                    "percent": row["percent"],
                    "voltage": row["voltage"],
                    "charging": bool(row["charging"]),
                }
                for row in rows
            ]
    except Exception as e:
        log(f"Errore nel recupero storico batteria: {e}", "warning")
        return []

def get_all_stats_for_export():
    """Recupera tutte le statistiche di ascolto per l'export (CSV/JSON)"""
    try:
        with _get_conn() as conn:
            cursor = conn.execute('''
                SELECT date, hour, rfid_uid, duration_seconds
                FROM listening_stats
                ORDER BY date DESC, hour ASC
            ''')
            return [
                {
                    "date": row["date"],
                    "hour": row["hour"],
                    "rfid_uid": row["rfid_uid"],
                    "duration_seconds": row["duration_seconds"],
                }
                for row in cursor
            ]
    except Exception as e:
        log(f"Errore nell'export statistiche: {e}", "warning")
        return []

# --- FUNZIONI SMART RESUME (#8) — avanzato ---
def save_resume_position(rfid_uid, target_path, position_sec, playlist_index=0):
    """Salva a che punto è arrivato il bambino in una storia (incluso indice playlist)"""
    try:
        with _get_conn() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO smart_resume
                    (rfid_uid, target_path, position_seconds, playlist_index, last_played_ts)
                VALUES (?, ?, ?, ?, ?)
            ''', (rfid_uid, target_path, position_sec, playlist_index, int(time.time())))
    except Exception as e:
        log(f"Errore salvataggio resume: {e}", "warning")

def clear_resume_position(rfid_uid):
    """
    Azzera la posizione di resume per una statuina quando il file è finito naturalmente.
    Evita di ripartire dalla fine alla prossima riproduzione.
    """
    try:
        with _get_conn() as conn:
            conn.execute("DELETE FROM smart_resume WHERE rfid_uid = ?", (rfid_uid,))
    except Exception as e:
        log(f"Errore cancellazione resume: {e}", "warning")

def get_resume_position(rfid_uid):
    """Recupera il secondo esatto da cui ripartire per una specifica statuina"""
    try:
        cutoff = int(time.time()) - RESUME_MAX_AGE_SEC
        with _get_conn() as conn:
            cursor = conn.execute(
                "SELECT target_path, position_seconds, playlist_index, last_played_ts "
                "FROM smart_resume WHERE rfid_uid = ? AND last_played_ts > ?",
                (rfid_uid, cutoff)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "target": row["target_path"],
                    "position": row["position_seconds"],
                    "playlist_index": row["playlist_index"] or 0,
                    "last_played_ts": row["last_played_ts"],
                }
    except Exception as e:
        log(f"Errore nel recupero posizione smart resume: {e}", "warning")
    return None

def cleanup_expired_resumes():
    """Rimuove i resume scaduti (più vecchi di RESUME_MAX_AGE_SEC)"""
    try:
        cutoff = int(time.time()) - RESUME_MAX_AGE_SEC
        with _get_conn() as conn:
            conn.execute("DELETE FROM smart_resume WHERE last_played_ts < ?", (cutoff,))
        log("Resume scaduti rimossi dal database.", "info")
    except Exception as e:
        log(f"Errore pulizia resume scaduti: {e}", "warning")

