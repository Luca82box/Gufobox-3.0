"""
tests/test_tts_piper_download.py — Piper binary and voice model auto-download endpoints.

Covers:
A) GET /tts/offline/suggested-voices
   - returns list with name, onnx_url, config_url, description
   - all suggested voices are Italian (it_IT)

B) POST /tts/offline/download-binary
   - rejects disallowed URL scheme (ftp://)
   - rejects disallowed host (not github.com or objects.githubusercontent.com)
   - returns 400 when URL is valid but network error (mocked)
   - uses default URL when no url field in payload

C) POST /tts/offline/download-voice
   - rejects unknown suggested voice name
   - rejects missing onnx_url and config_url (without name)
   - rejects bad filename in onnx_url (path traversal in URL filename)
   - rejects disallowed host for custom URL
   - successfully downloads and saves two mock voice files (mocked HTTP)
   - returns updated voices list after success
"""

import io
import os
import sys
import tarfile
import tempfile
import threading
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def tts_env(tmp_path):
    """Sets up a temporary Piper directory env and returns (voices_dir, bin_dir)."""
    import config as cfg

    voices_dir = str(tmp_path / "piper_voices")
    bin_dir = str(tmp_path / "piper_bin")
    os.makedirs(voices_dir, exist_ok=True)
    os.makedirs(bin_dir, exist_ok=True)

    orig_voices = cfg.PIPER_VOICES_DIR
    orig_bin_dir = cfg.PIPER_LOCAL_BIN_DIR
    orig_bin = cfg.PIPER_LOCAL_BIN
    orig_exe = cfg.PIPER_EXECUTABLE

    cfg.PIPER_VOICES_DIR = voices_dir
    cfg.PIPER_LOCAL_BIN_DIR = bin_dir
    cfg.PIPER_LOCAL_BIN = str(tmp_path / "piper_bin" / "piper")
    cfg.PIPER_EXECUTABLE = "piper"

    yield voices_dir, bin_dir

    cfg.PIPER_VOICES_DIR = orig_voices
    cfg.PIPER_LOCAL_BIN_DIR = orig_bin_dir
    cfg.PIPER_LOCAL_BIN = orig_bin
    cfg.PIPER_EXECUTABLE = orig_exe


@pytest.fixture()
def tts_app(tts_env):
    """Minimal Flask app with tts_bp registered."""
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.tts import tts_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret-tts"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(tts_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def client(tts_app):
    with tts_app.test_client() as c:
        yield c


# ─── A) Suggested voices ──────────────────────────────────────────────────────

class TestSuggestedVoices:
    def test_returns_list(self, client):
        rv = client.get("/api/tts/offline/suggested-voices")
        assert rv.status_code == 200
        data = rv.get_json()
        assert "voices" in data
        assert isinstance(data["voices"], list)
        assert len(data["voices"]) > 0

    def test_voice_has_required_fields(self, client):
        rv = client.get("/api/tts/offline/suggested-voices")
        voices = rv.get_json()["voices"]
        for v in voices:
            assert "name" in v
            assert "onnx_url" in v
            assert "config_url" in v
            assert "description" in v

    def test_all_voices_are_italian(self, client):
        rv = client.get("/api/tts/offline/suggested-voices")
        voices = rv.get_json()["voices"]
        for v in voices:
            assert v["name"].startswith("it_IT"), (
                f"Expected Italian voice name (it_IT prefix), got: {v['name']}"
            )

    def test_onnx_url_ends_with_onnx(self, client):
        rv = client.get("/api/tts/offline/suggested-voices")
        voices = rv.get_json()["voices"]
        for v in voices:
            assert v["onnx_url"].endswith(".onnx")
            assert v["config_url"].endswith(".onnx.json")


# ─── B) Download binary ────────────────────────────────────────────────────────

class TestDownloadBinary:
    def test_rejects_ftp_scheme(self, client):
        rv = client.post("/api/tts/offline/download-binary", json={
            "url": "ftp://github.com/rhasspy/piper/releases/download/v1/piper.tar.gz"
        })
        assert rv.status_code == 400
        assert "non valido" in rv.get_json()["error"].lower() or "non autorizzato" in rv.get_json()["error"].lower()

    def test_rejects_disallowed_host(self, client):
        rv = client.post("/api/tts/offline/download-binary", json={
            "url": "https://evil.example.com/piper.tar.gz"
        })
        assert rv.status_code == 400
        assert rv.get_json()["error"]

    def test_rejects_localhost_host(self, client):
        rv = client.post("/api/tts/offline/download-binary", json={
            "url": "https://localhost/piper.tar.gz"
        })
        assert rv.status_code == 400

    def test_network_error_returns_502(self, client):
        """A real network error while downloading returns 502."""
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("simulated network error")):
            rv = client.post("/api/tts/offline/download-binary", json={
                "url": "https://github.com/rhasspy/piper/releases/download/v1/piper_linux_aarch64.tar.gz"
            })
        assert rv.status_code == 502

    def test_success_installs_binary(self, client, tts_env):
        """A successful download saves the piper binary and returns ok."""
        import config as cfg

        # Build a minimal tar.gz containing a 'piper/piper' entry
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            content = b"#!/bin/sh\necho piper 1.0"
            info = tarfile.TarInfo(name="piper/piper")
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
        buf.seek(0)
        tar_bytes = buf.read()

        mock_response = MagicMock()
        mock_response.read.side_effect = [tar_bytes, b""]
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            rv = client.post("/api/tts/offline/download-binary", json={
                "url": "https://github.com/rhasspy/piper/releases/download/v1/piper_linux_aarch64.tar.gz"
            })

        assert rv.status_code == 200, rv.get_json()
        data = rv.get_json()
        assert data["status"] == "ok"
        assert os.path.isfile(cfg.PIPER_LOCAL_BIN), "Binary should be saved to PIPER_LOCAL_BIN"
        # Check executable bit
        mode = os.stat(cfg.PIPER_LOCAL_BIN).st_mode
        assert mode & 0o111, "Binary should have executable permission"

    def test_tar_without_piper_returns_422(self, client):
        """A tar.gz that does not contain a 'piper' binary returns 422."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            content = b"some random file content"
            info = tarfile.TarInfo(name="readme.txt")
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
        buf.seek(0)
        tar_bytes = buf.read()

        mock_response = MagicMock()
        mock_response.read.side_effect = [tar_bytes, b""]
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            rv = client.post("/api/tts/offline/download-binary", json={
                "url": "https://github.com/rhasspy/piper/releases/download/v1/piper_linux_aarch64.tar.gz"
            })

        assert rv.status_code == 422
        assert "piper" in rv.get_json()["error"].lower()

    def test_success_extracts_shared_libs(self, client, tts_env):
        """Full archive extraction: shared libraries are saved alongside the binary."""
        import config as cfg

        # Build a tar.gz that mimics the real piper release structure:
        # piper/piper, piper/libonnxruntime.so.1.14.1, piper/espeak-ng-data/...
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for name, content in [
                ("piper/piper", b"#!/bin/sh\necho piper 1.0"),
                ("piper/libonnxruntime.so.1.14.1", b"\x7fELF fake shared lib"),
                ("piper/libpiper_phonemize.so.1", b"\x7fELF fake phonemize"),
            ]:
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                tf.addfile(info, io.BytesIO(content))
            # Add a directory entry for espeak-ng-data
            dir_info = tarfile.TarInfo(name="piper/espeak-ng-data")
            dir_info.type = tarfile.DIRTYPE
            tf.addfile(dir_info)
        buf.seek(0)
        tar_bytes = buf.read()

        mock_response = MagicMock()
        mock_response.read.side_effect = [tar_bytes, b""]
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            rv = client.post("/api/tts/offline/download-binary", json={
                "url": "https://github.com/rhasspy/piper/releases/download/v1/piper_linux_aarch64.tar.gz"
            })

        assert rv.status_code == 200, rv.get_json()
        data = rv.get_json()
        assert data["status"] == "ok"

        bin_dir = cfg.PIPER_LOCAL_BIN_DIR
        # The piper binary must be present
        assert os.path.isfile(cfg.PIPER_LOCAL_BIN), "piper binary must be present"
        # Shared libraries must be extracted too
        assert os.path.isfile(os.path.join(bin_dir, "libonnxruntime.so.1.14.1")), \
            "libonnxruntime shared lib must be extracted"
        assert os.path.isfile(os.path.join(bin_dir, "libpiper_phonemize.so.1")), \
            "libpiper_phonemize shared lib must be extracted"
        # espeak-ng-data directory must be present
        assert os.path.isdir(os.path.join(bin_dir, "espeak-ng-data")), \
            "espeak-ng-data directory must be extracted"

    def test_status_endpoint_diagnosi_when_not_installed(self, client, tts_env):
        """Status endpoint includes a 'diagnosi' field when piper is not installed."""
        import config as cfg
        # Ensure piper binary does not exist
        if os.path.isfile(cfg.PIPER_LOCAL_BIN):
            os.remove(cfg.PIPER_LOCAL_BIN)
        rv = client.get("/api/tts/offline/status")
        assert rv.status_code == 200
        data = rv.get_json()
        assert "piper_available" in data
        # When piper is not installed, a diagnosi hint should be returned
        if not data["piper_available"]:
            assert "diagnosi" in data
            assert len(data["diagnosi"]) > 10



class TestDownloadVoice:
    def test_rejects_unknown_suggested_name(self, client):
        rv = client.post("/api/tts/offline/download-voice", json={"name": "it_IT-nonexistent-voice"})
        assert rv.status_code == 404
        assert "trovata" in rv.get_json()["error"]

    def test_rejects_missing_urls_and_no_name(self, client):
        rv = client.post("/api/tts/offline/download-voice", json={})
        assert rv.status_code == 400

    def test_rejects_path_traversal_in_onnx_url_filename(self, client):
        rv = client.post("/api/tts/offline/download-voice", json={
            "onnx_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/../../../etc/passwd",
            "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/it_IT-paola-medium.onnx.json"
        })
        assert rv.status_code == 400

    def test_rejects_disallowed_host_for_onnx(self, client):
        rv = client.post("/api/tts/offline/download-voice", json={
            "onnx_url": "https://evil.example.com/it_IT-paola-medium.onnx",
            "config_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/it_IT-paola-medium.onnx.json"
        })
        assert rv.status_code == 400
        assert rv.get_json()["error"]

    def test_success_by_suggested_name(self, client, tts_env):
        """Download by suggested voice name downloads both .onnx and .onnx.json files."""
        import config as cfg

        fake_onnx = b"\x00\x01\x02\x03" * 16     # dummy onnx bytes
        fake_json = b'{"language": {"code": "it"}}'

        call_count = [0]

        def mock_urlopen(req, **kwargs):
            idx = call_count[0]
            call_count[0] += 1
            content = fake_onnx if idx == 0 else fake_json
            mock_resp = MagicMock()
            mock_resp.read.side_effect = [content, b""]
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            rv = client.post("/api/tts/offline/download-voice", json={"name": "it_IT-paola-medium"})

        assert rv.status_code == 200, rv.get_json()
        data = rv.get_json()
        assert data["status"] == "ok"
        assert len(data["files"]) == 2
        assert all(f["ok"] for f in data["files"])

        # Both files should exist in PIPER_VOICES_DIR
        voices_dir = cfg.PIPER_VOICES_DIR
        assert os.path.isfile(os.path.join(voices_dir, "it_IT-paola-medium.onnx"))
        assert os.path.isfile(os.path.join(voices_dir, "it_IT-paola-medium.onnx.json"))

    def test_network_error_returns_502(self, client):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("simulated")):
            rv = client.post("/api/tts/offline/download-voice", json={"name": "it_IT-paola-medium"})
        assert rv.status_code == 502
