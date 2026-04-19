"""
tests/test_story_studio.py — Test per Story Studio.

Strategia:
- OpenAI client è sempre mockato (niente chiamate reali)
- FFmpeg è mockato dove necessario
- Verifica struttura JSON, file generati, endpoint API
"""

import json
import os
import struct
import tempfile
import threading
import time
import wave
import uuid
import pytest

from unittest.mock import MagicMock, patch, PropertyMock


# ===========================================================================
# Helpers
# ===========================================================================

def _is_valid_wav(path: str) -> bool:
    try:
        with wave.open(path, "r") as wf:
            return wf.getnframes() > 0
    except Exception:
        return False


# ===========================================================================
# SFX Generator
# ===========================================================================

class TestSfxGenerator:
    def test_sfx_catalog_not_empty(self):
        from core.sfx_generator import SFX_CATALOG
        assert len(SFX_CATALOG) >= 30

    def test_sfx_catalog_ids_are_strings(self):
        from core.sfx_generator import SFX_CATALOG
        for k, v in SFX_CATALOG.items():
            assert isinstance(k, str)
            assert isinstance(v, str)
            assert len(k) > 0
            assert len(v) > 0

    def test_generate_sfx_creates_valid_wav(self, tmp_path):
        from core.sfx_generator import generate_sfx
        path = generate_sfx("door_creak", str(tmp_path))
        assert os.path.isfile(path)
        assert _is_valid_wav(path)

    def test_generate_sfx_magic_sparkle(self, tmp_path):
        from core.sfx_generator import generate_sfx
        path = generate_sfx("magic_sparkle", str(tmp_path))
        assert _is_valid_wav(path)

    def test_generate_sfx_thunder(self, tmp_path):
        from core.sfx_generator import generate_sfx
        path = generate_sfx("thunder", str(tmp_path))
        assert _is_valid_wav(path)

    def test_generate_sfx_invalid_id_raises(self, tmp_path):
        from core.sfx_generator import generate_sfx
        with pytest.raises(KeyError):
            generate_sfx("nonexistent_sfx_xyz", str(tmp_path))

    def test_generate_all_sfx(self, tmp_path):
        from core.sfx_generator import generate_all_sfx, SFX_CATALOG
        results = generate_all_sfx(str(tmp_path))
        assert len(results) == len(SFX_CATALOG)
        for k, p in results.items():
            assert p is not None, f"SFX '{k}' ha fallito"
            assert os.path.isfile(p)
            assert _is_valid_wav(p)

    def test_get_sfx_path_exists(self, tmp_path):
        from core.sfx_generator import generate_sfx, get_sfx_path
        generate_sfx("owl_hoot", str(tmp_path))
        path = get_sfx_path("owl_hoot", str(tmp_path))
        assert path is not None
        assert os.path.isfile(path)

    def test_get_sfx_path_missing(self, tmp_path):
        from core.sfx_generator import get_sfx_path
        assert get_sfx_path("rain_light", str(tmp_path)) is None

    def test_wav_sample_rate(self, tmp_path):
        from core.sfx_generator import generate_sfx
        path = generate_sfx("clock_tick", str(tmp_path))
        with wave.open(path, "r") as wf:
            assert wf.getframerate() == 44100
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2


# ===========================================================================
# Music Generator
# ===========================================================================

class TestMusicGenerator:
    def test_music_catalog_not_empty(self):
        from core.music_generator import MUSIC_CATALOG
        assert len(MUSIC_CATALOG) >= 10

    def test_music_catalog_all_ids_unique(self):
        from core.music_generator import MUSIC_CATALOG
        keys = list(MUSIC_CATALOG.keys())
        assert len(keys) == len(set(keys))

    def test_generate_music_gentle_fantasy(self, tmp_path):
        from core.music_generator import generate_music
        path = generate_music("gentle_fantasy", str(tmp_path))
        assert os.path.isfile(path)
        assert _is_valid_wav(path)

    def test_generate_music_adventure_epic(self, tmp_path):
        from core.music_generator import generate_music
        path = generate_music("adventure_epic", str(tmp_path))
        assert _is_valid_wav(path)

    def test_generate_music_night_lullaby(self, tmp_path):
        from core.music_generator import generate_music
        path = generate_music("night_lullaby", str(tmp_path))
        assert _is_valid_wav(path)

    def test_generate_music_invalid_raises(self, tmp_path):
        from core.music_generator import generate_music
        with pytest.raises(KeyError):
            generate_music("nonexistent_music", str(tmp_path))

    def test_generate_all_music(self, tmp_path):
        from core.music_generator import generate_all_music, MUSIC_CATALOG
        results = generate_all_music(str(tmp_path))
        assert len(results) == len(MUSIC_CATALOG)
        for k, p in results.items():
            assert p is not None, f"Musica '{k}' ha fallito"
            assert _is_valid_wav(p)

    def test_get_music_path_exists(self, tmp_path):
        from core.music_generator import generate_music, get_music_path
        generate_music("happy_playful", str(tmp_path))
        path = get_music_path("happy_playful", str(tmp_path))
        assert path is not None

    def test_get_music_path_missing(self, tmp_path):
        from core.music_generator import get_music_path
        assert get_music_path("space_cosmic", str(tmp_path)) is None

    def test_music_wav_params(self, tmp_path):
        from core.music_generator import generate_music
        path = generate_music("mystery_dark", str(tmp_path))
        with wave.open(path, "r") as wf:
            assert wf.getframerate() == 44100
            assert wf.getsampwidth() == 2


# ===========================================================================
# Story Engine
# ===========================================================================

SAMPLE_SCRIPT = {
    "title": "Il Draghetto Timido",
    "characters": [
        {"name": "Narratore", "voice": "fable", "role": "narrator"},
        {"name": "Fuochino", "voice": "echo", "role": "character"},
    ],
    "scenes": [
        {
            "scene_number": 1,
            "setting": "Una grotta",
            "music": "gentle_fantasy",
            "lines": [
                {"character": "Narratore", "text": "C'era una volta un draghetto.", "sfx_before": "drip_cave", "sfx_after": None},
                {"character": "Fuochino", "text": "Ho paura del buio!", "sfx_before": None, "sfx_after": "door_creak"},
            ],
        }
    ],
}


def _make_mock_client(script_dict=None):
    client = MagicMock()
    if script_dict is None:
        script_dict = SAMPLE_SCRIPT

    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(script_dict)

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    client.chat.completions.create.return_value = mock_response

    mock_tts = MagicMock()
    mock_tts.stream_to_file = MagicMock()
    client.audio.speech.create.return_value = mock_tts

    return client


class TestStoryEngine:
    def test_generate_script_valid(self):
        from core.story_engine import generate_script
        client = _make_mock_client()
        result = generate_script(client, "Un drago coraggioso", "bambino", "medium")
        assert "scenes" in result
        assert "characters" in result
        assert isinstance(result["scenes"], list)

    def test_generate_script_strips_markdown(self):
        from core.story_engine import generate_script
        client = _make_mock_client()
        raw_resp = f"```json\n{json.dumps(SAMPLE_SCRIPT)}\n```"
        client.chat.completions.create.return_value.choices[0].message.content = raw_resp
        result = generate_script(client, "test", "ragazzo", "short")
        assert "scenes" in result

    def test_generate_script_invalid_json_raises(self):
        from core.story_engine import generate_script
        client = MagicMock()
        client.chat.completions.create.return_value.choices[0].message.content = "not json {{{"
        with pytest.raises(Exception):
            generate_script(client, "test", "adulto", "long")

    def test_generate_script_missing_scenes_raises(self):
        from core.story_engine import generate_script
        bad_script = {"title": "X", "characters": []}
        client = _make_mock_client(bad_script)
        with pytest.raises(ValueError, match="scene"):
            generate_script(client, "test", "bambino", "short")

    def test_synthesize_lines_creates_files(self, tmp_path):
        from core.story_engine import synthesize_lines

        def fake_stream(path):
            with open(path, "wb") as f:
                f.write(b"\xff\xfb\x90\x00" * 100)

        client = MagicMock()
        client.audio.speech.create.return_value.stream_to_file.side_effect = fake_stream

        results = synthesize_lines(client, SAMPLE_SCRIPT, str(tmp_path), "fable")
        assert len(results) == 2
        assert all(os.path.isfile(r["path"]) for r in results)
        assert all(r["character"] in ("Narratore", "Fuochino") for r in results)

    def test_synthesize_lines_progress_callback(self, tmp_path):
        from core.story_engine import synthesize_lines

        def fake_stream(path):
            with open(path, "wb") as f:
                f.write(b"\xff\xfb" * 50)

        client = MagicMock()
        client.audio.speech.create.return_value.stream_to_file.side_effect = fake_stream

        calls = []
        synthesize_lines(client, SAMPLE_SCRIPT, str(tmp_path), "nova",
                         progress_callback=lambda c, t: calls.append((c, t)))
        assert len(calls) == 2
        assert calls[-1][0] == calls[-1][1]

    def test_synthesize_lines_skips_empty_text(self, tmp_path):
        from core.story_engine import synthesize_lines
        script = {
            "characters": [{"name": "N", "voice": "nova", "role": "narrator"}],
            "scenes": [{"scene_number": 1, "setting": "X", "music": None,
                         "lines": [{"character": "N", "text": "   ", "sfx_before": None, "sfx_after": None}]}],
        }
        client = MagicMock()
        results = synthesize_lines(client, script, str(tmp_path))
        assert len(results) == 0
        client.audio.speech.create.assert_not_called()

    def test_finalize_story_writes_metadata(self, tmp_path):
        from core.story_engine import finalize_story
        final_mp3 = tmp_path / "final.mp3"
        final_mp3.write_bytes(b"\xff\xfb" * 50)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = json.dumps({"format": {"duration": "180.5"}})
            meta = finalize_story("test-id-123", str(tmp_path), SAMPLE_SCRIPT,
                                  str(final_mp3), "Il Draghetto")
        assert meta["status"] == "completed"
        assert meta["title"] == "Il Draghetto"
        assert os.path.isfile(tmp_path / "metadata.json")

    def test_list_stories_empty(self, tmp_path):
        from core.story_engine import list_stories
        with patch("core.story_engine.STORY_STUDIO_STORIES_DIR", str(tmp_path)):
            result = list_stories()
        assert result == []

    def test_list_stories_with_entries(self, tmp_path):
        from core.story_engine import list_stories
        for i in range(3):
            sid = f"story-{i:04d}-0000-0000-0000-000000000000"
            d = tmp_path / sid
            d.mkdir()
            meta = {"id": sid, "title": f"Storia {i}", "status": "completed",
                    "created_at": f"2024-01-0{i+1}T10:00:00"}
            (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        with patch("core.story_engine.STORY_STUDIO_STORIES_DIR", str(tmp_path)):
            result = list_stories()
        assert len(result) == 3

    def test_get_story_found(self, tmp_path):
        from core.story_engine import get_story
        sid = "abcd1234-0000-0000-0000-000000000000"
        d = tmp_path / sid
        d.mkdir()
        meta = {"id": sid, "title": "Test"}
        (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        with patch("core.story_engine.STORY_STUDIO_STORIES_DIR", str(tmp_path)):
            result = get_story(sid)
        assert result["title"] == "Test"

    def test_get_story_not_found(self, tmp_path):
        from core.story_engine import get_story
        with patch("core.story_engine.STORY_STUDIO_STORIES_DIR", str(tmp_path)):
            assert get_story("nonexistent-uuid-0000-0000-000000000000") is None

    def test_delete_story(self, tmp_path):
        from core.story_engine import delete_story
        sid = "de1e0000-0000-0000-0000-000000000000"
        d = tmp_path / sid
        d.mkdir()
        meta = {"id": sid, "title": "X", "output_path": None}
        (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        with patch("core.story_engine.STORY_STUDIO_STORIES_DIR", str(tmp_path)):
            result = delete_story(sid)
        assert result is True
        assert not d.exists()

    def test_delete_story_not_found(self, tmp_path):
        from core.story_engine import delete_story
        with patch("core.story_engine.STORY_STUDIO_STORIES_DIR", str(tmp_path)):
            assert delete_story("00000000-0000-0000-0000-000000000000") is False


# ===========================================================================
# API Endpoints
# ===========================================================================

@pytest.fixture
def app():
    import sys
    sys.modules.setdefault("eventlet", MagicMock())

    from flask import Flask
    from api.story_studio import story_studio_bp
    app = Flask(__name__)
    app.register_blueprint(story_studio_bp, url_prefix="/api")
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestStoryStudioApi:
    def test_voices_endpoint(self, client):
        r = client.get("/api/story-studio/voices")
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)
        assert len(data) == 6
        ids = [v["id"] for v in data]
        assert "nova" in ids
        assert "echo" in ids

    def test_sfx_endpoint(self, client):
        r = client.get("/api/story-studio/sfx")
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, list)
        assert len(data) >= 30

    def test_list_stories_empty(self, client, tmp_path):
        with patch("core.story_engine.STORY_STUDIO_STORIES_DIR", str(tmp_path)):
            r = client.get("/api/story-studio/stories")
        assert r.status_code == 200
        assert r.get_json() == []

    def test_generate_missing_title(self, client):
        r = client.post("/api/story-studio/generate",
                        json={"prompt": "Una storia"}, content_type="application/json")
        assert r.status_code == 400
        assert "titolo" in r.get_json()["error"].lower()

    def test_generate_missing_prompt(self, client):
        r = client.post("/api/story-studio/generate",
                        json={"title": "Test"}, content_type="application/json")
        assert r.status_code == 400
        assert "spunto" in r.get_json()["error"].lower()

    def test_generate_invalid_voice(self, client):
        r = client.post("/api/story-studio/generate",
                        json={"title": "T", "prompt": "P", "narrator_voice": "invalid_voice"},
                        content_type="application/json")
        assert r.status_code == 400

    def test_generate_invalid_age_group(self, client):
        r = client.post("/api/story-studio/generate",
                        json={"title": "T", "prompt": "P", "age_group": "vecchio"},
                        content_type="application/json")
        assert r.status_code == 400

    def test_generate_invalid_duration(self, client):
        r = client.post("/api/story-studio/generate",
                        json={"title": "T", "prompt": "P", "duration": "forever"},
                        content_type="application/json")
        assert r.status_code == 400

    def test_generate_invalid_character_voice(self, client):
        r = client.post("/api/story-studio/generate",
                        json={"title": "T", "prompt": "P",
                              "characters": [{"name": "Drago", "voice": "robot_bad"}]},
                        content_type="application/json")
        assert r.status_code == 400

    def test_generate_too_many_characters(self, client):
        chars = [{"name": f"C{i}", "voice": "nova"} for i in range(10)]
        r = client.post("/api/story-studio/generate",
                        json={"title": "T", "prompt": "P", "characters": chars},
                        content_type="application/json")
        assert r.status_code == 400

    def test_generate_valid_starts(self, client):
        with patch("core.story_engine.start_generation", return_value="test-uuid-1234-5678-abcd12345678"):
            r = client.post("/api/story-studio/generate",
                            json={"title": "Il Drago", "prompt": "Una storia epica"},
                            content_type="application/json")
        assert r.status_code == 202
        data = r.get_json()
        assert data["status"] == "started"
        assert "story_id" in data

    def test_get_story_invalid_id(self, client):
        r = client.get("/api/story-studio/story/not-a-valid-uuid")
        assert r.status_code == 400

    def test_get_story_not_found(self, client, tmp_path):
        with patch("core.story_engine.STORY_STUDIO_STORIES_DIR", str(tmp_path)):
            r = client.get("/api/story-studio/story/aaaaaaaa-0000-0000-0000-000000000000")
        assert r.status_code == 404

    def test_delete_story_not_found(self, client, tmp_path):
        with patch("core.story_engine.STORY_STUDIO_STORIES_DIR", str(tmp_path)):
            r = client.delete("/api/story-studio/story/bbbbbbbb-0000-0000-0000-000000000000")
        assert r.status_code == 404

    def test_delete_story_ok(self, client, tmp_path):
        sid = "cccccccc-0000-0000-0000-000000000000"
        d = tmp_path / sid
        d.mkdir()
        meta = {"id": sid, "title": "Test", "status": "completed",
                "output_path": None, "file_path": None}
        (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        with patch("core.story_engine.STORY_STUDIO_STORIES_DIR", str(tmp_path)):
            r = client.delete(f"/api/story-studio/story/{sid}")
        assert r.status_code == 200
        assert r.get_json()["status"] == "deleted"

    def test_get_story_script_not_found(self, client, tmp_path):
        sid = "dddddddd-0000-0000-0000-000000000000"
        d = tmp_path / sid
        d.mkdir()
        meta = {"id": sid, "title": "X"}
        (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        with patch("core.story_engine.STORY_STUDIO_STORIES_DIR", str(tmp_path)):
            r = client.get(f"/api/story-studio/story/{sid}/script")
        assert r.status_code == 404

    def test_get_story_script_ok(self, client, tmp_path):
        sid = "eeeeeeee-0000-0000-0000-000000000000"
        d = tmp_path / sid
        d.mkdir()
        meta = {"id": sid, "title": "Y"}
        (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        (d / "script.json").write_text(json.dumps(SAMPLE_SCRIPT), encoding="utf-8")
        with patch("core.story_engine.STORY_STUDIO_STORIES_DIR", str(tmp_path)):
            r = client.get(f"/api/story-studio/story/{sid}/script")
        assert r.status_code == 200
        assert r.get_json()["title"] == "Il Draghetto Timido"

    def test_audio_endpoint_no_file(self, client, tmp_path):
        sid = "ffffffff-0000-0000-0000-000000000000"
        d = tmp_path / sid
        d.mkdir()
        meta = {"id": sid, "title": "Z", "file_path": "/nonexistent/file.mp3"}
        (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        with patch("core.story_engine.STORY_STUDIO_STORIES_DIR", str(tmp_path)):
            r = client.get(f"/api/story-studio/story/{sid}/audio")
        assert r.status_code == 404

    def test_title_too_long(self, client):
        r = client.post("/api/story-studio/generate",
                        json={"title": "A" * 201, "prompt": "P"},
                        content_type="application/json")
        assert r.status_code == 400

    def test_prompt_too_long(self, client):
        r = client.post("/api/story-studio/generate",
                        json={"title": "T", "prompt": "P" * 2001},
                        content_type="application/json")
        assert r.status_code == 400

    def test_character_name_empty(self, client):
        r = client.post("/api/story-studio/generate",
                        json={"title": "T", "prompt": "P",
                              "characters": [{"name": "", "voice": "nova"}]},
                        content_type="application/json")
        assert r.status_code == 400

    def test_character_name_too_long(self, client):
        r = client.post("/api/story-studio/generate",
                        json={"title": "T", "prompt": "P",
                              "characters": [{"name": "X" * 81, "voice": "nova"}]},
                        content_type="application/json")
        assert r.status_code == 400
