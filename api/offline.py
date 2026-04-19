"""
api/offline.py — Endpoints per la gestione dei contenuti offline.

Endpoints:
  POST   /api/offline/generate           - Avvia la generazione in background
  GET    /api/offline/generate/status    - Stato della generazione in corso
  GET    /api/offline/content            - Lista contenuti offline disponibili
  DELETE /api/offline/content/<mode>     - Elimina contenuti di un mode
"""

import threading

from flask import Blueprint, request, jsonify

from core.utils import log
from core.extensions import socketio

offline_bp = Blueprint("offline", __name__)


def _run_generation(modes, force):
    """Esegue la generazione in un thread separato ed emette aggiornamenti via Socket.IO."""
    from core.offline_generator import generate_offline_content, get_generation_state

    try:
        result = generate_offline_content(modes=modes, force=force)
        socketio.emit("offline_generation_progress", {
            "running": False,
            "done": True,
            "generated": result["generated"],
            "skipped": result["skipped"],
            "errors": result["errors"],
        })
        log(
            f"Offline generation complete: {result['generated']} generated, "
            f"{result['skipped']} skipped, {len(result['errors'])} errors",
            "info",
        )
    except Exception as e:
        log(f"Offline generation thread error: {e}", "error")
        socketio.emit("offline_generation_progress", {
            "running": False,
            "done": True,
            "error": str(e),
        })


@offline_bp.route("/offline/generate", methods=["POST"])
def api_offline_generate():
    """Avvia la generazione dei contenuti offline in background."""
    from core.offline_generator import get_generation_state

    state = get_generation_state()
    if state["running"]:
        return jsonify({"error": "Generazione già in corso"}), 409

    data = request.get_json(silent=True) or {}
    modes = data.get("modes") or None
    force = bool(data.get("force", False))

    # Validazione modes
    if modes is not None:
        if not isinstance(modes, list):
            return jsonify({"error": "Il campo 'modes' deve essere una lista"}), 400
        from core.offline_generator import OFFLINE_TEMPLATES
        invalid = [m for m in modes if m not in OFFLINE_TEMPLATES]
        if invalid:
            return jsonify({"error": f"Mode non validi: {invalid}"}), 400

    t = threading.Thread(target=_run_generation, args=(modes, force), daemon=True)
    t.start()

    return jsonify({"status": "started"}), 202


@offline_bp.route("/offline/generate/status", methods=["GET"])
def api_offline_generate_status():
    """Restituisce lo stato corrente della generazione."""
    from core.offline_generator import get_generation_state

    state = get_generation_state()
    return jsonify({
        "running": state["running"],
        "progress": state["progress"],
        "total": state["total"],
        "current_mode": state["current_mode"],
        "generated": state["generated"],
        "skipped": state["skipped"],
        "errors": state["errors"],
    })


@offline_bp.route("/offline/content", methods=["GET"])
def api_offline_content():
    """Elenca i contenuti offline disponibili per ogni mode."""
    from core.offline_generator import list_offline_content

    return jsonify(list_offline_content())


@offline_bp.route("/offline/content/<mode>", methods=["DELETE"])
def api_offline_content_delete(mode):
    """Elimina i contenuti offline di un mode specifico."""
    from core.offline_generator import delete_offline_content, OFFLINE_TEMPLATES

    if mode not in OFFLINE_TEMPLATES:
        return jsonify({"error": f"Mode non valido: {mode}"}), 404

    try:
        result = delete_offline_content(mode)
        return jsonify(result)
    except ValueError:
        return jsonify({"error": "Mode non valido"}), 400
    except Exception as e:
        log(f"Errore eliminazione contenuti offline {mode}: {e}", "error")
        return jsonify({"error": "Errore interno durante l'eliminazione"}), 500
