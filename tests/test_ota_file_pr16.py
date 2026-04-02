"""
tests/test_ota_file_pr16.py — PR 16: OTA from file (upload, validate, apply).

Covers:
A) Upload endpoint — POST /system/ota/upload
   - Valid .zip upload succeeds and updates ota_state
   - Valid .tar.gz upload succeeds
   - Rejects missing file field
   - Rejects disallowed extensions (.exe, .py, .sh, .tar)
   - Rejects oversized file (> OTA_MAX_PACKAGE_BYTES)
   - Logs upload event (ok and fail)

B) Apply endpoint — POST /system/ota/apply_uploaded
   - Returns 404 if no staged file present
   - Returns 409 if OTA lock is held (concurrent apply)

C) Package validation — _validate_archive()
   - Valid zip with required file passes
   - Invalid zip (bad magic bytes) is rejected
   - Archive missing required file is rejected
   - Archive with path traversal member is rejected
   - Archive with absolute-path member is rejected
   - Zip with nested top-level dir (common packaging) passes

D) Apply flow — _run_ota_file() (mocked backup + copy)
   - Successful apply updates ota_state to 'success'
   - Failed backup aborts and sets 'failed'
   - Invalid package aborts and sets 'failed' with error message
   - Apply logs events (start, success, failure)

E) OTA state shape
   - _OTA_STATE_DEFAULT includes staged_filename and staged_at
   - _load_ota_state backfills missing keys from default
"""

import io
import json
import os
import sys
import tarfile
import tempfile
import zipfile
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def ota_app():
    """Minimal Flask app with system_bp registered."""
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.system import system_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-ota-file-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    flask_app.register_blueprint(system_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def client(ota_app):
    with ota_app.test_client() as c:
        yield c


@pytest.fixture()
def staging_dir(tmp_path):
    """Override OTA_STAGING_DIR to a temp directory for isolation."""
    d = tmp_path / "ota_staging"
    d.mkdir()
    with patch("api.system.OTA_STAGING_DIR", str(d)):
        yield str(d)


@pytest.fixture()
def state_file(tmp_path):
    """Override OTA_STATE_FILE to a temp file for isolation."""
    f = tmp_path / "ota_state.json"
    with patch("api.system.OTA_STATE_FILE", str(f)):
        yield str(f)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_valid_zip(extra_files=None):
    """Return bytes of a valid .zip containing main.py (required)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("main.py", "# GufoBox entry point\n")
        zf.writestr("requirements.txt", "flask\n")
        if extra_files:
            for name, content in extra_files.items():
                zf.writestr(name, content)
    return buf.getvalue()


def _make_valid_targz(extra_files=None):
    """Return bytes of a valid .tar.gz containing main.py."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in ({"main.py": b"# entry\n", **(extra_files or {})}).items():
            data = content if isinstance(content, bytes) else content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _upload_zip(client, data=None, filename="update.zip", content_type="application/zip"):
    """POST /api/system/ota/upload with a zip payload."""
    payload = data or _make_valid_zip()
    return client.post(
        "/api/system/ota/upload",
        data={"file": (io.BytesIO(payload), filename)},
        content_type="multipart/form-data",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# A) Upload endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestOtaUpload:

    def test_valid_zip_upload_returns_200(self, client, staging_dir, state_file):
        resp = _upload_zip(client)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "uploaded"
        assert body["filename"] == "update.zip"
        assert body["ext"] == ".zip"
        assert body["size_bytes"] > 0

    def test_valid_zip_creates_staged_file(self, client, staging_dir, state_file):
        _upload_zip(client)
        staged = os.path.join(staging_dir, "staged_package.zip")
        assert os.path.isfile(staged)

    def test_valid_zip_updates_ota_state(self, client, staging_dir, state_file):
        _upload_zip(client)
        with open(state_file) as f:
            state = json.load(f)
        assert state["status"] == "uploaded"
        assert state["staged_filename"] == "update.zip"
        assert state["staged_at"] is not None
        assert state["mode"] == "file"

    def test_valid_targz_upload(self, client, staging_dir, state_file):
        data = _make_valid_targz()
        resp = client.post(
            "/api/system/ota/upload",
            data={"file": (io.BytesIO(data), "update.tar.gz")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ext"] == ".tar.gz"
        staged = os.path.join(staging_dir, "staged_package.tar.gz")
        assert os.path.isfile(staged)

    def test_missing_file_field_returns_400(self, client, staging_dir, state_file):
        resp = client.post("/api/system/ota/upload", data={}, content_type="multipart/form-data")
        assert resp.status_code == 400
        assert "file" in resp.get_json()["error"].lower()

    @pytest.mark.parametrize("bad_name", [
        "malware.exe",
        "script.sh",
        "update.py",
        "archive.tar",
        "package.gz",
    ])
    def test_disallowed_extensions_rejected(self, client, staging_dir, state_file, bad_name):
        resp = client.post(
            "/api/system/ota/upload",
            data={"file": (io.BytesIO(b"dummy"), bad_name)},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        err = resp.get_json()["error"].lower()
        assert "estensione" in err or "non consentita" in err

    def test_oversized_file_rejected(self, client, staging_dir, state_file):
        with patch("api.system.OTA_MAX_PACKAGE_BYTES", 10):
            resp = client.post(
                "/api/system/ota/upload",
                data={"file": (io.BytesIO(b"x" * 12), "big.zip")},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 413
        err = resp.get_json()["error"].lower()
        assert "troppo grande" in err or "grande" in err

    def test_upload_logs_event(self, client, staging_dir, state_file):
        with patch("api.system.log_event") as mock_log:
            _upload_zip(client)
            calls = [str(c) for c in mock_log.call_args_list]
            assert any("caricato" in c.lower() or "upload" in c.lower() for c in calls)

    def test_invalid_extension_logs_warning(self, client, staging_dir, state_file):
        with patch("api.system.log_event") as mock_log:
            client.post(
                "/api/system/ota/upload",
                data={"file": (io.BytesIO(b"bad"), "evil.exe")},
                content_type="multipart/form-data",
            )
            warning_calls = [
                c for c in mock_log.call_args_list
                if "warning" in str(c)
            ]
            assert len(warning_calls) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# B) Apply endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestOtaApplyUploaded:

    def test_no_staged_file_returns_404(self, client, staging_dir, state_file):
        resp = client.post("/api/system/ota/apply_uploaded")
        # No staged file in empty staging_dir → 400 (no staged_filename) or 404
        assert resp.status_code in (400, 404)

    def test_apply_returns_409_when_lock_held(self, client, staging_dir, state_file):
        import api.system as sys_mod
        # First upload a valid package so there's something to apply
        _upload_zip(client)
        # Acquire the lock manually
        acquired = sys_mod._ota_lock.acquire(blocking=False)
        assert acquired, "Lock should be free before test"
        try:
            resp = client.post("/api/system/ota/apply_uploaded")
            assert resp.status_code == 409
            assert "già in corso" in resp.get_json()["error"].lower()
        finally:
            sys_mod._ota_lock.release()

    def test_apply_started_with_valid_staged_file(self, client, staging_dir, state_file):
        # Upload a valid zip first
        _upload_zip(client)
        # Patch _run_ota_file to avoid actual apply
        with patch("api.system._run_ota_file") as mock_run:
            resp = client.post("/api/system/ota/apply_uploaded")
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["status"] == "started"
            assert body["filename"] == "update.zip"


# ═══════════════════════════════════════════════════════════════════════════════
# C) Package validation — _validate_archive()
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidateArchive:

    def _write_zip(self, tmp_path, members):
        """Write a zip to tmp_path/pkg.zip with given members dict {name: content}."""
        p = str(tmp_path / "pkg.zip")
        with zipfile.ZipFile(p, "w") as zf:
            for name, content in members.items():
                zf.writestr(name, content)
        return p

    def _write_targz(self, tmp_path, members):
        """Write a tar.gz to tmp_path/pkg.tar.gz."""
        p = str(tmp_path / "pkg.tar.gz")
        with tarfile.open(p, "w:gz") as tf:
            for name, content in members.items():
                data = content if isinstance(content, bytes) else content.encode()
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
        return p

    def test_valid_zip_passes(self, tmp_path):
        from api.system import _validate_archive
        p = self._write_zip(tmp_path, {"main.py": "# ok", "requirements.txt": "flask"})
        ok, err = _validate_archive(p, ".zip")
        assert ok is True
        assert err is None

    def test_valid_targz_passes(self, tmp_path):
        from api.system import _validate_archive
        p = self._write_targz(tmp_path, {"main.py": "# ok"})
        ok, err = _validate_archive(p, ".tar.gz")
        assert ok is True
        assert err is None

    def test_zip_with_nested_prefix_passes(self, tmp_path):
        """Common packaging style: gufobox-2.0/main.py should pass."""
        from api.system import _validate_archive
        p = self._write_zip(tmp_path, {
            "gufobox-2.0/main.py": "# ok",
            "gufobox-2.0/requirements.txt": "flask",
        })
        ok, err = _validate_archive(p, ".zip")
        assert ok is True, f"Expected ok, got err: {err}"

    def test_missing_required_file_rejected(self, tmp_path):
        from api.system import _validate_archive
        p = self._write_zip(tmp_path, {"README.md": "hi", "config.py": "x=1"})
        ok, err = _validate_archive(p, ".zip")
        assert ok is False
        assert "main.py" in err

    def test_path_traversal_in_zip_rejected(self, tmp_path):
        from api.system import _validate_archive
        p = str(tmp_path / "evil.zip")
        with zipfile.ZipFile(p, "w") as zf:
            # Path traversal entry
            zf.writestr("../etc/passwd", "root:x:0:0")
            zf.writestr("main.py", "# ok")
        ok, err = _validate_archive(p, ".zip")
        assert ok is False
        assert "traversal" in err.lower() or ".." in err

    def test_absolute_path_in_targz_rejected(self, tmp_path):
        from api.system import _validate_archive
        p = str(tmp_path / "evil.tar.gz")
        with tarfile.open(p, "w:gz") as tf:
            data = b"evil"
            info = tarfile.TarInfo(name="/etc/passwd")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
            data2 = b"# ok"
            info2 = tarfile.TarInfo(name="main.py")
            info2.size = len(data2)
            tf.addfile(info2, io.BytesIO(data2))
        ok, err = _validate_archive(p, ".tar.gz")
        assert ok is False
        assert "traversal" in err.lower() or "path" in err.lower()

    def test_corrupt_zip_rejected(self, tmp_path):
        from api.system import _validate_archive
        p = str(tmp_path / "bad.zip")
        with open(p, "wb") as f:
            f.write(b"not a zip at all")
        ok, err = _validate_archive(p, ".zip")
        assert ok is False
        assert err is not None

    def test_corrupt_targz_rejected(self, tmp_path):
        from api.system import _validate_archive
        p = str(tmp_path / "bad.tar.gz")
        with open(p, "wb") as f:
            f.write(b"\x00\x01\x02\x03garbage")
        ok, err = _validate_archive(p, ".tar.gz")
        assert ok is False

    def test_unsupported_ext_rejected(self, tmp_path):
        from api.system import _validate_archive
        ok, err = _validate_archive(str(tmp_path / "pkg.exe"), ".exe")
        assert ok is False
        assert "estensione" in err.lower() or "supportata" in err.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# D) Apply flow — _run_ota_file()
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunOtaFile:

    def _setup_staged_zip(self, staging_dir):
        """Write a valid staged_package.zip to staging_dir. Returns path."""
        path = os.path.join(staging_dir, "staged_package.zip")
        data = _make_valid_zip()
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_successful_apply_sets_success_state(self, tmp_path):
        from api.system import _run_ota_file

        staged = str(tmp_path / "staged_package.zip")
        with open(staged, "wb") as f:
            f.write(_make_valid_zip())

        state_file = str(tmp_path / "ota_state.json")

        with (
            patch("api.system.OTA_STATE_FILE", state_file),
            patch("api.system.OTA_LOG_FILE", str(tmp_path / "ota.log")),
            patch("api.system._create_backup", return_value="backup_20260101_120000"),
            patch("api.system._apply_archive", return_value=(True, None, 10)),
            patch("api.system.log_event") as mock_log_event,
        ):
            _run_ota_file(staged, "update.zip", ".zip")

        with open(state_file) as f:
            state = json.load(f)

        assert state["status"] == "success"
        assert state["running"] is False
        assert state["progress_percent"] == 100

        # Check event log calls
        log_calls = [str(c) for c in mock_log_event.call_args_list]
        assert any("success" in c.lower() or "completato" in c.lower() for c in log_calls)

    def test_failed_backup_aborts_and_sets_failed(self, tmp_path):
        from api.system import _run_ota_file

        staged = str(tmp_path / "staged_package.zip")
        with open(staged, "wb") as f:
            f.write(_make_valid_zip())

        state_file = str(tmp_path / "ota_state.json")

        with (
            patch("api.system.OTA_STATE_FILE", state_file),
            patch("api.system.OTA_LOG_FILE", str(tmp_path / "ota.log")),
            patch("api.system._create_backup", return_value=None),  # backup fails
            patch("api.system.log_event"),
        ):
            _run_ota_file(staged, "update.zip", ".zip")

        with open(state_file) as f:
            state = json.load(f)

        assert state["status"] == "failed"
        assert state["running"] is False
        assert "backup" in (state.get("last_error") or "").lower()

    def test_invalid_package_aborts_and_sets_failed(self, tmp_path):
        from api.system import _run_ota_file

        # Create a zip missing main.py
        staged = str(tmp_path / "staged_package.zip")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("README.md", "no main here")
        with open(staged, "wb") as f:
            f.write(buf.getvalue())

        state_file = str(tmp_path / "ota_state.json")

        with (
            patch("api.system.OTA_STATE_FILE", state_file),
            patch("api.system.OTA_LOG_FILE", str(tmp_path / "ota.log")),
            patch("api.system._create_backup", return_value="backup_x"),
            patch("api.system.log_event") as mock_log_event,
        ):
            _run_ota_file(staged, "update.zip", ".zip")

        with open(state_file) as f:
            state = json.load(f)

        assert state["status"] == "failed"
        assert state["last_error"] is not None

        # Error event logged
        error_calls = [c for c in mock_log_event.call_args_list if "error" in str(c)]
        assert len(error_calls) > 0

    def test_path_traversal_archive_aborts(self, tmp_path):
        from api.system import _run_ota_file

        # Create a zip with path traversal AND main.py (to pass required check but fail traversal)
        staged = str(tmp_path / "staged_package.zip")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../etc/cron.d/evil", "* * * * * root rm -rf /")
            zf.writestr("main.py", "# ok")
        with open(staged, "wb") as f:
            f.write(buf.getvalue())

        state_file = str(tmp_path / "ota_state.json")

        with (
            patch("api.system.OTA_STATE_FILE", state_file),
            patch("api.system.OTA_LOG_FILE", str(tmp_path / "ota.log")),
            patch("api.system.log_event"),
        ):
            _run_ota_file(staged, "evil.zip", ".zip")

        with open(state_file) as f:
            state = json.load(f)

        assert state["status"] == "failed"

    def test_apply_logs_start_and_success_events(self, tmp_path):
        from api.system import _run_ota_file

        staged = str(tmp_path / "staged_package.zip")
        with open(staged, "wb") as f:
            f.write(_make_valid_zip())

        state_file = str(tmp_path / "ota_state.json")

        with (
            patch("api.system.OTA_STATE_FILE", state_file),
            patch("api.system.OTA_LOG_FILE", str(tmp_path / "ota.log")),
            patch("api.system._create_backup", return_value="bk"),
            patch("api.system._apply_archive", return_value=(True, None, 5)),
            patch("api.system.log_event") as mock_log_event,
        ):
            _run_ota_file(staged, "pkg.zip", ".zip")

        calls_str = [str(c) for c in mock_log_event.call_args_list]
        # At least: validation start and success
        assert len(calls_str) >= 2
        combined = " ".join(calls_str).lower()
        assert "validazione" in combined or "avviata" in combined
        assert "successo" in combined or "completato" in combined


# ═══════════════════════════════════════════════════════════════════════════════
# E) OTA state shape
# ═══════════════════════════════════════════════════════════════════════════════

class TestOtaStateShape:

    def test_default_has_staged_fields(self):
        from api.system import _OTA_STATE_DEFAULT
        assert "staged_filename" in _OTA_STATE_DEFAULT
        assert "staged_at" in _OTA_STATE_DEFAULT

    def test_load_backfills_staged_fields_from_old_state(self, tmp_path):
        from api.system import _load_ota_state

        # Old state without staged_* fields
        old_state = {"status": "idle", "running": False, "mode": None}
        state_file = str(tmp_path / "ota_state.json")
        with open(state_file, "w") as f:
            json.dump(old_state, f)

        with patch("api.system.OTA_STATE_FILE", state_file):
            state = _load_ota_state()

        assert "staged_filename" in state
        assert "staged_at" in state

    def test_load_returns_default_when_file_missing(self, tmp_path):
        from api.system import _load_ota_state, _OTA_STATE_DEFAULT

        state_file = str(tmp_path / "nonexistent_ota_state.json")
        with patch("api.system.OTA_STATE_FILE", state_file):
            state = _load_ota_state()

        for key in _OTA_STATE_DEFAULT:
            assert key in state

    def test_running_derived_from_status(self, tmp_path):
        from api.system import _load_ota_state

        state_file = str(tmp_path / "ota_state.json")
        with open(state_file, "w") as f:
            json.dump({"status": "running", "running": False}, f)

        with patch("api.system.OTA_STATE_FILE", state_file):
            state = _load_ota_state()

        # running must be derived from status == "running"
        assert state["running"] is True

    def test_ota_extension_helper(self):
        from api.system import _ota_package_extension
        assert _ota_package_extension("pkg.zip") == ".zip"
        assert _ota_package_extension("pkg.tar.gz") == ".tar.gz"
        assert _ota_package_extension("pkg.ZIP") == ".zip"    # case-insensitive accepted
        assert _ota_package_extension("pkg.TAR.GZ") == ".tar.gz"  # case-insensitive accepted
        assert _ota_package_extension("evil.exe") is None
        assert _ota_package_extension("") is None
        assert _ota_package_extension("nodot") is None
        assert _ota_package_extension("archive.tar") is None
        assert _ota_package_extension("data.gz") is None
