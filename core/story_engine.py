"""
core/story_engine.py — Motore di generazione storie audio.

Pipeline in 5 fasi:
  1. Generazione script con GPT-4
  2. Sintesi vocale multi-voce con OpenAI TTS
  3. Preparazione SFX e musiche
  4. Mixaggio con FFmpeg
  5. Finalizzazione (metadati + copia in cartella statuine)
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid

from config import (
    STORY_STUDIO_STORIES_DIR,
    STORY_STUDIO_SFX_DIR,
    STORY_STUDIO_MUSIC_DIR,
    STORY_STUDIO_OUTPUT_DIR,
)
from core.utils import log

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

OPENAI_VOICES = {
    "nova":    "Femminile calda",
    "shimmer": "Femminile dolce",
    "fable":   "Maschile narrativa",
    "echo":    "Maschile profonda",
    "alloy":   "Neutra",
    "onyx":    "Maschile grave",
}

AGE_GROUPS = ["bambino", "ragazzo", "adulto"]

DURATIONS = {
    "short":  {"label": "Breve (2-3 min)",   "lines": 10},
    "medium": {"label": "Media (5-7 min)",   "lines": 25},
    "long":   {"label": "Lunga (10-15 min)", "lines": 50},
}

# Generazioni attive: {story_id: thread}
_active_generations: dict = {}
_gen_lock = threading.Lock()


# ===========================================================================
# FASE 1 — GENERAZIONE SCRIPT GPT-4
# ===========================================================================

def _build_system_prompt(age_group: str, duration: str, characters: list | None) -> str:
    dur_info = DURATIONS.get(duration, DURATIONS["medium"])
    target_lines = dur_info["lines"]

    age_desc = {
        "bambino": "bambini dai 3 agli 8 anni (linguaggio semplice, frasi brevi, toni rassicuranti)",
        "ragazzo": "ragazzi dai 9 ai 14 anni (linguaggio più ricco, avventura, umorismo leggero)",
        "adulto":  "adulti (linguaggio complesso, temi profondi, narrativa elaborata)",
    }.get(age_group, "bambini")

    char_hint = ""
    if characters:
        char_list = ", ".join(f"{c['name']} (voce: {c['voice']})" for c in characters)
        char_hint = f"\nPersonaggi già definiti: {char_list}. Includili nella storia."

    sfx_list = (
        "rain_light, rain_heavy, wind_gentle, wind_storm, thunder, birds_morning, "
        "crickets_night, river_stream, ocean_waves, fire_crackling, owl_hoot, wolf_howl, "
        "horse_gallop, cat_meow, dog_bark, rooster_crow, footsteps_grass, footsteps_stone, "
        "footsteps_snow, door_open, door_creak, door_slam, knock_door, key_lock, "
        "magic_sparkle, magic_whoosh, magic_bell, dragon_roar, sword_draw, sword_clash, "
        "treasure_open, potion_bubble, crowd_cheer, clock_tick, bell_tower, drip_cave, "
        "wooden_bridge"
    )

    music_list = (
        "gentle_fantasy, adventure_epic, mystery_dark, happy_playful, night_lullaby, "
        "forest_ambient, castle_royal, underwater, space_cosmic, victory_celebration"
    )

    return f"""Sei un autore professionista di storie audio per {age_desc}.
Il tuo compito è generare uno script strutturato in JSON per una storia audio in italiano.
{char_hint}

REGOLE:
- Tutto in italiano
- Circa {target_lines} battute totali nelle scene
- Usa SFX per arricchire l'atmosfera
- Ogni scena ha una musica di sottofondo

VOCI: nova (femminile calda), shimmer (femminile dolce), echo (maschile profonda),
      fable (maschile narrativa), alloy (neutra), onyx (maschile grave)

SFX DISPONIBILI: {sfx_list}
MUSICHE DISPONIBILI: {music_list}

OUTPUT (solo JSON valido, nient'altro):
{{
  "title": "Titolo",
  "characters": [
    {{"name": "Narratore", "voice": "fable", "role": "narrator"}},
    {{"name": "Nome", "voice": "echo", "role": "character"}}
  ],
  "scenes": [
    {{
      "scene_number": 1,
      "setting": "Luogo",
      "music": "gentle_fantasy",
      "lines": [
        {{"character": "Narratore", "text": "...", "sfx_before": null, "sfx_after": null}}
      ]
    }}
  ]
}}"""


def generate_script(client, prompt: str, age_group: str, duration: str,
                    characters: list | None = None) -> dict:
    """Usa GPT-4 per generare lo script. Ritorna dict validato."""
    system_prompt = _build_system_prompt(age_group, duration, characters)

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": f"Crea una storia audio su: {prompt}"},
        ],
        temperature=0.85,
        max_tokens=4000,
    )

    raw = response.choices[0].message.content.strip()
    # Rimuovi backtick markdown se presenti
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)

    script = json.loads(raw)

    if "scenes" not in script or not isinstance(script["scenes"], list):
        raise ValueError("Script non valido: mancano le scene")
    if "characters" not in script or not isinstance(script["characters"], list):
        raise ValueError("Script non valido: mancano i personaggi")

    return script


# ===========================================================================
# FASE 2 — SINTESI VOCALE
# ===========================================================================

def _char_voice_map(script: dict, narrator_voice: str) -> dict:
    mapping = {}
    for char in script.get("characters", []):
        name = char.get("name", "")
        voice = char.get("voice", "nova")
        if voice not in OPENAI_VOICES:
            voice = "nova"
        if char.get("role") == "narrator" and narrator_voice in OPENAI_VOICES:
            voice = narrator_voice
        mapping[name] = voice
    return mapping


def synthesize_lines(client, script: dict, story_dir: str,
                     narrator_voice: str = "nova",
                     progress_callback=None) -> list:
    """Genera MP3 per ogni battuta. Ritorna lista di metadati battute."""
    lines_dir = os.path.join(story_dir, "lines")
    os.makedirs(lines_dir, exist_ok=True)

    voice_map = _char_voice_map(script, narrator_voice)

    all_lines = []
    for scene in script.get("scenes", []):
        for line in scene.get("lines", []):
            all_lines.append({
                "character":  line.get("character", "Narratore"),
                "text":       line.get("text", ""),
                "sfx_before": line.get("sfx_before"),
                "sfx_after":  line.get("sfx_after"),
            })

    results = []
    total = len(all_lines)

    for idx, line_info in enumerate(all_lines):
        char = line_info["character"]
        text = line_info["text"].strip()
        if not text:
            continue

        voice = voice_map.get(char, narrator_voice)
        safe_char = re.sub(r"[^a-z0-9_]", "_", char.lower())
        filename = f"line_{idx + 1:03d}_{safe_char}.mp3"
        filepath = os.path.join(lines_dir, filename)

        if not os.path.isfile(filepath):
            tts_resp = client.audio.speech.create(
                model="tts-1-hd",
                voice=voice,
                input=text,
            )
            tts_resp.stream_to_file(filepath)

        word_count = len(text.split())
        duration_ms = int(word_count / 150 * 60 * 1000)

        results.append({
            "path":        filepath,
            "character":   char,
            "text":        text,
            "voice":       voice,
            "duration_ms": duration_ms,
            "sfx_before":  line_info["sfx_before"],
            "sfx_after":   line_info["sfx_after"],
            "index":       idx,
        })

        if progress_callback:
            progress_callback(idx + 1, total)

    return results


# ===========================================================================
# FASE 3 — ASSET (SFX + MUSICA)
# ===========================================================================

def prepare_audio_assets(script: dict, story_dir: str) -> dict:
    """Genera/copia SFX e musiche necessari. Ritorna mapping {key: path}."""
    from core.sfx_generator import generate_sfx, SFX_CATALOG
    from core.music_generator import generate_music, MUSIC_CATALOG

    assets_dir = os.path.join(story_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    sfx_needed = set()
    music_needed = set()
    for scene in script.get("scenes", []):
        music = scene.get("music")
        if music and music in MUSIC_CATALOG:
            music_needed.add(music)
        for line in scene.get("lines", []):
            for field in ["sfx_before", "sfx_after"]:
                sfx_id = line.get(field)
                if sfx_id and sfx_id in SFX_CATALOG:
                    sfx_needed.add(sfx_id)

    assets = {}

    for sfx_id in sfx_needed:
        global_sfx = os.path.join(STORY_STUDIO_SFX_DIR, f"{sfx_id}.wav")
        if not os.path.isfile(global_sfx):
            try:
                generate_sfx(sfx_id, STORY_STUDIO_SFX_DIR)
            except Exception as e:
                log(f"SFX [{sfx_id}]: {e}", "warning")
                continue
        dest = os.path.join(assets_dir, f"sfx_{sfx_id}.wav")
        if not os.path.isfile(dest):
            shutil.copy2(global_sfx, dest)
        assets[f"sfx_{sfx_id}"] = dest

    for music_id in music_needed:
        global_music = os.path.join(STORY_STUDIO_MUSIC_DIR, f"{music_id}.wav")
        if not os.path.isfile(global_music):
            try:
                generate_music(music_id, STORY_STUDIO_MUSIC_DIR)
            except Exception as e:
                log(f"Music [{music_id}]: {e}", "warning")
                continue
        dest = os.path.join(assets_dir, f"music_{music_id}.wav")
        if not os.path.isfile(dest):
            shutil.copy2(global_music, dest)
        assets[f"music_{music_id}"] = dest

    return assets


# ===========================================================================
# FASE 4 — MIXAGGIO FFMPEG
# ===========================================================================

def _check_ffmpeg() -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def mix_story(script: dict, lines_info: list, assets: dict,
              story_dir: str, enable_sfx: bool = True,
              enable_music: bool = True) -> str:
    """Mixa voci, SFX e musica con FFmpeg. Ritorna path del MP3 finale."""
    if not lines_info:
        raise ValueError("Nessuna battuta da mixare")

    output_path = os.path.join(story_dir, "final.mp3")

    if not _check_ffmpeg():
        log("FFmpeg non disponibile: concatenazione semplice", "warning")
        return _mix_simple_concat(lines_info, output_path)

    inputs = []
    audio_labels = []

    for line_info in lines_info:
        if os.path.isfile(line_info["path"]):
            inputs.extend(["-i", line_info["path"]])
            audio_labels.append(f"[{len(inputs) // 2 - 1}:a]")

    if not audio_labels:
        raise ValueError("Nessun file audio delle battute trovato")

    voice_count = len(audio_labels)

    music_input_idx = None
    if enable_music:
        for scene in script.get("scenes", []):
            music_id = scene.get("music")
            if music_id:
                music_key = f"music_{music_id}"
                if music_key in assets and os.path.isfile(assets[music_key]):
                    inputs.extend(["-i", assets[music_key]])
                    music_input_idx = len(inputs) // 2 - 1
                    break

    filter_parts = []

    if voice_count == 1:
        voice_chain = audio_labels[0]
    else:
        concat_inputs = "".join(audio_labels)
        filter_parts.append(f"{concat_inputs}concat=n={voice_count}:v=0:a=1[voices]")
        voice_chain = "[voices]"

    if music_input_idx is not None:
        music_label = f"[{music_input_idx}:a]"
        filter_parts.append(f"{music_label}volume=0.12,aloop=loop=-1:size=2e+09[bg]")
        filter_parts.append(
            f"{voice_chain}[bg]amix=inputs=2:duration=first:dropout_transition=2[mixed]"
        )
        final_label = "[mixed]"
    else:
        final_label = voice_chain

    filter_parts.append(
        f"{final_label}afade=t=in:st=0:d=1.5,afade=t=out:st=999:d=2[out]"
    )

    cmd = ["ffmpeg", "-y"]
    cmd.extend(inputs)
    if filter_parts:
        cmd.extend(["-filter_complex", ";".join(filter_parts)])
        cmd.extend(["-map", "[out]"])
    else:
        cmd.extend(["-map", "0:a"])

    cmd.extend(["-ac", "2", "-ar", "44100", "-b:a", "192k", "-codec:a", "libmp3lame", output_path])

    log(f"FFmpeg mix: {len(lines_info)} battute", "info")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        log(f"FFmpeg errore: {result.stderr[-500:]}", "error")
        return _mix_simple_concat(lines_info, output_path)

    return output_path


def _mix_simple_concat(lines_info: list, output_path: str) -> str:
    valid_files = [li["path"] for li in lines_info if os.path.isfile(li["path"])]
    if not valid_files:
        raise ValueError("Nessun file audio trovato")

    if not _check_ffmpeg():
        shutil.copy2(valid_files[0], output_path)
        return output_path

    concat_list = output_path + "_list.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for p in valid_files:
            f.write(f"file '{p}'\n")

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", output_path]
    subprocess.run(cmd, capture_output=True, timeout=120)

    try:
        os.remove(concat_list)
    except Exception:
        pass

    if not os.path.isfile(output_path):
        shutil.copy2(valid_files[0], output_path)

    return output_path


# ===========================================================================
# FASE 5 — FINALIZZAZIONE
# ===========================================================================

def finalize_story(story_id: str, story_dir: str, script: dict,
                   final_path: str, title: str) -> dict:
    """Salva metadati e copia il file nella cartella statuine."""
    duration_sec = 0.0
    if os.path.isfile(final_path) and _check_ffmpeg():
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", final_path],
                capture_output=True, text=True, timeout=10,
            )
            info = json.loads(result.stdout)
            duration_sec = float(info.get("format", {}).get("duration", 0))
        except Exception:
            pass

    safe_title = re.sub(r"[^\w\s-]", "", title.lower())
    safe_title = re.sub(r"[\s_-]+", "_", safe_title).strip("_") or story_id[:8]

    output_filename = f"{safe_title}_{story_id[:8]}.mp3"
    output_dest = os.path.join(STORY_STUDIO_OUTPUT_DIR, output_filename)
    try:
        if os.path.isfile(final_path):
            shutil.copy2(final_path, output_dest)
    except Exception as e:
        log(f"Copia statuine fallita: {e}", "warning")
        output_dest = None

    meta = {
        "id":           story_id,
        "title":        title,
        "status":       "completed",
        "duration_sec": round(duration_sec, 1),
        "file_path":    final_path,
        "output_path":  output_dest,
        "characters":   script.get("characters", []),
        "scene_count":  len(script.get("scenes", [])),
        "created_at":   time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    meta_path = os.path.join(story_dir, "metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return meta


# ===========================================================================
# PIPELINE COMPLETA (eseguita in background)
# ===========================================================================

def _save_meta(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run_story_pipeline(story_id: str, params: dict) -> None:
    """Pipeline completa in background."""
    from api.ai import get_openai_client
    from core.extensions import socketio

    title          = params.get("title", "Storia senza titolo")
    prompt         = params.get("prompt", "")
    age_group      = params.get("age_group", "bambino")
    duration       = params.get("duration", "medium")
    narrator_voice = params.get("narrator_voice", "nova")
    enable_sfx     = params.get("enable_sfx", True)
    enable_music   = params.get("enable_music", True)
    characters     = params.get("characters") or None

    story_dir  = os.path.join(STORY_STUDIO_STORIES_DIR, story_id)
    meta_path  = os.path.join(story_dir, "metadata.json")
    os.makedirs(story_dir, exist_ok=True)

    def _emit(phase, progress, message, **extra):
        payload = {"story_id": story_id, "phase": phase,
                   "progress": progress, "message": message}
        payload.update(extra)
        try:
            socketio.emit("story_studio_progress", payload)
        except Exception:
            pass
        log(f"Story [{story_id[:8]}] {phase} {progress}%: {message}", "info")

    _save_meta(meta_path, {
        "id": story_id, "title": title, "status": "in_progress",
        "duration_sec": 0, "file_path": None, "output_path": None,
        "characters": [], "scene_count": 0,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "prompt": prompt, "age_group": age_group, "duration": duration,
    })

    try:
        _emit("scripting", 5, "Generazione script con GPT-4...")
        client = get_openai_client()
        script = generate_script(client, prompt, age_group, duration, characters)

        script_path = os.path.join(story_dir, "script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f, ensure_ascii=False, indent=2)

        total_lines = sum(len(s.get("lines", [])) for s in script.get("scenes", []))
        _emit("scripting", 20, "Script generato!", total_lines=total_lines)

        _emit("synthesizing", 25, f"Sintesi vocale: 0 di {total_lines} battute...",
              current_line=0, total_lines=total_lines)

        def _synth_cb(current, total):
            pct = 25 + int((current / total) * 35)
            _emit("synthesizing", pct,
                  f"Sintesi voce: {current} di {total} battute...",
                  current_line=current, total_lines=total)

        lines_info = synthesize_lines(client, script, story_dir, narrator_voice, _synth_cb)
        _emit("synthesizing", 60, f"Sintesi completata: {len(lines_info)} battute")

        _emit("sfx", 65, "Preparazione effetti sonori e musiche...")
        assets = prepare_audio_assets(script, story_dir)
        _emit("sfx", 75, f"Asset pronti: {len(assets)} file")

        _emit("mixing", 80, "Mixaggio audio con FFmpeg...")
        final_path = mix_story(script, lines_info, assets, story_dir,
                               enable_sfx=enable_sfx, enable_music=enable_music)
        _emit("mixing", 92, "Mixaggio completato!")

        _emit("done", 95, "Finalizzazione...")
        meta = finalize_story(story_id, story_dir, script, final_path, title)
        _emit("done", 100, "Storia completata!", story=meta)

    except Exception as e:
        log(f"Story pipeline error [{story_id[:8]}]: {e}", "error")
        _save_meta(meta_path, {
            "id": story_id, "title": title, "status": "error",
            "error": str(e), "duration_sec": 0,
            "file_path": None, "output_path": None,
            "characters": [], "scene_count": 0,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        try:
            socketio.emit("story_studio_progress", {
                "story_id": story_id, "phase": "error",
                "progress": 0, "message": f"Errore: {e}",
            })
        except Exception:
            pass
    finally:
        with _gen_lock:
            _active_generations.pop(story_id, None)


# ===========================================================================
# GESTIONE STORIE
# ===========================================================================

def start_generation(params: dict) -> str:
    """Avvia la pipeline in background. Ritorna story_id."""
    story_id = str(uuid.uuid4())
    t = threading.Thread(target=run_story_pipeline, args=(story_id, params), daemon=True)
    with _gen_lock:
        _active_generations[story_id] = t
    t.start()
    return story_id


def list_stories() -> list:
    stories = []
    if not os.path.isdir(STORY_STUDIO_STORIES_DIR):
        return stories
    for story_id in os.listdir(STORY_STUDIO_STORIES_DIR):
        meta_path = os.path.join(STORY_STUDIO_STORIES_DIR, story_id, "metadata.json")
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    stories.append(json.load(f))
            except Exception:
                pass
    stories.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return stories


def get_story(story_id: str) -> dict | None:
    meta_path = os.path.join(STORY_STUDIO_STORIES_DIR, story_id, "metadata.json")
    if not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_story_script(story_id: str) -> dict | None:
    script_path = os.path.join(STORY_STUDIO_STORIES_DIR, story_id, "script.json")
    if not os.path.isfile(script_path):
        return None
    try:
        with open(script_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def delete_story(story_id: str) -> bool:
    story_dir = os.path.join(STORY_STUDIO_STORIES_DIR, story_id)
    if not os.path.isdir(story_dir):
        return False
    meta = get_story(story_id)
    if meta and meta.get("output_path") and os.path.isfile(meta["output_path"]):
        try:
            os.remove(meta["output_path"])
        except Exception:
            pass
    try:
        shutil.rmtree(story_dir)
        return True
    except Exception as e:
        log(f"Errore eliminazione storia [{story_id[:8]}]: {e}", "error")
        return False


def is_generating(story_id: str) -> bool:
    with _gen_lock:
        return story_id in _active_generations
