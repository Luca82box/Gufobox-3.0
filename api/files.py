"""
api/files.py — File manager API (PR 17: premium polish).

Endpoints:
  GET  /files/default-root              — radici consentite e cartella default
  GET  /files/list                      — elenca file/cartelle con mtime, sort, filter
  GET  /files/open                      — lettura sicura file binario
  POST /files/mkdir                     — crea cartella
  POST /files/delete                    — elimina (multi-path, partial success)
  POST /files/rename                    — rinomina
  POST /files/copy                      — copia (job-based)
  POST /files/move                      — sposta (job-based)
  POST /files/compress                  — comprimi in zip (job-based)
  POST /files/uncompress                — decomprimi zip (job-based)
  POST /files/details                   — metadati file
  POST /files/upload/init               — inizia upload a chunk
  POST /files/upload/chunk              — carica chunk
  POST /files/upload/finalize           — finalizza upload
"""

import os
import shutil
import mimetypes
import time as _time
import zipfile
import threading
from flask import Blueprint, request, jsonify, send_file
from werkzeug.utils import secure_filename

import config as _cfg
from core.utils import secure_open_read, log
from core.state import bus
from core.jobs import create_job, update_job, finish_job
from core.event_log import log_event

files_bp = Blueprint('files', __name__)

# =========================================================
# HELPER: sicurezza path
# =========================================================

def _resolve_safe(path: str):
    """
    Risolve il path e verifica che sia dentro _cfg.FILE_MANAGER_ROOTS.
    Ritorna il path reale o None se non autorizzato.

    Usa `+ os.sep` nel confronto per prevenire path traversal in cui un
    prefisso comune non coincide con il separatore di directory, ad es.
    /home/gufoboxbad sarebbe accettato se la radice è /home/gufobox senza il sep.
    """
    real = os.path.realpath(path)
    for r in _cfg.FILE_MANAGER_ROOTS:
        r_real = os.path.realpath(r)
        if real == r_real or real.startswith(r_real + os.sep):
            return real
    return None


def _safe_paths(paths: list) -> list:
    """Filtra una lista di path lasciando solo quelli autorizzati."""
    result = []
    for p in paths:
        r = _resolve_safe(p)
        if r is not None:
            result.append(r)
    return result


def _file_type(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        return "unknown"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "image"
    if mime in ("application/zip", "application/x-tar", "application/gzip",
                "application/x-bzip2", "application/x-7z-compressed"):
        return "archive"
    if mime.startswith("text/"):
        return "text"
    return "unknown"


def _entry_dict(full_path: str) -> dict:
    """Crea il dict di un singolo entry file/cartella."""
    is_dir = os.path.isdir(full_path)
    stat = os.stat(full_path)
    return {
        "name": os.path.basename(full_path),
        "path": full_path,
        "is_dir": is_dir,
        "size": stat.st_size if not is_dir else 0,
        "mtime": int(stat.st_mtime),
        "type": "dir" if is_dir else _file_type(full_path),
    }


# =========================================================
# NAVIGAZIONE CARTELLE
# =========================================================

@files_bp.route("/files/default-root", methods=["GET"])
def api_files_default_root():
    """Restituisce la cartella di partenza e le radici consentite."""
    return jsonify({
        "default_path": _cfg.FILE_MANAGER_DEFAULT_PATH,
        "allowed_roots": _cfg.FILE_MANAGER_ROOTS
    })


@files_bp.route("/files/list", methods=["GET"])
def api_files_list():
    """Elenca file e cartelle in modo sicuro. Supporta sort e filtro tipo."""
    req_path = request.args.get("path", "").strip() or _cfg.FILE_MANAGER_DEFAULT_PATH
    sort_by = request.args.get("sort", "name")       # name | size | mtime | type
    sort_dir = request.args.get("order", "asc")      # asc | desc
    filter_type = request.args.get("filter_type", "") # "" | audio | video | image | dir | archive | text

    real_path = os.path.realpath(req_path)
    allowed = any(
        real_path == os.path.realpath(r) or real_path.startswith(os.path.realpath(r) + os.sep)
        for r in _cfg.FILE_MANAGER_ROOTS
    )
    if not allowed:
        return jsonify({"error": "Access Denied"}), 403

    if not os.path.isdir(real_path):
        return jsonify({"error": "Cartella non trovata"}), 404

    entries = []
    try:
        for item in os.listdir(real_path):
            full_path = os.path.join(real_path, item)
            try:
                entries.append(_entry_dict(full_path))
            except OSError:
                pass  # skip inaccessible files

    except Exception as e:
        log(f"Errore lettura cartella {real_path}: {e}", "error")
        return jsonify({"error": "Impossibile leggere la cartella"}), 500

    # Filtro tipo
    if filter_type:
        if filter_type == "dir":
            entries = [e for e in entries if e["is_dir"]]
        else:
            entries = [e for e in entries if e["type"] == filter_type]

    # Ordinamento: cartelle sempre in cima, poi sort sul campo richiesto
    reverse = sort_dir == "desc"
    sort_keys = {
        "name":  lambda e: e["name"].lower(),
        "size":  lambda e: e["size"],
        "mtime": lambda e: e["mtime"],
        "type":  lambda e: (e["type"], e["name"].lower()),
    }
    key_fn = sort_keys.get(sort_by, sort_keys["name"])
    dirs = sorted([e for e in entries if e["is_dir"]], key=key_fn, reverse=reverse)
    files = sorted([e for e in entries if not e["is_dir"]], key=key_fn, reverse=reverse)
    entries = dirs + files

    return jsonify({
        "current_path": real_path,
        "entries": entries,
        "default_path": _cfg.FILE_MANAGER_DEFAULT_PATH,
        "allowed_roots": _cfg.FILE_MANAGER_ROOTS,
        "total": len(entries),
    })


# =========================================================
# LETTURA FILE (sicurezza TOCTOU)
# =========================================================

@files_bp.route("/files/open", methods=["GET"])
def api_files_open():
    """Restituisce un file binario usando file descriptor sicuro (O_NOFOLLOW)."""
    path = request.args.get("path", "").strip()
    if not path:
        return jsonify({"error": "Percorso mancante"}), 400

    try:
        fd = secure_open_read(path, _cfg.FILE_MANAGER_ROOTS)
        mime, _ = mimetypes.guess_type(path)
        return send_file(fd, mimetype=mime or "application/octet-stream")
    except ValueError as e:
        log(f"Tentativo di accesso illegale bloccato: {path}", "warning")
        return jsonify({"error": str(e)}), 403
    except FileNotFoundError:
        return jsonify({"error": "File non trovato"}), 404
    except Exception as e:
        return jsonify({"error": f"Errore apertura: {str(e)}"}), 500


# =========================================================
# OPERAZIONI DI BASE
# =========================================================

@files_bp.route("/files/mkdir", methods=["POST"])
def api_files_mkdir():
    """Crea una nuova cartella."""
    data = request.get_json(silent=True) or {}
    parent = data.get("path", "").strip()
    name = data.get("name", "").strip()

    if not parent or not name:
        return jsonify({"error": "Dati mancanti (path e name richiesti)"}), 400

    name = secure_filename(name)
    if not name:
        return jsonify({"error": "Nome cartella non valido"}), 400

    new_dir = _resolve_safe(os.path.join(parent, name))
    if new_dir is None:
        return jsonify({"error": "Access Denied"}), 403

    try:
        os.makedirs(new_dir, exist_ok=True)
        log(f"Creata cartella: {new_dir}", "info")
        return jsonify({"status": "ok", "path": new_dir})
    except Exception as e:
        log(f"mkdir fallito {new_dir}: {e}", "error")
        return jsonify({"error": "Impossibile creare la cartella"}), 500


@files_bp.route("/files/delete", methods=["POST"])
def api_files_delete():
    """Elimina uno o più file/cartelle con partial-success."""
    data = request.get_json(silent=True) or {}
    paths = data.get("paths", [])

    if not isinstance(paths, list) or not paths:
        return jsonify({"error": "paths deve essere una lista non vuota"}), 400

    deleted = []
    errors = []
    for p in paths:
        real = _resolve_safe(p)
        if real is None:
            errors.append({"path": p, "error": "Access Denied"})
            continue
        try:
            if os.path.isdir(real):
                shutil.rmtree(real)
            elif os.path.exists(real):
                os.remove(real)
            else:
                errors.append({"path": p, "error": "File non trovato"})
                continue
            deleted.append(real)
        except Exception as e:
            log(f"Errore delete {real}: {e}", "warning")
            errors.append({"path": p, "error": "Errore durante l'eliminazione"})
            log_event("files", "error", f"Delete fallito: {os.path.basename(real)}", {"path": real, "err": str(e)})

    bus.emit_notification(f"Eliminati {len(deleted)} elementi", "info")
    return jsonify({
        "status": "ok" if not errors else "partial",
        "deleted": len(deleted),
        "errors": errors,
    })


@files_bp.route("/files/rename", methods=["POST"])
def api_files_rename():
    """Rinomina un file o una cartella."""
    data = request.get_json(silent=True) or {}
    path = data.get("path", "").strip()
    new_name = data.get("new_name", "").strip()

    if not path or not new_name:
        return jsonify({"error": "path e new_name richiesti"}), 400

    real_src = _resolve_safe(path)
    if real_src is None:
        return jsonify({"error": "Access Denied"}), 403
    if not os.path.exists(real_src):
        return jsonify({"error": "File non trovato"}), 404

    safe_name = secure_filename(new_name)
    if not safe_name:
        return jsonify({"error": "Nome non valido"}), 400

    real_dst = _resolve_safe(os.path.join(os.path.dirname(real_src), safe_name))
    if real_dst is None:
        return jsonify({"error": "Access Denied sulla destinazione"}), 403

    if os.path.exists(real_dst):
        return jsonify({"error": "Esiste già un elemento con questo nome"}), 409

    try:
        os.rename(real_src, real_dst)
        log(f"Rinominato {real_src} -> {real_dst}", "info")
        return jsonify({"status": "ok", "new_path": real_dst})
    except Exception as e:
        log(f"Rename fallito {real_src}: {e}", "error")
        log_event("files", "error", f"Rename fallito: {os.path.basename(real_src)}", {"err": str(e)})
        return jsonify({"error": "Impossibile rinominare il file"}), 500


# =========================================================
# OPERAZIONI JOB-BASED (copy, move, compress, uncompress)
# =========================================================

def _run_copy(job_id: str, sources: list, destination: str):
    """Worker thread: copia ogni source nella destination."""
    total = len(sources)
    done = 0
    errors = []
    for src in sources:
        if not os.path.exists(src):
            errors.append({"path": src, "error": "Non trovato"})
            continue
        dst_name = os.path.basename(src)
        real_dst = os.path.join(destination, dst_name)
        if os.path.exists(real_dst):
            base, ext = os.path.splitext(dst_name)
            real_dst = os.path.join(destination, f"{base}_copy{ext}")
        try:
            if os.path.isdir(src):
                shutil.copytree(src, real_dst)
            else:
                shutil.copy2(src, real_dst)
            done += 1
            update_job(job_id,
                       status="running",
                       items_done=done,
                       progress_percent=int(done / total * 100),
                       current_item=dst_name)
        except Exception as e:
            errors.append({"path": src, "error": str(e)})
            log_event("files", "error", f"Copy fallita: {dst_name}", {"err": str(e)})

    msg = f"Copiati {done}/{total}"
    if errors:
        msg += f" ({len(errors)} errori)"
    status = "error" if done == 0 and errors else "done"
    finish_job(job_id, status=status, message=msg,
               error=errors[0]["error"] if done == 0 and errors else None)


def _run_move(job_id: str, sources: list, destination: str):
    """Worker thread: sposta ogni source nella destination."""
    total = len(sources)
    done = 0
    errors = []
    for src in sources:
        if not os.path.exists(src):
            errors.append({"path": src, "error": "Non trovato"})
            continue
        dst_name = os.path.basename(src)
        real_dst = os.path.join(destination, dst_name)
        if os.path.exists(real_dst):
            base, ext = os.path.splitext(dst_name)
            real_dst = os.path.join(destination, f"{base}_moved{ext}")
        try:
            shutil.move(src, real_dst)
            done += 1
            update_job(job_id,
                       status="running",
                       items_done=done,
                       progress_percent=int(done / total * 100),
                       current_item=dst_name)
        except Exception as e:
            errors.append({"path": src, "error": str(e)})
            log_event("files", "error", f"Move fallita: {dst_name}", {"err": str(e)})

    msg = f"Spostati {done}/{total}"
    if errors:
        msg += f" ({len(errors)} errori)"
    status = "error" if done == 0 and errors else "done"
    finish_job(job_id, status=status, message=msg,
               error=errors[0]["error"] if done == 0 and errors else None)


def _run_compress(job_id: str, sources: list, destination: str, archive_name: str):
    """Worker thread: comprimi sources in un archivio zip."""
    if not archive_name.endswith(".zip"):
        archive_name += ".zip"
    archive_path = os.path.join(destination, archive_name)

    update_job(job_id, status="running", message="Creazione archivio...")
    total = len(sources)
    added = 0
    errors = []
    try:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for src in sources:
                if not os.path.exists(src):
                    errors.append({"path": src, "error": "Non trovato"})
                    continue
                try:
                    if os.path.isdir(src):
                        for root, _, files_in_dir in os.walk(src):
                            for fname in files_in_dir:
                                fpath = os.path.join(root, fname)
                                arcname = os.path.relpath(fpath, os.path.dirname(src))
                                zf.write(fpath, arcname)
                    else:
                        zf.write(src, os.path.basename(src))
                    added += 1
                    update_job(job_id, items_done=added,
                               progress_percent=int(added / total * 100),
                               current_item=os.path.basename(src))
                except Exception as e:
                    errors.append({"path": src, "error": str(e)})
                    log_event("files", "error", f"Compress fallita su {os.path.basename(src)}", {"err": str(e)})
    except Exception as e:
        log_event("files", "error", f"Compress fallita: {archive_name}", {"err": str(e)})
        finish_job(job_id, status="error", error=str(e))
        return

    msg = f"Compressi {added}/{total} in {archive_name}"
    if errors:
        msg += f" ({len(errors)} errori)"
    finish_job(job_id, status="done", message=msg)


def _run_uncompress(job_id: str, archive_path: str, destination: str):
    """Worker thread: decomprime un archivio zip nella destination."""
    update_job(job_id, status="running", message="Decompressione in corso...")
    try:
        real_dest = os.path.realpath(destination)
        with zipfile.ZipFile(archive_path, "r") as zf:
            # Sicurezza: controlla path traversal nei membri.
            # Il confronto include + os.sep per evitare che un nome come
            # "destination_evil/file" passi per via del prefisso comune.
            for member in zf.namelist():
                member_path = os.path.realpath(os.path.join(destination, member))
                if not (member_path == real_dest or
                        member_path.startswith(real_dest + os.sep)):
                    finish_job(job_id, status="error",
                               error=f"Path traversal nel membro: {member}")
                    log_event("files", "error", "Uncompress rifiutata: path traversal",
                              {"archive": archive_path})
                    return
            total = len(zf.namelist())
            zf.extractall(destination)
        finish_job(job_id, status="done",
                   message=f"Estratti {total} elementi in {os.path.basename(destination)}")
    except zipfile.BadZipFile as e:
        log_event("files", "error", "Uncompress fallita: archivio corrotto",
                  {"archive": archive_path})
        finish_job(job_id, status="error", error=f"Archivio non valido: {e}")
    except Exception as e:
        log_event("files", "error", "Uncompress fallita",
                  {"archive": archive_path, "err": str(e)})
        finish_job(job_id, status="error", error=str(e))


@files_bp.route("/files/copy", methods=["POST"])
def api_files_copy():
    """Copia file/cartelle nella destination (job-based)."""
    data = request.get_json(silent=True) or {}
    sources = data.get("sources", [])
    destination = data.get("destination", "").strip()

    if not sources or not destination:
        return jsonify({"error": "sources e destination richiesti"}), 400

    real_dst = _resolve_safe(destination)
    if real_dst is None or not os.path.isdir(real_dst):
        return jsonify({"error": "Destinazione non valida"}), 400

    safe_srcs = _safe_paths(sources)
    if not safe_srcs:
        return jsonify({"error": "Nessun source valido"}), 400

    job = create_job("file_copy",
                     f"Copia {len(safe_srcs)} elementi in {os.path.basename(real_dst)}",
                     items_total=len(safe_srcs))
    threading.Thread(target=_run_copy, args=(job["job_id"], safe_srcs, real_dst),
                     daemon=True).start()
    return jsonify({"status": "ok", "job": job})


@files_bp.route("/files/move", methods=["POST"])
def api_files_move():
    """Sposta file/cartelle nella destination (job-based)."""
    data = request.get_json(silent=True) or {}
    sources = data.get("sources", [])
    destination = data.get("destination", "").strip()

    if not sources or not destination:
        return jsonify({"error": "sources e destination richiesti"}), 400

    real_dst = _resolve_safe(destination)
    if real_dst is None or not os.path.isdir(real_dst):
        return jsonify({"error": "Destinazione non valida"}), 400

    safe_srcs = _safe_paths(sources)
    if not safe_srcs:
        return jsonify({"error": "Nessun source valido"}), 400

    job = create_job("file_move",
                     f"Sposta {len(safe_srcs)} elementi in {os.path.basename(real_dst)}",
                     items_total=len(safe_srcs))
    threading.Thread(target=_run_move, args=(job["job_id"], safe_srcs, real_dst),
                     daemon=True).start()
    return jsonify({"status": "ok", "job": job})


@files_bp.route("/files/compress", methods=["POST"])
def api_files_compress():
    """Comprimi file/cartelle selezionati in un archivio zip (job-based)."""
    data = request.get_json(silent=True) or {}
    sources = data.get("paths", data.get("sources", []))
    destination = data.get("destination", "").strip()
    archive_name = data.get("archive_name", "archivio").strip() or "archivio"

    if not sources or not destination:
        return jsonify({"error": "paths/sources e destination richiesti"}), 400

    real_dst = _resolve_safe(destination)
    if real_dst is None or not os.path.isdir(real_dst):
        return jsonify({"error": "Destinazione non valida"}), 400

    safe_srcs = _safe_paths(sources)
    if not safe_srcs:
        return jsonify({"error": "Nessun source valido"}), 400

    # Sicurezza: archive_name non può contenere path separators
    archive_name = os.path.basename(archive_name) or "archivio"

    job = create_job("file_compress",
                     f"Comprimi {len(safe_srcs)} elementi in {archive_name}.zip",
                     items_total=len(safe_srcs))
    threading.Thread(target=_run_compress,
                     args=(job["job_id"], safe_srcs, real_dst, archive_name),
                     daemon=True).start()
    return jsonify({"status": "ok", "job": job})


@files_bp.route("/files/uncompress", methods=["POST"])
def api_files_uncompress():
    """Decomprime un archivio zip (job-based)."""
    data = request.get_json(silent=True) or {}
    archive = data.get("path", "").strip()
    destination = data.get("destination", "").strip()

    if not archive or not destination:
        return jsonify({"error": "path e destination richiesti"}), 400

    real_archive = _resolve_safe(archive)
    if real_archive is None or not os.path.isfile(real_archive):
        return jsonify({"error": "Archivio non trovato o non consentito"}), 400

    real_dst = _resolve_safe(destination)
    if real_dst is None or not os.path.isdir(real_dst):
        return jsonify({"error": "Destinazione non valida"}), 400

    job = create_job("file_uncompress",
                     f"Decomprimi {os.path.basename(real_archive)}",
                     items_total=1)
    threading.Thread(target=_run_uncompress,
                     args=(job["job_id"], real_archive, real_dst),
                     daemon=True).start()
    return jsonify({"status": "ok", "job": job})


# =========================================================
# DETTAGLI FILE
# =========================================================

@files_bp.route("/files/details", methods=["POST"])
def api_files_details():
    """Ritorna metadati dettagliati di un file/cartella."""
    data = request.get_json(silent=True) or {}
    path = data.get("path", "").strip()

    if not path:
        return jsonify({"error": "path richiesto"}), 400

    real = _resolve_safe(path)
    if real is None:
        return jsonify({"error": "Access Denied"}), 403
    if not os.path.exists(real):
        return jsonify({"error": "File non trovato"}), 404

    try:
        stat = os.stat(real)
        is_dir = os.path.isdir(real)
        result = {
            "name": os.path.basename(real),
            "path": real,
            "is_dir": is_dir,
            "size": stat.st_size if not is_dir else 0,
            "mtime": int(stat.st_mtime),
            "type": "dir" if is_dir else _file_type(real),
            "mime": mimetypes.guess_type(real)[0] if not is_dir else None,
            "readable": os.access(real, os.R_OK),
            "writable": os.access(real, os.W_OK),
        }
        if is_dir:
            try:
                result["children_count"] = len(os.listdir(real))
            except Exception:
                result["children_count"] = None
        return jsonify(result)
    except Exception as e:
        log(f"Errore dettagli {real}: {e}", "error")
        return jsonify({"error": "Impossibile leggere i dettagli del file"}), 500


# =========================================================
# UPLOAD A CHUNK
# =========================================================

_upload_sessions: dict = {}
_upload_lock = threading.Lock()
_UPLOAD_SESSION_MAX_AGE_SEC = 3600  # 1 ora — sessioni abbandonate


def _cleanup_stale_upload_sessions():
    """Rimuove sessioni di upload abbandonate (più vecchie di _UPLOAD_SESSION_MAX_AGE_SEC)."""
    now = _time.time()
    with _upload_lock:
        stale = [
            sid for sid, sess in _upload_sessions.items()
            if now - sess.get("created_ts", now) > _UPLOAD_SESSION_MAX_AGE_SEC
        ]
        for sid in stale:
            sess = _upload_sessions.pop(sid)
            try:
                tmp = sess.get("tmp_path", "")
                if tmp and os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
    if stale:
        log(f"Upload sessions cleanup: rimosse {len(stale)} sessioni abbandonate", "info")


@files_bp.route("/files/upload/init", methods=["POST"])
def api_files_upload_init():
    """Inizia una sessione di upload a chunk."""
    data = request.get_json(silent=True) or {}
    filename = data.get("filename", "").strip()
    total_size = data.get("total_size", 0)
    dest_path = data.get("path", _cfg.FILE_MANAGER_DEFAULT_PATH).strip()
    chunk_size = int(data.get("chunk_size", 8 * 1024 * 1024))

    if not filename:
        return jsonify({"error": "filename richiesto"}), 400

    safe_name = secure_filename(filename)
    if not safe_name:
        return jsonify({"error": "Nome file non valido"}), 400

    real_dst = _resolve_safe(dest_path)
    if real_dst is None or not os.path.isdir(real_dst):
        return jsonify({"error": "Cartella destinazione non valida"}), 400

    import uuid
    session_id = str(uuid.uuid4())
    tmp_path = os.path.join(_cfg.CHUNK_UPLOAD_ROOT, session_id + ".tmp")

    with _upload_lock:
        _upload_sessions[session_id] = {
            "filename": safe_name,
            "destination": real_dst,
            "total_size": int(total_size),
            "received": 0,
            "tmp_path": tmp_path,
            "created_ts": _time.time(),
        }
    # Cleanup delle sessioni abbandonate (best-effort, non blocca la risposta)
    try:
        import eventlet as _ev
        _ev.spawn(_cleanup_stale_upload_sessions)
    except Exception:
        pass

    open(tmp_path, "wb").close()

    return jsonify({
        "session_id": session_id,
        "chunk_size": chunk_size,
        "filename": safe_name,
    })


@files_bp.route("/files/upload/chunk", methods=["POST"])
def api_files_upload_chunk():
    """Riceve un chunk di upload."""
    session_id = request.form.get("session_id", "")
    offset = int(request.form.get("offset", 0))
    chunk_file = request.files.get("chunk")

    if not session_id or chunk_file is None:
        return jsonify({"error": "session_id e chunk richiesti"}), 400

    with _upload_lock:
        session = _upload_sessions.get(session_id)

    if session is None:
        return jsonify({"error": "Sessione non trovata"}), 404

    try:
        chunk_data = chunk_file.read()
        with open(session["tmp_path"], "r+b") as f:
            f.seek(offset)
            f.write(chunk_data)
        with _upload_lock:
            _upload_sessions[session_id]["received"] = offset + len(chunk_data)

        return jsonify({
            "status": "ok",
            "received": offset + len(chunk_data),
            "total_size": session["total_size"],
        })
    except Exception as e:
        log(f"Errore chunk upload {session_id}: {e}", "error")
        log_event("files", "error",
                  f"Upload chunk fallito: {session.get('filename', '')}",
                  {"err": str(e)})
        return jsonify({"error": "Errore durante il caricamento del chunk"}), 500


@files_bp.route("/files/upload/finalize", methods=["POST"])
def api_files_upload_finalize():
    """Finalizza l'upload: sposta il file temporaneo nella destinazione."""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "")

    with _upload_lock:
        session = _upload_sessions.pop(session_id, None)

    if session is None:
        return jsonify({"error": "Sessione non trovata"}), 404

    tmp_path = session["tmp_path"]
    dest_path = os.path.join(session["destination"], session["filename"])

    try:
        if os.path.exists(dest_path):
            base, ext = os.path.splitext(session["filename"])
            dest_path = os.path.join(session["destination"],
                                     f"{base}_{int(_time.time())}{ext}")

        shutil.move(tmp_path, dest_path)
        log(f"Upload completato: {dest_path}", "info")
        return jsonify({
            "status": "ok",
            "path": dest_path,
            "filename": os.path.basename(dest_path),
            "size": os.path.getsize(dest_path),
        })
    except Exception as e:
        log(f"Errore finalize upload {session_id}: {e}", "error")
        log_event("files", "error",
                  f"Upload finalize fallito: {session.get('filename', '')}",
                  {"err": str(e)})
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        return jsonify({"error": "Impossibile finalizzare l'upload"}), 500
