"""
tests/test_offline_generator.py — Test per il generatore automatico di contenuti offline (PR #35).

Copre:
  1) OFFLINE_TEMPLATES contiene tutti i mode necessari
  2) generate_offline_content() crea i file con Piper mockato
  3) generate_offline_content(modes=["spoken_quiz"]) genera solo quiz
  4) generate_offline_content(force=False) salta file esistenti
  5) generate_offline_content(force=True) rigenera tutto
  6) Endpoint POST /api/offline/generate avvia la generazione
  7) Endpoint GET /api/offline/content lista i contenuti
  8) Endpoint DELETE /api/offline/content/spoken_quiz elimina i file
  9) Se Piper non è installato, la generazione fallisce con errore chiaro
 10) I template contengono almeno 4 elementi per ogni mode
 11) list_offline_content() riflette i file presenti su disco
 12) delete_offline_content() elimina i file del mode
 13) Endpoint GET /api/offline/generate/status restituisce lo stato
 14) Endpoint POST /api/offline/generate con mode invalido ritorna 400
 15) Endpoint DELETE /api/offline/content/<mode> con mode invalido ritorna 404
"""

import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def app(tmp_path):
    """Flask app con blueprint offline registrato, OFFLINE_FALLBACK_DIR in tmp."""
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.offline import offline_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-offline-gen-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(offline_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")

    # Patch OFFLINE_FALLBACK_DIR to tmp_path for isolation
    import core.offline_generator as og
    og_orig_dir = og.OFFLINE_FALLBACK_DIR
    og.OFFLINE_FALLBACK_DIR = str(tmp_path)

    import config
    config_orig_dir = config.OFFLINE_FALLBACK_DIR
    config.OFFLINE_FALLBACK_DIR = str(tmp_path)

    yield flask_app

    og.OFFLINE_FALLBACK_DIR = og_orig_dir
    config.OFFLINE_FALLBACK_DIR = config_orig_dir


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c


@pytest.fixture()
def tmp_offline_dir(tmp_path):
    """Restituisce un directory temporanea da usare come OFFLINE_FALLBACK_DIR."""
    import core.offline_generator as og
    orig = og.OFFLINE_FALLBACK_DIR
    og.OFFLINE_FALLBACK_DIR = str(tmp_path)
    yield tmp_path
    og.OFFLINE_FALLBACK_DIR = orig


@pytest.fixture(autouse=True)
def reset_generation_state():
    """Resetta lo stato di generazione prima di ogni test."""
    import core.offline_generator as og
    with og._generation_lock:
        og._generation_state.update({
            "running": False,
            "progress": 0,
            "total": 0,
            "current_mode": "",
            "generated": 0,
            "skipped": 0,
            "errors": [],
        })
    yield
    with og._generation_lock:
        og._generation_state.update({
            "running": False,
            "progress": 0,
            "total": 0,
            "current_mode": "",
            "generated": 0,
            "skipped": 0,
            "errors": [],
        })


# ---------------------------------------------------------------------------
# 1) OFFLINE_TEMPLATES contiene tutti i mode necessari
# ---------------------------------------------------------------------------

class TestOfflineTemplates:
    REQUIRED_MODES = [
        "spoken_quiz", "adventure", "personalized_story", "guess_sound",
        "imitate", "playful_english", "logic_games", "entertainment",
        "school", "ai_chat", "edu_ai",
    ]

    def test_all_required_modes_present(self):
        from core.offline_generator import OFFLINE_TEMPLATES
        for mode in self.REQUIRED_MODES:
            assert mode in OFFLINE_TEMPLATES, f"Mode mancante: {mode}"

    def test_templates_are_lists(self):
        from core.offline_generator import OFFLINE_TEMPLATES
        for mode, templates in OFFLINE_TEMPLATES.items():
            assert isinstance(templates, list), f"{mode} non è una lista"
            assert len(templates) > 0, f"{mode} è vuoto"

    # 10) I template contengono almeno 4 elementi per ogni mode
    def test_minimum_4_templates_per_mode(self):
        from core.offline_generator import OFFLINE_TEMPLATES
        for mode, templates in OFFLINE_TEMPLATES.items():
            assert len(templates) >= 4, (
                f"Mode '{mode}' ha solo {len(templates)} template (minimo: 4)"
            )

    def test_main_modes_have_at_least_8_templates(self):
        from core.offline_generator import OFFLINE_TEMPLATES
        main_modes = [
            "spoken_quiz", "adventure", "personalized_story",
            "guess_sound", "imitate", "playful_english", "logic_games",
        ]
        for mode in main_modes:
            assert len(OFFLINE_TEMPLATES[mode]) >= 8, (
                f"Mode principale '{mode}' ha solo {len(OFFLINE_TEMPLATES[mode])} template (minimo: 8)"
            )

    def test_spoken_quiz_has_15_templates(self):
        from core.offline_generator import OFFLINE_TEMPLATES
        assert len(OFFLINE_TEMPLATES["spoken_quiz"]) >= 15

    def test_templates_are_strings(self):
        from core.offline_generator import OFFLINE_TEMPLATES
        for mode, templates in OFFLINE_TEMPLATES.items():
            for i, t in enumerate(templates):
                assert isinstance(t, str), f"{mode}[{i}] non è una stringa"
                assert len(t.strip()) > 0, f"{mode}[{i}] è una stringa vuota"


# ---------------------------------------------------------------------------
# 2) generate_offline_content() crea i file con Piper mockato
# ---------------------------------------------------------------------------

class TestGenerateOfflineContent:

    def _make_fake_wav(self, tmp_path, name="fake.wav"):
        """Crea un file WAV finto da usare come output di Piper."""
        p = tmp_path / name
        p.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")
        return str(p)

    def test_generates_files_for_all_modes(self, tmp_path, tmp_offline_dir):
        from core.offline_generator import generate_offline_content, OFFLINE_TEMPLATES

        fake_wav = self._make_fake_wav(tmp_path)

        with patch("api.tts.synthesize_with_piper", return_value=fake_wav):
            result = generate_offline_content()

        assert result["generated"] > 0
        assert result["skipped"] == 0
        assert result["errors"] == []
        # Verifica che i file siano stati creati
        for mode in OFFLINE_TEMPLATES:
            mode_dir = tmp_offline_dir / mode
            assert mode_dir.is_dir()

    # 3) generate_offline_content(modes=["spoken_quiz"]) genera solo quiz
    def test_generates_only_specified_mode(self, tmp_path, tmp_offline_dir):
        from core.offline_generator import generate_offline_content, OFFLINE_TEMPLATES

        fake_wav = self._make_fake_wav(tmp_path)

        with patch("api.tts.synthesize_with_piper", return_value=fake_wav):
            result = generate_offline_content(modes=["spoken_quiz"])

        expected = len(OFFLINE_TEMPLATES["spoken_quiz"])
        assert result["generated"] == expected
        assert result["details"]["spoken_quiz"]["generated"] == expected
        # Le altre cartelle non devono esistere
        for mode in OFFLINE_TEMPLATES:
            if mode != "spoken_quiz":
                assert "adventure" not in result["details"] or mode != "adventure"

    # 4) generate_offline_content(force=False) salta file esistenti
    def test_skips_existing_files_when_force_false(self, tmp_path, tmp_offline_dir):
        from core.offline_generator import generate_offline_content

        fake_wav = self._make_fake_wav(tmp_path)

        # Prima generazione
        with patch("api.tts.synthesize_with_piper", return_value=fake_wav):
            result1 = generate_offline_content(modes=["spoken_quiz"], force=False)

        assert result1["generated"] > 0
        assert result1["skipped"] == 0

        # Seconda generazione con force=False → salta tutti
        with patch("api.tts.synthesize_with_piper", return_value=fake_wav) as mock_synth:
            result2 = generate_offline_content(modes=["spoken_quiz"], force=False)

        assert result2["skipped"] == result1["generated"]
        assert result2["generated"] == 0

    # 5) generate_offline_content(force=True) rigenera tutto
    def test_regenerates_when_force_true(self, tmp_path, tmp_offline_dir):
        from core.offline_generator import generate_offline_content, OFFLINE_TEMPLATES

        fake_wav = self._make_fake_wav(tmp_path)

        # Prima generazione
        with patch("api.tts.synthesize_with_piper", return_value=fake_wav):
            result1 = generate_offline_content(modes=["spoken_quiz"], force=False)

        expected = len(OFFLINE_TEMPLATES["spoken_quiz"])
        assert result1["generated"] == expected

        # Seconda generazione con force=True → rigenera tutto
        with patch("api.tts.synthesize_with_piper", return_value=fake_wav):
            result2 = generate_offline_content(modes=["spoken_quiz"], force=True)

        assert result2["generated"] == expected
        assert result2["skipped"] == 0

    # 9) Se Piper non è installato, la generazione fallisce con errore chiaro
    def test_piper_not_installed_logs_error(self, tmp_offline_dir):
        from core.offline_generator import generate_offline_content

        with patch("api.tts.synthesize_with_piper",
                   side_effect=RuntimeError("Piper non installato o non trovato in PATH")):
            result = generate_offline_content(modes=["spoken_quiz"])

        assert result["generated"] == 0
        assert len(result["errors"]) > 0
        # Tutti gli errori devono menzionare il problema
        assert any("Piper" in e or "spoken_quiz" in e for e in result["errors"])

    def test_naming_convention(self, tmp_path, tmp_offline_dir):
        """I file devono rispettare la convenzione {mode}_{nn:02d}.wav."""
        from core.offline_generator import generate_offline_content

        fake_wav = self._make_fake_wav(tmp_path)

        with patch("api.tts.synthesize_with_piper", return_value=fake_wav):
            generate_offline_content(modes=["adventure"])

        mode_dir = tmp_offline_dir / "adventure"
        files = sorted(os.listdir(str(mode_dir)))
        assert len(files) > 0
        for fname in files:
            assert fname.startswith("adventure_")
            assert fname.endswith(".wav")
            # Verifica il numero a 2 cifre (es. adventure_01.wav)
            num_part = fname[len("adventure_"):-len(".wav")]
            assert num_part.isdigit() and len(num_part) == 2

    def test_files_saved_in_correct_subdir(self, tmp_path, tmp_offline_dir):
        """I file devono essere in OFFLINE_FALLBACK_DIR/{mode}/."""
        from core.offline_generator import generate_offline_content

        fake_wav = self._make_fake_wav(tmp_path)

        with patch("api.tts.synthesize_with_piper", return_value=fake_wav):
            generate_offline_content(modes=["guess_sound"])

        mode_dir = tmp_offline_dir / "guess_sound"
        assert mode_dir.is_dir()
        assert len(list(mode_dir.iterdir())) > 0


# ---------------------------------------------------------------------------
# 11) list_offline_content() riflette i file presenti su disco
# ---------------------------------------------------------------------------

class TestListOfflineContent:

    def test_empty_when_no_files(self, tmp_offline_dir):
        from core.offline_generator import list_offline_content
        result = list_offline_content()
        for mode, info in result.items():
            assert info["count"] == 0
            assert info["files"] == []

    def test_counts_existing_files(self, tmp_offline_dir):
        from core.offline_generator import list_offline_content

        # Crea dei file finti
        mode_dir = tmp_offline_dir / "spoken_quiz"
        mode_dir.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            (mode_dir / f"spoken_quiz_{i+1:02d}.wav").write_bytes(b"fake")

        result = list_offline_content()
        assert result["spoken_quiz"]["count"] == 3
        assert len(result["spoken_quiz"]["files"]) == 3

    def test_lists_all_modes(self, tmp_offline_dir):
        from core.offline_generator import list_offline_content, OFFLINE_TEMPLATES
        result = list_offline_content()
        for mode in OFFLINE_TEMPLATES:
            assert mode in result


# ---------------------------------------------------------------------------
# 12) delete_offline_content() elimina i file del mode
# ---------------------------------------------------------------------------

class TestDeleteOfflineContent:

    def test_deletes_wav_files(self, tmp_offline_dir):
        from core.offline_generator import delete_offline_content

        mode_dir = tmp_offline_dir / "adventure"
        mode_dir.mkdir(parents=True, exist_ok=True)
        for i in range(4):
            (mode_dir / f"adventure_{i+1:02d}.wav").write_bytes(b"fake")

        result = delete_offline_content("adventure")
        assert result["deleted"] == 4
        assert result["mode"] == "adventure"
        remaining = list(mode_dir.iterdir())
        assert len(remaining) == 0

    def test_raises_on_invalid_mode(self, tmp_offline_dir):
        from core.offline_generator import delete_offline_content
        with pytest.raises(ValueError, match="Mode non valido"):
            delete_offline_content("invalid_mode_xyz")

    def test_zero_deleted_when_empty(self, tmp_offline_dir):
        from core.offline_generator import delete_offline_content
        result = delete_offline_content("adventure")
        assert result["deleted"] == 0


# ---------------------------------------------------------------------------
# 6) Endpoint POST /api/offline/generate avvia la generazione
# ---------------------------------------------------------------------------

class TestApiOfflineGenerate:

    def test_post_starts_generation(self, client):
        with patch("core.offline_generator.generate_offline_content") as mock_gen:
            mock_gen.return_value = {"generated": 5, "skipped": 0, "errors": [], "details": {}}
            resp = client.post(
                "/api/offline/generate",
                json={},
                content_type="application/json",
            )
        assert resp.status_code == 202
        data = resp.get_json()
        assert data["status"] == "started"

    def test_post_with_specific_modes(self, client):
        with patch("core.offline_generator.generate_offline_content") as mock_gen:
            mock_gen.return_value = {"generated": 2, "skipped": 0, "errors": [], "details": {}}
            resp = client.post(
                "/api/offline/generate",
                json={"modes": ["spoken_quiz"]},
                content_type="application/json",
            )
        assert resp.status_code == 202

    # 14) Endpoint POST /api/offline/generate con mode invalido ritorna 400
    def test_post_invalid_mode_returns_400(self, client):
        resp = client.post(
            "/api/offline/generate",
            json={"modes": ["invalid_mode_xyz"]},
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    def test_post_modes_not_list_returns_400(self, client):
        resp = client.post(
            "/api/offline/generate",
            json={"modes": "spoken_quiz"},
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_post_returns_409_when_already_running(self, client):
        import core.offline_generator as og
        with og._generation_lock:
            og._generation_state["running"] = True
        try:
            resp = client.post(
                "/api/offline/generate",
                json={},
                content_type="application/json",
            )
            assert resp.status_code == 409
        finally:
            with og._generation_lock:
                og._generation_state["running"] = False


# ---------------------------------------------------------------------------
# 7) Endpoint GET /api/offline/content lista i contenuti
# ---------------------------------------------------------------------------

class TestApiOfflineContent:

    def test_get_returns_all_modes(self, client, tmp_offline_dir):
        from core.offline_generator import OFFLINE_TEMPLATES
        resp = client.get("/api/offline/content")
        assert resp.status_code == 200
        data = resp.get_json()
        for mode in OFFLINE_TEMPLATES:
            assert mode in data

    def test_get_returns_count_and_files(self, client, tmp_offline_dir):
        # Crea un file finto
        mode_dir = tmp_offline_dir / "spoken_quiz"
        mode_dir.mkdir(parents=True, exist_ok=True)
        (mode_dir / "spoken_quiz_01.wav").write_bytes(b"fake")

        resp = client.get("/api/offline/content")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["spoken_quiz"]["count"] == 1
        assert "spoken_quiz_01.wav" in data["spoken_quiz"]["files"]


# ---------------------------------------------------------------------------
# 8) Endpoint DELETE /api/offline/content/spoken_quiz elimina i file
# ---------------------------------------------------------------------------

class TestApiOfflineContentDelete:

    def test_delete_removes_files(self, client, tmp_offline_dir):
        mode_dir = tmp_offline_dir / "spoken_quiz"
        mode_dir.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            (mode_dir / f"spoken_quiz_{i+1:02d}.wav").write_bytes(b"fake")

        resp = client.delete("/api/offline/content/spoken_quiz")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["deleted"] == 3
        assert data["mode"] == "spoken_quiz"

    # 15) Endpoint DELETE /api/offline/content/<mode> con mode invalido ritorna 404
    def test_delete_invalid_mode_returns_404(self, client):
        resp = client.delete("/api/offline/content/invalid_mode_xyz")
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data


# ---------------------------------------------------------------------------
# 13) Endpoint GET /api/offline/generate/status
# ---------------------------------------------------------------------------

class TestApiOfflineGenerateStatus:

    def test_get_status_when_idle(self, client):
        resp = client.get("/api/offline/generate/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["running"] is False
        assert "progress" in data
        assert "total" in data
        assert "current_mode" in data

    def test_get_status_fields(self, client):
        resp = client.get("/api/offline/generate/status")
        data = resp.get_json()
        for field in ["running", "progress", "total", "current_mode", "generated", "skipped", "errors"]:
            assert field in data, f"Campo mancante: {field}"
