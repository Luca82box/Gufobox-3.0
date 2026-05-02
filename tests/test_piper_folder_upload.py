"""
tests/test_piper_folder_upload.py — Tests for POST /api/tts/offline/upload-asset

Covers:
A) Single file to "voices" target dir
B) Single file to "bin" target dir (made executable)
C) Multiple files uploaded at once (folder-mode)
D) Rejects unknown target_dir
E) Handles missing files gracefully
F) Sanitises filenames to prevent path traversal
G) Returns correct result counts (uploaded / total)
H) Refreshes PIPER_EXECUTABLE after bin upload containing "piper"
"""

import io
import os
import stat
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def piper_env(tmp_path, monkeypatch):
    """Override Piper dirs with temporary directories."""
    import config as cfg
    import api.tts as tts_module

    voices_dir = str(tmp_path / "piper_voices")
    bin_dir = str(tmp_path / "piper_bin")
    local_bin = str(tmp_path / "piper_bin" / "piper")
    os.makedirs(voices_dir, exist_ok=True)
    os.makedirs(bin_dir, exist_ok=True)

    monkeypatch.setattr(cfg, "PIPER_VOICES_DIR", voices_dir)
    monkeypatch.setattr(cfg, "PIPER_LOCAL_BIN_DIR", bin_dir)
    monkeypatch.setattr(cfg, "PIPER_LOCAL_BIN", local_bin)
    monkeypatch.setattr(tts_module, "PIPER_VOICES_DIR", voices_dir)
    monkeypatch.setattr(tts_module, "PIPER_LOCAL_BIN_DIR", bin_dir)
    monkeypatch.setattr(tts_module, "PIPER_LOCAL_BIN", local_bin)

    return {"voices_dir": voices_dir, "bin_dir": bin_dir, "local_bin": local_bin}


@pytest.fixture()
def app(piper_env):
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.auth import auth_bp
    from api.tts import tts_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-asset-upload-secret"
    flask_app.config["TESTING"] = True
    flask_app.config["SESSION_COOKIE_SECURE"] = False
    CORS(flask_app, supports_credentials=True)
    flask_app.register_blueprint(auth_bp, url_prefix="/api")
    flask_app.register_blueprint(tts_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def client(app):
    with app.test_client() as c:
        yield c


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _file_field(filename, content=b"fake-binary-data"):
    return (io.BytesIO(content), filename)


def _post_assets(client, files, target_dir="voices"):
    """Upload one or more files via the upload-asset endpoint."""
    data = {"target_dir": target_dir}
    if isinstance(files, list):
        # Multiple files under the same field name
        data["files[]"] = files
    else:
        data["files[]"] = [files]
    return client.post(
        "/api/tts/offline/upload-asset",
        data=data,
        content_type="multipart/form-data",
    )


# ─── A) Single file to voices dir ─────────────────────────────────────────────

def test_upload_asset_single_voice_file(client, piper_env):
    rv = _post_assets(client, _file_field("it_IT-paola-medium.onnx", b"fake-model"), "voices")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["status"] == "ok"
    assert body["uploaded"] == 1
    dest = os.path.join(piper_env["voices_dir"], "it_IT-paola-medium.onnx")
    assert os.path.isfile(dest)


def test_upload_asset_voice_config_file(client, piper_env):
    rv = _post_assets(client, _file_field("it_IT-paola-medium.onnx.json", b"{}"), "voices")
    assert rv.status_code == 200
    assert rv.get_json()["uploaded"] == 1
    dest = os.path.join(piper_env["voices_dir"], "it_IT-paola-medium.onnx.json")
    assert os.path.isfile(dest)


# ─── B) Single file to bin dir (made executable) ──────────────────────────────

def test_upload_asset_binary_is_executable(client, piper_env):
    rv = _post_assets(client, _file_field("piper", b"\x7fELF"), "bin")
    assert rv.status_code == 200
    assert rv.get_json()["uploaded"] == 1
    dest = os.path.join(piper_env["bin_dir"], "piper")
    assert os.path.isfile(dest)
    file_mode = os.stat(dest).st_mode
    assert file_mode & stat.S_IXUSR, "Binary must be executable by owner"
    assert file_mode & stat.S_IXGRP, "Binary must be executable by group"
    assert file_mode & stat.S_IXOTH, "Binary must be executable by others"


def test_upload_asset_shared_lib_is_executable(client, piper_env):
    rv = _post_assets(client, _file_field("libonnxruntime.so", b"\x7fELF"), "bin")
    assert rv.status_code == 200
    dest = os.path.join(piper_env["bin_dir"], "libonnxruntime.so")
    assert os.path.isfile(dest)
    assert os.stat(dest).st_mode & stat.S_IXUSR


# ─── C) Multiple files (folder mode) ──────────────────────────────────────────

def test_upload_asset_multiple_files_bin(client, piper_env):
    files = [
        _file_field("piper", b"\x7fELF-piper"),
        _file_field("libonnxruntime.so", b"\x7fELF-ort"),
        _file_field("libpiper_phonemize.so.1.2.0", b"\x7fELF-phonemize"),
    ]
    rv = _post_assets(client, files, "bin")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["uploaded"] == 3
    assert body["total"] == 3
    for fname in ("piper", "libonnxruntime.so", "libpiper_phonemize.so.1.2.0"):
        assert os.path.isfile(os.path.join(piper_env["bin_dir"], fname))


def test_upload_asset_multiple_voice_files(client, piper_env):
    files = [
        _file_field("it_IT-paola-medium.onnx", b"onnx-model"),
        _file_field("it_IT-paola-medium.onnx.json", b"{}"),
    ]
    rv = _post_assets(client, files, "voices")
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["uploaded"] == 2
    assert "it_IT-paola-medium" in body["voices"]


# ─── D) Rejects unknown target_dir ────────────────────────────────────────────

def test_upload_asset_rejects_unknown_target(client):
    rv = _post_assets(client, _file_field("piper"), "../../etc")
    assert rv.status_code == 400
    assert "target_dir" in rv.get_json()["error"].lower()


def test_upload_asset_rejects_tmp_target(client):
    rv = _post_assets(client, _file_field("piper"), "/tmp")
    assert rv.status_code == 400


# ─── E) Missing files ─────────────────────────────────────────────────────────

def test_upload_asset_no_files_returns_400(client):
    rv = client.post(
        "/api/tts/offline/upload-asset",
        data={"target_dir": "voices"},
        content_type="multipart/form-data",
    )
    assert rv.status_code == 400


# ─── F) Path traversal sanitisation ───────────────────────────────────────────

def test_upload_asset_path_traversal_sanitised(client, piper_env):
    rv = _post_assets(client, _file_field("../../evil.onnx"), "voices")
    # Either sanitised (200) or rejected (400) — must never write outside voices_dir
    if rv.status_code == 200:
        body = rv.get_json()
        for result in body["results"]:
            fname = result["file"]
            assert ".." not in fname
            assert "/" not in fname
            assert "\\" not in fname
            dest = os.path.join(piper_env["voices_dir"], fname)
            assert os.path.isfile(dest)
    else:
        assert rv.status_code in (400, 422)


# ─── G) Result counts ─────────────────────────────────────────────────────────

def test_upload_asset_results_contain_file_names(client, piper_env):
    files = [
        _file_field("it_IT-paola-medium.onnx", b"onnx"),
        _file_field("it_IT-paola-medium.onnx.json", b"{}"),
    ]
    rv = _post_assets(client, files, "voices")
    assert rv.status_code == 200
    body = rv.get_json()
    names = [r["file"] for r in body["results"]]
    assert "it_IT-paola-medium.onnx" in names
    assert "it_IT-paola-medium.onnx.json" in names


# ─── H) PIPER_EXECUTABLE refreshed after bin upload ──────────────────────────

def test_upload_asset_refreshes_piper_executable(client, piper_env):
    import config as cfg
    rv = _post_assets(client, _file_field("piper", b"\x7fELF"), "bin")
    assert rv.status_code == 200
    # After uploading a file named "piper" to the bin dir, PIPER_EXECUTABLE must
    # point to the local binary path (PIPER_LOCAL_BIN)
    assert cfg.PIPER_EXECUTABLE == piper_env["local_bin"]
