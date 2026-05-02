"""
tests/test_admin_update_extension_pr35.py — PR 35: Extended admin update system.

Covers:
A) Backup resilience — _create_backup() must skip special files
   - Named pipe (FIFO) in source dir is silently skipped, not fatal
   - Socket file is silently skipped
   - Regular files and directories are backed up normally
   - Log entry is written for each skipped special file

B) New OTA modes — api_ota_start() accepts 'drivers' and 'system_firmware'
   - 'drivers' mode is accepted and starts background worker
   - 'system_firmware' mode is accepted and starts background worker
   - Unknown modes are still rejected with 400

C) URL fetch endpoint — POST /system/ota/fetch_url
   - Valid zip URL sets ota_state to 'uploaded'
   - Valid tar.gz URL sets ota_state to 'uploaded'
   - Missing url field returns 400
   - Non-http scheme returns 400
   - URL not pointing to .zip or .tar.gz returns 400
   - URL download error (network) returns 502
   - Oversized download is rejected with 413
   - Successful fetch logs event
"""

import io
import json
import os
import stat
import sys
import tempfile
import zipfile
from unittest.mock import MagicMock, patch, call
from urllib.error import URLError

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
    flask_app.secret_key = "test-ota-ext-secret"
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
    d = tmp_path / "ota_staging"
    d.mkdir()
    with patch("api.system.OTA_STAGING_DIR", str(d)):
        yield str(d)


@pytest.fixture()
def state_file(tmp_path):
    f = tmp_path / "ota_state.json"
    with patch("api.system.OTA_STATE_FILE", str(f)):
        yield str(f)


def _make_valid_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("main.py", "# GufoBox entry point\n")
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════════════
# A) Backup resilience — special files are skipped
# ═══════════════════════════════════════════════════════════════════════════════

class TestBackupSkipsSpecialFiles:
    """_create_backup() must not fail when the source tree contains special files."""

    def test_named_pipe_is_excluded(self, tmp_path):
        """A FIFO/named pipe in the source dir must NOT cause the backup to fail."""
        from api.system import _create_backup

        src = tmp_path / "app"
        src.mkdir()
        (src / "main.py").write_text("# main\n")
        (src / "requirements.txt").write_text("flask\n")

        # Create a named pipe
        pipe_path = src / ".lgd-nfy0"
        os.mkfifo(str(pipe_path))

        backup_root = tmp_path / "backups"
        backup_root.mkdir()

        with (
            patch("api.system.BASE_DIR", str(src)),
            patch("api.system.BACKUP_DIR", str(backup_root)),
            patch("api.system._ota_log") as mock_log,
        ):
            result = _create_backup()

        # Backup must succeed
        assert result is not None, "Backup should not fail because of a named pipe"

        # The named pipe must NOT be in the backup
        backup_path = backup_root / result
        assert not (backup_path / ".lgd-nfy0").exists(), "Named pipe must be excluded from backup"

        # A regular file must still be present
        assert (backup_path / "main.py").exists(), "Regular file must be included in backup"

        # A log line should mention the skipped file
        skipped_log_calls = [
            str(c) for c in mock_log.call_args_list
            if "speciale" in str(c).lower() or "lgd-nfy0" in str(c)
        ]
        assert skipped_log_calls, "A log line should record the skipped special file"

    def test_backup_succeeds_without_special_files(self, tmp_path):
        """Normal backup (no special files) must still work correctly."""
        from api.system import _create_backup

        src = tmp_path / "app"
        src.mkdir()
        (src / "main.py").write_text("# main\n")
        subdir = src / "api"
        subdir.mkdir()
        (subdir / "system.py").write_text("# system\n")

        backup_root = tmp_path / "backups"
        backup_root.mkdir()

        with (
            patch("api.system.BASE_DIR", str(src)),
            patch("api.system.BACKUP_DIR", str(backup_root)),
        ):
            result = _create_backup()

        assert result is not None
        backup_path = backup_root / result
        assert (backup_path / "main.py").exists()
        assert (backup_path / "api" / "system.py").exists()

    def test_excluded_dirs_not_in_backup(self, tmp_path):
        """Directories in _BACKUP_EXCLUSIONS must be excluded."""
        from api.system import _create_backup

        src = tmp_path / "app"
        src.mkdir()
        (src / "main.py").write_text("# main\n")
        (src / "__pycache__").mkdir()
        (src / "__pycache__" / "cache.pyc").write_bytes(b"\x00")

        backup_root = tmp_path / "backups"
        backup_root.mkdir()

        with (
            patch("api.system.BASE_DIR", str(src)),
            patch("api.system.BACKUP_DIR", str(backup_root)),
        ):
            result = _create_backup()

        assert result is not None
        backup_path = backup_root / result
        assert not (backup_path / "__pycache__").exists(), "__pycache__ must be excluded"


# ═══════════════════════════════════════════════════════════════════════════════
# B) New OTA modes accepted by api_ota_start
# ═══════════════════════════════════════════════════════════════════════════════

class TestOtaStartNewModes:

    def test_drivers_mode_accepted(self, client, state_file):
        """POST /system/ota/start with mode='drivers' should return 200 started."""
        with patch("api.system.eventlet") as mock_ev, \
             patch("api.system.bus"):
            mock_ev.spawn_n = lambda fn: fn()
            with patch("api.system._run_ota") as mock_run:
                resp = client.post(
                    "/api/system/ota/start",
                    json={"mode": "drivers"},
                    content_type="application/json",
                )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "started"
        assert body["mode"] == "drivers"

    def test_system_firmware_mode_accepted(self, client, state_file):
        """POST /system/ota/start with mode='system_firmware' should return 200."""
        with patch("api.system.eventlet") as mock_ev, \
             patch("api.system.bus"):
            mock_ev.spawn_n = lambda fn: fn()
            with patch("api.system._run_ota"):
                resp = client.post(
                    "/api/system/ota/start",
                    json={"mode": "system_firmware"},
                    content_type="application/json",
                )
        assert resp.status_code == 200
        assert resp.get_json()["mode"] == "system_firmware"

    def test_unknown_mode_still_rejected(self, client, state_file):
        """POST /system/ota/start with unknown mode should still return 400."""
        resp = client.post(
            "/api/system/ota/start",
            json={"mode": "invalid_mode"},
            content_type="application/json",
        )
        assert resp.status_code == 400
        err = resp.get_json()["error"].lower()
        assert "modalità" in err or "mode" in err or "supportata" in err

    def test_all_valid_modes_accepted(self, client, state_file):
        """All four valid modes must be accepted."""
        import api.system as sys_mod

        valid_modes = ("app", "system_safe", "drivers", "system_firmware")
        for mode in valid_modes:
            # Ensure lock is free
            try:
                sys_mod._ota_lock.release()
            except RuntimeError:
                pass

            with patch("api.system.eventlet") as mock_ev, \
                 patch("api.system.bus"), \
                 patch("api.system._run_ota"):
                mock_ev.spawn_n = lambda fn: None
                resp = client.post(
                    "/api/system/ota/start",
                    json={"mode": mode},
                    content_type="application/json",
                )
            assert resp.status_code == 200, f"Mode '{mode}' should be accepted (got {resp.status_code})"


# ═══════════════════════════════════════════════════════════════════════════════
# C) URL fetch endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestOtaFetchUrl:

    def _mock_urlopen(self, data: bytes):
        """Return a context-manager mock that streams `data`."""
        resp_mock = MagicMock()
        # .read() returns chunks then b""
        resp_mock.read.side_effect = [data, b""]
        resp_mock.__enter__ = lambda s: s
        resp_mock.__exit__ = MagicMock(return_value=False)
        return resp_mock

    def test_valid_zip_url_sets_state_uploaded(self, client, staging_dir, state_file):
        """A valid zip URL should set ota_state status to 'uploaded'."""
        zip_data = _make_valid_zip()
        mock_resp = self._mock_urlopen(zip_data)

        with patch("api.system.urllib.request.urlopen", return_value=mock_resp):
            resp = client.post(
                "/api/system/ota/fetch_url",
                json={"url": "https://example.com/gufobox-update.zip"},
                content_type="application/json",
            )

        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body["status"] == "uploaded"
        assert body["ext"] == ".zip"
        assert body["source"] == "url"
        # Staged file must exist
        assert os.path.isfile(os.path.join(staging_dir, "staged_package.zip"))

    def test_valid_targz_url(self, client, staging_dir, state_file):
        """A valid tar.gz URL should stage a .tar.gz file."""
        import tarfile as _tf
        buf = io.BytesIO()
        with _tf.open(fileobj=buf, mode="w:gz") as tf:
            data = b"# main\n"
            info = _tf.TarInfo(name="main.py")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        gz_data = buf.getvalue()

        mock_resp = self._mock_urlopen(gz_data)
        with patch("api.system.urllib.request.urlopen", return_value=mock_resp):
            resp = client.post(
                "/api/system/ota/fetch_url",
                json={"url": "https://example.com/gufobox-update.tar.gz"},
                content_type="application/json",
            )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ext"] == ".tar.gz"
        assert os.path.isfile(os.path.join(staging_dir, "staged_package.tar.gz"))

    def test_missing_url_returns_400(self, client, staging_dir, state_file):
        resp = client.post(
            "/api/system/ota/fetch_url",
            json={},
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "url" in resp.get_json()["error"].lower()

    def test_non_http_scheme_returns_400(self, client, staging_dir, state_file):
        resp = client.post(
            "/api/system/ota/fetch_url",
            json={"url": "ftp://example.com/update.zip"},
            content_type="application/json",
        )
        assert resp.status_code == 400
        err = resp.get_json()["error"].lower()
        assert "schema" in err or "scheme" in err or "consentito" in err

    def test_non_package_url_returns_400(self, client, staging_dir, state_file):
        resp = client.post(
            "/api/system/ota/fetch_url",
            json={"url": "https://example.com/update.exe"},
            content_type="application/json",
        )
        assert resp.status_code == 400
        err = resp.get_json()["error"].lower()
        assert "zip" in err or "tar" in err or "url" in err

    def test_url_network_error_returns_502(self, client, staging_dir, state_file):
        with patch("api.system.urllib.request.urlopen", side_effect=URLError("connection refused")):
            resp = client.post(
                "/api/system/ota/fetch_url",
                json={"url": "https://example.com/update.zip"},
                content_type="application/json",
            )
        assert resp.status_code == 502
        err = resp.get_json()["error"].lower()
        assert "scaricare" in err or "download" in err

    def test_oversized_url_download_returns_413(self, client, staging_dir, state_file):
        """Downloads exceeding OTA_MAX_PACKAGE_BYTES must be rejected with 413."""
        large_chunk = b"x" * 200

        mock_resp = MagicMock()
        # Keep returning data so size limit is exceeded
        mock_resp.read.return_value = large_chunk
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("api.system.OTA_MAX_PACKAGE_BYTES", 100), \
             patch("api.system.urllib.request.urlopen", return_value=mock_resp):
            resp = client.post(
                "/api/system/ota/fetch_url",
                json={"url": "https://example.com/update.zip"},
                content_type="application/json",
            )
        assert resp.status_code == 413
        err = resp.get_json()["error"].lower()
        assert "grande" in err or "large" in err

    def test_successful_fetch_logs_event(self, client, staging_dir, state_file):
        zip_data = _make_valid_zip()
        mock_resp = self._mock_urlopen(zip_data)

        with patch("api.system.urllib.request.urlopen", return_value=mock_resp), \
             patch("api.system.log_event") as mock_log:
            client.post(
                "/api/system/ota/fetch_url",
                json={"url": "https://example.com/gufobox-update.zip"},
                content_type="application/json",
            )

        logged = [str(c) for c in mock_log.call_args_list]
        assert any("url" in c.lower() or "scaricato" in c.lower() for c in logged)

    def test_fetch_updates_ota_state_file(self, client, staging_dir, state_file):
        zip_data = _make_valid_zip()
        mock_resp = self._mock_urlopen(zip_data)

        with patch("api.system.urllib.request.urlopen", return_value=mock_resp):
            client.post(
                "/api/system/ota/fetch_url",
                json={"url": "https://example.com/gufobox-update.zip"},
                content_type="application/json",
            )

        with open(state_file) as f:
            state = json.load(f)
        assert state["status"] == "uploaded"
        assert state["mode"] == "file"
        assert state["staged_filename"] is not None
        assert state["staged_at"] is not None

    def test_localhost_url_blocked_ssrf(self, client, staging_dir, state_file):
        """URLs pointing to localhost/internal hosts must be rejected (SSRF prevention)."""
        blocked_urls = [
            "http://localhost/update.zip",
            "http://127.0.0.1/update.zip",
        ]
        for url in blocked_urls:
            resp = client.post(
                "/api/system/ota/fetch_url",
                json={"url": url},
                content_type="application/json",
            )
            assert resp.status_code == 400, f"Expected 400 for SSRF URL {url!r}, got {resp.status_code}"
            err = resp.get_json()["error"].lower()
            assert "host" in err or "consentito" in err or "bloccato" in err, \
                f"Expected host-related error for {url!r}, got: {err!r}"
