"""
tests/test_audit_fixes.py — Test per i fix dell'audit completo del repository.

Copre i tre bug identificati e corretti:

  1) Conflitto di rotte /api/rfid/trigger
     - Bug: media_bp (registrato prima) oscurava rfid_bp, ignorando rfid_profiles
     - Fix: rfid_bp viene registrato prima di media_bp in main.py
     - Test: verifica che l'endpoint corretto (rfid.api_rfid_trigger_profile)
             gestisca le richieste quando entrambi i blueprint sono attivi

  2) _apply_profile_led non impostava led_runtime["current_rfid"]
     - Bug: solo led_runtime["led_rfid_code"] veniva impostato; get_effective_led_assignment
            in api/led.py legge "current_rfid" → LED non aggiornati dai profili RFID
     - Fix: _apply_profile_led imposta anche led_runtime["current_rfid"] = rfid_code

  3) Path traversal security in api/files.py
     - Bug: startswith(realpath(r)) senza + os.sep permetteva /home/gufoboxbad
             quando la radice consentita è /home/gufobox
     - Fix: _resolve_safe, api_files_list e _run_uncompress usano
             `real == r_real or real.startswith(r_real + os.sep)`
"""

import io
import os
import sys
import zipfile
import tempfile
from copy import deepcopy
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ===========================================================================
# Fixture Flask minimale con ENTRAMBI i blueprint (come in produzione)
# ===========================================================================

@pytest.fixture()
def full_app():
    """Flask app con rfid_bp registrato PRIMA di media_bp, come in main.py."""
    from flask import Flask
    from flask_cors import CORS
    from core.extensions import socketio
    from api.rfid import rfid_bp
    from api.media import media_bp

    flask_app = Flask(__name__)
    flask_app.secret_key = "test-audit-secret"
    flask_app.config["TESTING"] = True
    CORS(flask_app)
    # Ordine corretto: rfid_bp prima di media_bp
    flask_app.register_blueprint(rfid_bp, url_prefix="/api")
    flask_app.register_blueprint(media_bp, url_prefix="/api")
    socketio.init_app(flask_app, async_mode="threading")
    return flask_app


@pytest.fixture()
def full_client(full_app):
    with full_app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def reset_state():
    """Reset rfid_profiles e rfid_map prima e dopo ogni test."""
    from core.state import rfid_profiles, rfid_map
    orig_profiles = deepcopy(dict(rfid_profiles))
    orig_map = deepcopy(dict(rfid_map))
    yield
    rfid_profiles.clear()
    rfid_profiles.update(orig_profiles)
    rfid_map.clear()
    rfid_map.update(orig_map)


# ===========================================================================
# 1) Conflitto di rotte /api/rfid/trigger
# ===========================================================================

class TestRfidRouteConflict:
    """
    Verifica che registrando rfid_bp prima di media_bp il trigger RFID utilizzi
    l'implementazione completa di rfid_bp (che gestisce rfid_profiles e più mode).
    """

    def test_rfid_trigger_uses_rfid_bp_when_both_registered(self, full_app):
        """Quando entrambi i blueprint sono registrati, deve vincere rfid_bp."""
        adapter = full_app.url_map.bind("localhost")
        endpoint, _ = adapter.match("/api/rfid/trigger", method="POST")
        assert endpoint == "rfid.api_rfid_trigger_profile", (
            f"Endpoint errato: {endpoint!r}. "
            "rfid_bp deve essere registrato prima di media_bp in main.py "
            "affinché la rotta completa gestisca le richieste."
        )

    def test_rfid_trigger_uses_rfid_profiles_not_only_rfid_map(self, full_client):
        """
        Con rfid_bp prioritario, un profilo in rfid_profiles (mode=media_folder)
        deve essere eseguito correttamente, non ignorato.
        """
        from core.state import rfid_profiles, media_runtime
        rfid_profiles["AUDIT:01"] = {
            "rfid_code": "AUDIT:01",
            "name": "Test Cartella",
            "enabled": True,
            "mode": "media_folder",
            "folder": "/some/folder",
            "webradio_url": "",
            "web_media_url": "",
            "web_content_type": "generic",
            "ai_prompt": "",
            "rss_url": "",
            "rss_limit": 10,
            "volume": 70,
            "loop": True,
            "led": None,
            "edu_config": None,
            "recording_path": "",
            "image_path": "",
            "updated_at": 0,
        }
        # build_playlist e start_player sono importati dentro le funzioni di api/rfid.py
        with patch("core.media.start_player", return_value=(True, "ok")), \
             patch("core.media.build_playlist", return_value=["/some/folder/track.mp3"]), \
             patch("core.database.get_resume_position", return_value=None):
            resp = full_client.post("/api/rfid/trigger", json={"rfid_code": "AUDIT:01"})
        assert resp.status_code == 200, (
            f"Il trigger RFID per profilo media_folder dovrebbe dare 200, "
            f"non {resp.status_code}: {resp.get_data(as_text=True)}"
        )

    def test_rfid_trigger_falls_back_to_rfid_map_via_rfid_bp(self, full_client):
        """
        Anche con rfid_bp attivo, il fallback su rfid_map (legacy) deve funzionare.
        """
        from core.state import rfid_map
        rfid_map["LEGACY:01"] = {
            "type": "audio",
            "target": "/music/legacy.mp3",
            "name": "Legacy Track",
        }
        # start_player è importato dentro _handle_legacy_trigger / _exec_* in api/rfid.py
        with patch("core.media.start_player", return_value=(True, "ok")):
            resp = full_client.post("/api/rfid/trigger", json={"rfid_code": "LEGACY:01"})
        assert resp.status_code == 200

    def test_rfid_trigger_unknown_returns_404(self, full_client):
        """UID sconosciuto deve restituire 404 con rfid_bp attivo."""
        resp = full_client.post("/api/rfid/trigger", json={"rfid_code": "UNKNOWN:99"})
        assert resp.status_code == 404

    def test_rfid_map_routes_still_accessible_via_media_bp(self, full_client):
        """La rotta /rfid/map (solo in media_bp) deve restare raggiungibile."""
        resp = full_client.get("/api/rfid/map")
        assert resp.status_code == 200

    def test_rfid_delete_still_accessible_via_media_bp(self, full_client):
        """La rotta /rfid/delete (solo in media_bp) deve restare raggiungibile."""
        resp = full_client.post("/api/rfid/delete", json={"uid": "NONEXISTENT"})
        # 404 perché UID non esiste, ma la rotta è raggiungibile
        assert resp.status_code == 404


# ===========================================================================
# 2) _apply_profile_led imposta led_runtime["current_rfid"]
# ===========================================================================

class TestApplyProfileLedSetsCurrentRfid:
    """
    _apply_profile_led deve impostare led_runtime["current_rfid"] oltre a
    led_runtime["led_rfid_code"], per garantire la compatibilità con
    get_effective_led_assignment() in api/led.py.
    """

    def test_apply_profile_led_sets_current_rfid(self):
        """led_runtime["current_rfid"] deve essere impostato da _apply_profile_led."""
        from api.rfid import _apply_profile_led
        from core.state import led_runtime

        profile_with_led = {
            "led": {
                "enabled": True,
                "effect_id": "pulse",
                "color": "#ff00cc",
                "brightness": 80,
                "speed": 50,
                "params": {},
            }
        }

        led_runtime.pop("current_rfid", None)

        with patch("api.rfid.bus") as mock_bus:
            _apply_profile_led("TEST:RFID:01", profile_with_led)

        assert led_runtime.get("current_rfid") == "TEST:RFID:01", (
            "led_runtime['current_rfid'] non impostato da _apply_profile_led. "
            "Questo interrompe get_effective_led_assignment() in api/led.py."
        )

    def test_apply_profile_led_also_sets_legacy_fields(self):
        """_apply_profile_led deve continuare ad impostare led_rfid_code e gli altri campi."""
        from api.rfid import _apply_profile_led
        from core.state import led_runtime

        profile_with_led = {
            "led": {
                "enabled": True,
                "effect_id": "breathing",
                "color": "#00ff00",
                "brightness": 60,
                "speed": 30,
                "params": {},
            }
        }

        with patch("api.rfid.bus") as mock_bus:
            _apply_profile_led("TEST:RFID:02", profile_with_led)

        assert led_runtime.get("led_rfid_code") == "TEST:RFID:02"
        assert led_runtime.get("led_source") == "rfid_profile"
        assert led_runtime.get("current_effect") == "breathing"
        assert led_runtime.get("master_color") == "#00ff00"

    def test_apply_profile_led_no_led_block_does_not_set_current_rfid(self):
        """Se il profilo non ha LED abilitati, current_rfid non deve cambiare."""
        from api.rfid import _apply_profile_led
        from core.state import led_runtime

        led_runtime["current_rfid"] = "PREVIOUS:RFID"

        with patch("api.rfid.bus") as mock_bus:
            _apply_profile_led("NEW:RFID", {"led": None})
            _apply_profile_led("NEW:RFID", {})
            _apply_profile_led("NEW:RFID", {"led": {"enabled": False}})

        # Deve restare invariato
        assert led_runtime.get("current_rfid") == "PREVIOUS:RFID"

    def test_led_current_rfid_propagates_to_get_effective_led_assignment(self):
        """
        Dopo _apply_profile_led, get_effective_led_assignment deve trovare
        il profilo LED corretto via led_runtime["current_rfid"] e rfid_map.
        """
        from api.rfid import _apply_profile_led
        from api.led import get_effective_led_assignment
        from core.state import led_runtime, rfid_map

        uid = "LED:TEST:03"
        rfid_map[uid] = {
            "type": "audio",
            "target": "/music/test.mp3",
            "led": {
                "enabled": True,
                "effect_id": "rainbow",
                "color": "#aabbcc",
                "brightness": 55,
                "speed": 25,
                "params": {},
            },
        }

        with patch("api.rfid.bus") as mock_bus:
            _apply_profile_led(uid, rfid_map[uid])

        assignment, source = get_effective_led_assignment()
        assert source == "rfid", (
            f"Source atteso 'rfid', ottenuto {source!r}. "
            "get_effective_led_assignment non legge correttamente current_rfid."
        )
        assert assignment.get("effect_id") == "rainbow"

        del rfid_map[uid]


# ===========================================================================
# 3) Path traversal security in api/files.py
# ===========================================================================

class TestPathTraversalSecurity:
    """
    Verifica che _resolve_safe, api_files_list e _run_uncompress
    blocchino path con prefisso comune ma separatore mancante.
    """

    def test_resolve_safe_blocks_sibling_directory(self, tmp_path):
        """
        /home/gufoboxbad non deve essere accettato quando la radice è /home/gufobox.
        Senza + os.sep il check startswith fallisce silenziosamente.
        """
        import config as _cfg
        from api.files import _resolve_safe

        # Crea due cartelle sibling in tmp
        allowed = tmp_path / "gufobox"
        allowed.mkdir()
        sibling = tmp_path / "gufoboxbad"
        sibling.mkdir()

        orig_roots = _cfg.FILE_MANAGER_ROOTS[:]
        try:
            _cfg.FILE_MANAGER_ROOTS[:] = [str(allowed)]
            result = _resolve_safe(str(sibling))
            assert result is None, (
                f"_resolve_safe ha accettato il path sibling {sibling} "
                "che non è dentro la radice consentita."
            )
        finally:
            _cfg.FILE_MANAGER_ROOTS[:] = orig_roots

    def test_resolve_safe_accepts_root_itself(self, tmp_path):
        """La radice stessa deve essere accettata."""
        import config as _cfg
        from api.files import _resolve_safe

        allowed = tmp_path / "gufobox"
        allowed.mkdir()

        orig_roots = _cfg.FILE_MANAGER_ROOTS[:]
        try:
            _cfg.FILE_MANAGER_ROOTS[:] = [str(allowed)]
            result = _resolve_safe(str(allowed))
            assert result is not None, "La radice stessa dovrebbe essere accettata."
        finally:
            _cfg.FILE_MANAGER_ROOTS[:] = orig_roots

    def test_resolve_safe_accepts_subdirectory(self, tmp_path):
        """Una sottocartella della radice deve essere accettata."""
        import config as _cfg
        from api.files import _resolve_safe

        allowed = tmp_path / "gufobox"
        subdir = allowed / "media" / "audio"
        subdir.mkdir(parents=True)

        orig_roots = _cfg.FILE_MANAGER_ROOTS[:]
        try:
            _cfg.FILE_MANAGER_ROOTS[:] = [str(allowed)]
            result = _resolve_safe(str(subdir))
            assert result is not None
        finally:
            _cfg.FILE_MANAGER_ROOTS[:] = orig_roots

    def test_files_list_blocks_sibling_path(self, tmp_path):
        """GET /files/list con path sibling deve restituire 403."""
        import config as _cfg
        from flask import Flask
        from flask_cors import CORS
        from core.extensions import socketio
        from api.files import files_bp

        allowed = tmp_path / "gufobox"
        allowed.mkdir()
        sibling = tmp_path / "gufoboxbad"
        sibling.mkdir()

        flask_app = Flask(__name__)
        flask_app.secret_key = "test"
        flask_app.config["TESTING"] = True
        CORS(flask_app)
        flask_app.register_blueprint(files_bp, url_prefix="/api")
        socketio.init_app(flask_app, async_mode="threading")

        orig_roots = _cfg.FILE_MANAGER_ROOTS[:]
        try:
            _cfg.FILE_MANAGER_ROOTS[:] = [str(allowed)]
            with flask_app.test_client() as c:
                resp = c.get(f"/api/files/list?path={sibling}")
            assert resp.status_code == 403, (
                f"Il path sibling {sibling} non dovrebbe essere accessibile."
            )
        finally:
            _cfg.FILE_MANAGER_ROOTS[:] = orig_roots

    def test_files_list_accepts_root_path(self, tmp_path):
        """GET /files/list con la radice stessa deve restituire 200."""
        import config as _cfg
        from flask import Flask
        from flask_cors import CORS
        from core.extensions import socketio
        from api.files import files_bp

        allowed = tmp_path / "gufobox"
        allowed.mkdir()

        flask_app = Flask(__name__)
        flask_app.secret_key = "test"
        flask_app.config["TESTING"] = True
        CORS(flask_app)
        flask_app.register_blueprint(files_bp, url_prefix="/api")
        socketio.init_app(flask_app, async_mode="threading")

        orig_roots = _cfg.FILE_MANAGER_ROOTS[:]
        orig_default = _cfg.FILE_MANAGER_DEFAULT_PATH
        try:
            _cfg.FILE_MANAGER_ROOTS[:] = [str(allowed)]
            _cfg.FILE_MANAGER_DEFAULT_PATH = str(allowed)
            with flask_app.test_client() as c:
                resp = c.get(f"/api/files/list?path={allowed}")
            assert resp.status_code == 200
        finally:
            _cfg.FILE_MANAGER_ROOTS[:] = orig_roots
            _cfg.FILE_MANAGER_DEFAULT_PATH = orig_default

    def test_run_uncompress_blocks_path_traversal_sibling(self, tmp_path):
        """
        _run_uncompress deve bloccare membri il cui path reale è fuori
        dalla destinazione (anche con prefisso comune senza sep).
        """
        from api.files import _run_uncompress
        from core.jobs import create_job

        dest = tmp_path / "dest"
        dest.mkdir()

        # Crea una cartella sibling con prefisso comune
        sibling = tmp_path / "destbad"
        sibling.mkdir()

        # Costruisce uno zip con un membro che punta al sibling via symlink name
        # (sul filesystem reale, usiamo un path con ../destbad)
        zip_path = str(tmp_path / "evil.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            # Membro con path traversal esplicito: ../destbad/evil.txt
            zi = zipfile.ZipInfo("../destbad/evil.txt")
            zf.writestr(zi, "evil content")

        job_id = create_job("uncompress", {"archive": zip_path})

        with patch("api.files.update_job"), patch("api.files.finish_job") as mock_finish:
            _run_uncompress(job_id, zip_path, str(dest))
            # Deve finire in errore, non estrarre
            mock_finish.assert_called_once()
            call_kwargs = mock_finish.call_args
            status = call_kwargs[1].get("status") or (
                call_kwargs[0][1] if len(call_kwargs[0]) > 1 else None
            )
            assert status == "error", (
                f"_run_uncompress doveva rifiutare il path traversal, "
                f"invece ha chiamato finish_job con: {call_kwargs}"
            )
