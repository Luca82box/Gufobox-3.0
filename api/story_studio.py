"""
api/story_studio.py — Blueprint Flask per Story Studio.

Endpoints:
  POST   /api/story-studio/generate
  GET    /api/story-studio/stories
  GET    /api/story-studio/story/<id>
  GET    /api/story-studio/story/<id>/audio
  DELETE /api/story-studio/story/<id>
  GET    /api/story-studio/story/<id>/script
  POST   /api/story-studio/story/<id>/regenerate
  GET    /api/story-studio/sfx
  GET    /api/story-studio/voices
"""

import os
import re
import threading

from flask import Blueprint, request, jsonify, send_file

from core.utils import log
from core.story_engine import (
    OPENAI_VOICES, AGE_GROUPS, DURATIONS,
    start_generation, list_stories, get_story,
    get_story_script, delete_story, is_generating,
    run_story_pipeline, _active_generations, _gen_lock,
)

story_studio_bp = Blueprint("story_studio", __name__)

_MAX_TITLE_LEN   = 200
_MAX_PROMPT_LEN  = 2000
_MAX_CHAR_NAME   = 80
_MAX_CHARACTERS  = 8


# ---------------------------------------------------------------------------
# Validazione
# ---------------------------------------------------------------------------

def _validate_generate_input(data: dict) -> str | None:
    title = (data.get("title") or "").strip()
    if not title:
        return "Il titolo è obbligatorio"
    if len(title) > _MAX_TITLE_LEN:
        return f"Il titolo è troppo lungo (max {_MAX_TITLE_LEN} caratteri)"

    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return "Lo spunto della storia è obbligatorio"
    if len(prompt) > _MAX_PROMPT_LEN:
        return f"Lo spunto è troppo lungo (max {_MAX_PROMPT_LEN} caratteri)"

    if data.get("age_group", "bambino") not in AGE_GROUPS:
        return f"Fascia d'età non valida. Usa: {', '.join(AGE_GROUPS)}"

    if data.get("duration", "medium") not in DURATIONS:
        return f"Durata non valida. Usa: {', '.join(DURATIONS.keys())}"

    if data.get("narrator_voice", "nova") not in OPENAI_VOICES:
        return f"Voce narratore non valida. Usa: {', '.join(OPENAI_VOICES.keys())}"

    characters = data.get("characters")
    if characters is not None:
        if not isinstance(characters, list):
            return "Il campo 'characters' deve essere una lista"
        if len(characters) > _MAX_CHARACTERS:
            return f"Troppi personaggi (max {_MAX_CHARACTERS})"
        for i, char in enumerate(characters):
            if not isinstance(char, dict):
                return f"Personaggio #{i+1} non valido"
            name = (char.get("name") or "").strip()
            if not name:
                return f"Il nome del personaggio #{i+1} è obbligatorio"
            if len(name) > _MAX_CHAR_NAME:
                return f"Nome del personaggio #{i+1} troppo lungo"
            if char.get("voice", "nova") not in OPENAI_VOICES:
                return f"Voce del personaggio '{name}' non valida"

    return None


def _safe_story_id(story_id: str) -> str | None:
    if not re.match(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        story_id, re.IGNORECASE
    ):
        return None
    return story_id.lower()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@story_studio_bp.route("/story-studio/generate", methods=["POST"])
def api_generate_story():
    data = request.get_json(silent=True) or {}

    error = _validate_generate_input(data)
    if error:
        return jsonify({"error": error}), 400

    params = {
        "title":          data["title"].strip(),
        "prompt":         data["prompt"].strip(),
        "age_group":      data.get("age_group", "bambino"),
        "duration":       data.get("duration", "medium"),
        "narrator_voice": data.get("narrator_voice", "nova"),
        "enable_sfx":     bool(data.get("enable_sfx", True)),
        "enable_music":   bool(data.get("enable_music", True)),
        "characters":     data.get("characters") or None,
    }

    try:
        story_id = start_generation(params)
    except Exception as e:
        log(f"Errore avvio generazione: {e}", "error")
        return jsonify({"error": "Errore interno durante l'avvio"}), 500

    return jsonify({"status": "started", "story_id": story_id}), 202


@story_studio_bp.route("/story-studio/stories", methods=["GET"])
def api_list_stories():
    try:
        return jsonify(list_stories())
    except Exception as e:
        log(f"Errore lista storie: {e}", "error")
        return jsonify({"error": "Errore nel recupero delle storie"}), 500


@story_studio_bp.route("/story-studio/story/<story_id>", methods=["GET"])
def api_get_story(story_id: str):
    safe_id = _safe_story_id(story_id)
    if not safe_id:
        return jsonify({"error": "ID storia non valido"}), 400
    meta = get_story(safe_id)
    if meta is None:
        return jsonify({"error": "Storia non trovata"}), 404
    meta["generating"] = is_generating(safe_id)
    return jsonify(meta)


@story_studio_bp.route("/story-studio/story/<story_id>/audio", methods=["GET"])
def api_story_audio(story_id: str):
    safe_id = _safe_story_id(story_id)
    if not safe_id:
        return jsonify({"error": "ID storia non valido"}), 400
    meta = get_story(safe_id)
    if meta is None:
        return jsonify({"error": "Storia non trovata"}), 404
    file_path = meta.get("file_path")
    if not file_path or not os.path.isfile(file_path):
        return jsonify({"error": "File audio non disponibile"}), 404
    return send_file(file_path, mimetype="audio/mpeg", as_attachment=False)


@story_studio_bp.route("/story-studio/story/<story_id>", methods=["DELETE"])
def api_delete_story(story_id: str):
    safe_id = _safe_story_id(story_id)
    if not safe_id:
        return jsonify({"error": "ID storia non valido"}), 400
    if is_generating(safe_id):
        return jsonify({"error": "Impossibile eliminare: generazione in corso"}), 409
    if get_story(safe_id) is None:
        return jsonify({"error": "Storia non trovata"}), 404
    if delete_story(safe_id):
        return jsonify({"status": "deleted", "story_id": safe_id})
    return jsonify({"error": "Errore durante l'eliminazione"}), 500


@story_studio_bp.route("/story-studio/story/<story_id>/script", methods=["GET"])
def api_story_script(story_id: str):
    safe_id = _safe_story_id(story_id)
    if not safe_id:
        return jsonify({"error": "ID storia non valido"}), 400
    if get_story(safe_id) is None:
        return jsonify({"error": "Storia non trovata"}), 404
    script = get_story_script(safe_id)
    if script is None:
        return jsonify({"error": "Script non disponibile"}), 404
    return jsonify(script)


@story_studio_bp.route("/story-studio/story/<story_id>/regenerate", methods=["POST"])
def api_regenerate_story(story_id: str):
    safe_id = _safe_story_id(story_id)
    if not safe_id:
        return jsonify({"error": "ID storia non valido"}), 400
    if is_generating(safe_id):
        return jsonify({"error": "Storia già in generazione"}), 409
    meta = get_story(safe_id)
    if meta is None:
        return jsonify({"error": "Storia non trovata"}), 404

    params = {
        "title":          meta.get("title", "Storia"),
        "prompt":         meta.get("prompt", ""),
        "age_group":      meta.get("age_group", "bambino"),
        "duration":       meta.get("duration", "medium"),
        "narrator_voice": meta.get("narrator_voice", "nova"),
        "enable_sfx":     meta.get("enable_sfx", True),
        "enable_music":   meta.get("enable_music", True),
        "characters":     meta.get("characters"),
    }
    data = request.get_json(silent=True) or {}
    params.update({k: v for k, v in data.items() if k in params})

    try:
        t = threading.Thread(target=run_story_pipeline, args=(safe_id, params), daemon=True)
        with _gen_lock:
            _active_generations[safe_id] = t
        t.start()
    except Exception as e:
        log(f"Errore rigenerazione: {e}", "error")
        return jsonify({"error": "Errore durante la rigenerazione"}), 500

    return jsonify({"status": "started", "story_id": safe_id}), 202


@story_studio_bp.route("/story-studio/sfx", methods=["GET"])
def api_sfx_list():
    from core.sfx_generator import SFX_CATALOG
    return jsonify([{"id": k, "label": v} for k, v in SFX_CATALOG.items()])


@story_studio_bp.route("/story-studio/voices", methods=["GET"])
def api_voices_list():
    return jsonify([{"id": k, "label": v} for k, v in OPENAI_VOICES.items()])
