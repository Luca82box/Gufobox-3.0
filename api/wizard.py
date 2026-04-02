"""
api/wizard.py — REST API for the AI wizard state machine.

Endpoints:
  POST /api/wizard/start          — start wizard for a given category
  POST /api/wizard/submit         — submit an answer for the current stage
  GET  /api/wizard/status         — get current wizard state
  POST /api/wizard/cancel         — cancel / reset the wizard

The wizard is also automatically started by the RFID trigger when a statuette
with mode=school or mode=entertainment is read (see api/rfid.py).
"""
from flask import Blueprint, request, jsonify

from core.wizard import (
    wizard_start,
    wizard_submit,
    wizard_cancel,
    get_wizard_state,
    wizard_apply_config,
    VALID_CATEGORIES,
    STAGE_DONE,
)
from core.utils import log

wizard_bp = Blueprint("wizard", __name__)


@wizard_bp.route("/wizard/start", methods=["POST"])
def api_wizard_start():
    """
    Start the wizard for a given category.

    Body: { "category": "school" | "entertainment", "rfid_code": "<optional>" }
    """
    data = request.get_json(silent=True) or {}
    category = str(data.get("category", "")).strip().lower()
    rfid_code = str(data.get("rfid_code", "")).strip().upper() or None

    if not category:
        return jsonify({"error": "Il campo 'category' è obbligatorio"}), 400

    result = wizard_start(source_category=category, source_rfid=rfid_code)
    if result.get("error"):
        return jsonify({"error": result["error"]}), 400

    return jsonify({"status": "ok", "wizard": result})


@wizard_bp.route("/wizard/submit", methods=["POST"])
def api_wizard_submit():
    """
    Submit an answer for the current wizard stage.

    Body: { "answer": "<selected_option>" }

    When the wizard reaches stage=done the completed_config is applied
    automatically to the live AI educational settings.
    """
    data = request.get_json(silent=True) or {}
    answer = str(data.get("answer", "")).strip()

    if not answer:
        return jsonify({"error": "Il campo 'answer' è obbligatorio"}), 400

    result = wizard_submit(answer)
    if result.get("error"):
        return jsonify({"error": result["error"], "wizard": result.get("wizard")}), 400

    # Auto-apply config when wizard completes
    if result.get("current_stage") == STAGE_DONE and result.get("completed_config"):
        success, msg = wizard_apply_config()
        if not success:
            log(f"Wizard auto-apply fallito: {msg}", "warning")
            return jsonify({
                "status": "completed_with_error",
                "wizard": result,
                "apply_error": "Errore durante l'applicazione della configurazione.",
            })
        return jsonify({"status": "completed", "wizard": result, "apply_message": "Configurazione applicata con successo."})

    return jsonify({"status": "ok", "wizard": result})


@wizard_bp.route("/wizard/status", methods=["GET"])
def api_wizard_status():
    """Return the current wizard state."""
    return jsonify(get_wizard_state())


@wizard_bp.route("/wizard/cancel", methods=["POST"])
def api_wizard_cancel():
    """Cancel (reset) the current wizard."""
    result = wizard_cancel()
    return jsonify({"status": "ok", "wizard": result})
