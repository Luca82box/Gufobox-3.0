"""
tests/test_refactoring_pr32.py — Verifica delle correzioni architetturali (PR #32).

Copre:
  1) hw/buttons.py: importa direttamente le funzioni Python, niente HTTP top-level
  2) hw/rfid.py: usa _trigger_rfid_direct() prima del fallback HTTP
  3) core/event_log.py: usa append puro e _write_raw solo per il trimming periodico
  4) core/utils.py: flag _shutdown_requested e is_shutdown_requested()
  5) hw/battery.py: state["battery"] come dizionario strutturato
  6) hw/battery.py: rilevazione ricarica tramite registro CRATE del MAX17048
  7) core/media.py: _reset_media_runtime() è definita e usata in stop_player + watchdog
  8) Dockerfile: stage multi-stage per il build del frontend Vue
"""

import ast
import os
import sys
import json
import tempfile
import pathlib

import pytest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _has_module_level_requests_import(py_file: pathlib.Path) -> bool:
    """Ritorna True se `import requests` (o `from requests ...`) è al top-level del modulo."""
    tree = ast.parse(py_file.read_text())
    return any(
        isinstance(n, (ast.Import, ast.ImportFrom))
        and any(
            (alias.name if isinstance(n, ast.Import) else (n.module or "")).startswith("requests")
            for alias in n.names
        )
        for n in ast.iter_child_nodes(tree)
    )



# ===========================================================================
# 1) hw/buttons.py — import diretto, niente HTTP al top-level
# ===========================================================================

class TestButtonsNoDependencyOnHTTP:
    """I pulsanti fisici devono usare import Python diretto, non roundtrip HTTP."""

    def test_no_top_level_requests_import(self):
        """requests non deve essere importato al livello modulo di hw/buttons.py."""
        assert not _has_module_level_requests_import(ROOT / "hw" / "buttons.py"), (
            "import requests trovato al livello modulo di hw/buttons.py; "
            "deve stare solo dentro le funzioni di fallback"
        )

    def test_direct_imports_present(self):
        """hw/buttons.py deve importare direttamente le funzioni core (send_mpv_command, perform_standby, ...)."""
        import hw.buttons as btns
        assert hasattr(btns, "_send_mpv_command"), "_send_mpv_command non trovato in hw.buttons"
        assert hasattr(btns, "_perform_standby"), "_perform_standby non trovato in hw.buttons"
        assert hasattr(btns, "_wake_from_standby"), "_wake_from_standby non trovato in hw.buttons"
        assert hasattr(btns, "_is_in_standby"), "_is_in_standby non trovato in hw.buttons"
        assert hasattr(btns, "_DIRECT_AVAILABLE"), "_DIRECT_AVAILABLE non trovato in hw.buttons"

    def test_play_pause_uses_direct_call(self):
        """action_play_pause deve chiamare _send_mpv_command direttamente quando disponibile."""
        import hw.buttons as btns
        orig_avail = btns._DIRECT_AVAILABLE
        orig_fn = btns._send_mpv_command
        try:
            btns._DIRECT_AVAILABLE = True
            mock_fn = MagicMock()
            btns._send_mpv_command = mock_fn
            btns.action_play_pause()
            mock_fn.assert_called_once_with(["cycle", "pause"])
        finally:
            btns._DIRECT_AVAILABLE = orig_avail
            btns._send_mpv_command = orig_fn

    def test_power_hold_uses_direct_standby(self):
        """action_power_hold è un no-op: lo standby avviene solo da pannello admin."""
        import hw.buttons as btns
        orig_avail = btns._DIRECT_AVAILABLE
        orig_fn = btns._perform_standby
        try:
            btns._DIRECT_AVAILABLE = True
            mock_fn = MagicMock()
            btns._perform_standby = mock_fn
            btns.action_power_hold()
            mock_fn.assert_not_called()
        finally:
            btns._DIRECT_AVAILABLE = orig_avail
            btns._perform_standby = orig_fn


# ===========================================================================
# 2) hw/rfid.py — usa chiamata diretta, fallback HTTP opzionale
# ===========================================================================

class TestRfidDirectCall:
    """Il worker RFID deve usare la chiamata Python diretta, non HTTP per default."""

    @classmethod
    def setup_class(cls):
        """Mock RPi.GPIO e mfrc522 prima di importare hw.rfid (richiede HW Raspberry Pi)."""
        import sys
        # Previene l'import di RPi.GPIO (non disponibile in CI)
        for mod in ("RPi", "RPi.GPIO", "mfrc522"):
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()
        # Forza il reload di hw.rfid con i mock in place (se già importato senza mock)
        if "hw.rfid" in sys.modules:
            del sys.modules["hw.rfid"]

    def test_direct_trigger_function_exists(self):
        """_trigger_rfid_direct deve essere definita in hw/rfid.py."""
        import hw.rfid as rfid_mod
        assert hasattr(rfid_mod, "_trigger_rfid_direct"), (
            "_trigger_rfid_direct non trovata in hw.rfid"
        )
        assert callable(rfid_mod._trigger_rfid_direct)

    def test_direct_trigger_calls_handle_rfid_trigger(self):
        """_trigger_rfid_direct deve delegare a handle_rfid_trigger se disponibile."""
        import hw.rfid as rfid_mod
        mock_fn = MagicMock(return_value=True)
        with patch("api.rfid.handle_rfid_trigger", mock_fn):
            result = rfid_mod._trigger_rfid_direct("TEST_UID")
        mock_fn.assert_called_once_with("TEST_UID")
        assert result is True

    def test_direct_trigger_returns_false_when_unavailable(self):
        """_trigger_rfid_direct deve ritornare False se il modulo non è disponibile."""
        import hw.rfid as rfid_mod
        with patch("builtins.__import__", side_effect=ImportError("no module")):
            result = rfid_mod._trigger_rfid_direct("TEST_UID")
        assert result is False

    def test_no_requests_import_at_module_level(self):
        """requests non deve essere importato al livello modulo di hw/rfid.py."""
        assert not _has_module_level_requests_import(ROOT / "hw" / "rfid.py"), (
            "import requests trovato al livello modulo di hw/rfid.py; "
            "deve stare solo dentro le funzioni di fallback"
        )

    def test_rfid_worker_checks_shutdown(self):
        """_rfid_worker deve rispettare is_shutdown_requested() e terminare."""
        import hw.rfid as rfid_mod
        # Con SimpleMFRC522=None, il worker esce subito per libreria mancante
        orig_simple = rfid_mod.SimpleMFRC522
        rfid_mod.SimpleMFRC522 = None
        try:
            with patch("hw.rfid.is_shutdown_requested", return_value=True):
                rfid_mod._rfid_worker()  # non deve bloccarsi
        finally:
            rfid_mod.SimpleMFRC522 = orig_simple


# ===========================================================================
# 3) core/event_log.py — append puro + trimming periodico
# ===========================================================================

class TestEventLogAppendOnly:
    """log_event deve usare _append_raw (non _write_raw) per ogni evento."""

    def setup_method(self):
        import core.event_log as _el
        fd, self._tmp = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        os.unlink(self._tmp)  # rimuovi subito: vogliamo che event_log lo crei fresco
        self._orig_file = _el._log_file
        self._orig_count = _el._append_count
        self._orig_approx = _el._approx_total
        self._orig_count_file = _el._append_count_for_file
        _el._log_file = self._tmp
        _el._append_count = 0
        _el._approx_total = 0
        _el._append_count_for_file = self._tmp

    def teardown_method(self):
        import core.event_log as _el
        _el._log_file = self._orig_file
        _el._append_count = self._orig_count
        _el._approx_total = self._orig_approx
        _el._append_count_for_file = self._orig_count_file
        if os.path.exists(self._tmp):
            os.remove(self._tmp)

    def test_log_event_calls_append_raw_not_write_raw(self):
        """log_event deve chiamare _append_raw (non _write_raw) sotto la soglia di trimming."""
        import core.event_log as _el
        with patch.object(_el, "_write_raw") as mock_write, \
             patch.object(_el, "_append_raw", wraps=_el._append_raw) as mock_append:
            _el.log_event("test", "info", "messaggio 1")
            _el.log_event("test", "info", "messaggio 2")
        # _append_raw deve essere chiamata per ogni evento
        assert mock_append.call_count == 2
        # _write_raw NON deve essere chiamata (nessun trim necessario con file piccolo)
        mock_write.assert_not_called()

    def test_log_event_appends_valid_json_lines(self):
        """Ogni evento deve essere una riga JSON valida nel file."""
        from core.event_log import log_event
        log_event("rfid", "info", "statuina appoggiata 🦉")
        log_event("battery", "warning", "batteria al 15% 🔋")
        with open(self._tmp, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)  # non solleva eccezione
            assert "ts" in obj
            assert "area" in obj
            assert "severity" in obj
            assert "message" in obj

    def test_trim_called_only_when_needed(self):
        """_trim_if_needed deve essere chiamata solo quando _approx_total > MAX_ENTRIES."""
        import core.event_log as _el
        from core.event_log import EVENT_LOG_TRIM_EVERY, EVENT_LOG_MAX_ENTRIES
        # Con pochi eventi (< MAX_ENTRIES) non si deve fare trim
        with patch.object(_el, "_trim_if_needed") as mock_trim:
            for i in range(EVENT_LOG_TRIM_EVERY):
                _el.log_event("test", "info", f"msg-{i}")
        # _approx_total è ancora piccolo → nessun trim
        mock_trim.assert_not_called()

    def test_trim_called_when_approx_total_exceeds_max(self):
        """_trim_if_needed deve essere chiamata quando _approx_total supera MAX_ENTRIES."""
        import core.event_log as _el
        from core.event_log import EVENT_LOG_TRIM_EVERY, EVENT_LOG_MAX_ENTRIES
        # Imposta il contatore come se il file fosse già quasi pieno
        _el._approx_total = EVENT_LOG_MAX_ENTRIES + 1
        _el._append_count = 0
        with patch.object(_el, "_trim_if_needed") as mock_trim:
            for i in range(EVENT_LOG_TRIM_EVERY):
                _el.log_event("test", "info", f"msg-{i}")
        mock_trim.assert_called_once()

    def test_append_raw_function_exists(self):
        """_append_raw deve essere una funzione pubblica del modulo."""
        from core.event_log import _append_raw
        assert callable(_append_raw)

    def test_trim_every_constant_is_reasonable(self):
        """EVENT_LOG_TRIM_EVERY deve essere > 1 per ridurre l'I/O."""
        from core.event_log import EVENT_LOG_TRIM_EVERY
        assert EVENT_LOG_TRIM_EVERY > 1, (
            f"EVENT_LOG_TRIM_EVERY={EVENT_LOG_TRIM_EVERY}; deve essere > 1 per ridurre l'I/O sulla SD"
        )


# ===========================================================================
# 4) core/utils.py — flag _shutdown_requested + is_shutdown_requested()
# ===========================================================================

class TestGracefulShutdown:
    """Il flag di shutdown deve essere accessibile a tutti i worker."""

    def test_request_shutdown_function_exists(self):
        from core.utils import request_shutdown
        assert callable(request_shutdown)

    def test_is_shutdown_requested_function_exists(self):
        from core.utils import is_shutdown_requested
        assert callable(is_shutdown_requested)

    def test_shutdown_flag_starts_false(self):
        import core.utils as utils_mod
        # Reset the event to ensure clean state
        utils_mod._shutdown_event.clear()
        try:
            assert utils_mod.is_shutdown_requested() is False
        finally:
            utils_mod._shutdown_event.clear()

    def test_request_shutdown_sets_flag(self):
        import core.utils as utils_mod
        utils_mod._shutdown_event.clear()
        try:
            utils_mod.request_shutdown()
            assert utils_mod.is_shutdown_requested() is True
        finally:
            utils_mod._shutdown_event.clear()

    def test_all_workers_import_is_shutdown_requested(self):
        """Tutti i moduli worker devono importare is_shutdown_requested."""
        worker_files = [
            ROOT / "hw" / "rfid.py",
            ROOT / "hw" / "battery.py",
            ROOT / "hw" / "led.py",
            ROOT / "core" / "media.py",
            ROOT / "core" / "hardware.py",
        ]
        for worker_path in worker_files:
            src = worker_path.read_text()
            assert "is_shutdown_requested" in src, (
                f"{worker_path.name} non usa is_shutdown_requested() — "
                "il worker non rispetta il graceful shutdown"
            )


# ===========================================================================
# 5 & 6) hw/battery.py — stato strutturato + rilevazione ricarica CRATE
# ===========================================================================

class TestBatteryStructuredState:
    """state["battery"] deve essere un dizionario strutturato, non chiavi flat."""

    def test_read_battery_returns_three_values(self):
        """read_battery_max17048 deve ritornare (percent, voltage, crate)."""
        import hw.battery as bat

        mock_bus = MagicMock()
        # SOC: 50% → 50.0 + 0/256
        mock_bus.read_i2c_block_data.side_effect = [
            [50, 0],     # REG_SOC → 50%
            [0x10, 0x0], # REG_VCELL → (0x100 >> 4) * 0.00125 = 0.5V circa
            [0x00, 0x10], # REG_CRATE → positivo (in carica)
        ]
        with patch("hw.battery.smbus2.SMBus") as mock_smbus:
            mock_smbus.return_value.__enter__ = MagicMock(return_value=mock_bus)
            mock_smbus.return_value.__exit__ = MagicMock(return_value=False)
            percent, voltage, crate = bat.read_battery_max17048()

        assert percent is not None
        assert voltage is not None
        # crate può essere None solo in caso di errore

    def test_read_battery_returns_none_on_error(self):
        """In caso di errore I2C deve ritornare (None, None, None)."""
        import hw.battery as bat
        with patch("hw.battery.smbus2.SMBus", side_effect=OSError("I2C error")):
            percent, voltage, crate = bat.read_battery_max17048()
        assert percent is None
        assert voltage is None
        assert crate is None

    def test_battery_watchdog_sets_structured_state(self):
        """Il watchdog deve aggiornare state["battery"] come dizionario strutturato."""
        import hw.battery as bat
        from core.state import state, bus

        # Simula una lettura singola di batteria e poi shutdown
        # is_shutdown_requested è importata via `from core.utils import is_shutdown_requested`
        # dentro _battery_watchdog(), quindi va patchata tramite core.utils
        shutdown_sequence = [False, True]  # primo ciclo esegue, secondo esce

        with patch("hw.battery.read_battery_max17048", return_value=(75.0, 3.85, 1.5)), \
             patch("core.utils.is_shutdown_requested", side_effect=shutdown_sequence), \
             patch("hw.battery.eventlet") as mock_ev, \
             patch("hw.battery.play_ai_notification"), \
             patch("core.database.log_battery_reading", create=True), \
             patch.object(bus, "mark_dirty"), \
             patch.object(bus, "request_emit"), \
             patch.object(bus, "emit_notification"):
            mock_ev.sleep = MagicMock()
            bat._battery_watchdog()

        # state["battery"] deve essere un dict strutturato
        batt = state.get("battery")
        assert isinstance(batt, dict), (
            f"state['battery'] deve essere un dict, trovato: {type(batt)}"
        )
        assert "percent" in batt, "Manca 'percent' in state['battery']"
        assert "voltage" in batt, "Manca 'voltage' in state['battery']"
        assert "charging" in batt, "Manca 'charging' in state['battery']"
        assert "status" in batt, "Manca 'status' in state['battery']"
        assert "updated_ts" in batt, "Manca 'updated_ts' in state['battery']"

    def test_battery_watchdog_no_flat_keys(self):
        """state NON deve avere chiavi flat battery_percent o battery_voltage."""
        import hw.battery as bat
        from core.state import state, bus

        # Rimuovi eventuali chiavi flat residue
        state.pop("battery_percent", None)
        state.pop("battery_voltage", None)

        shutdown_sequence = [False, True]
        with patch("hw.battery.read_battery_max17048", return_value=(80.0, 3.90, -0.5)), \
             patch("core.utils.is_shutdown_requested", side_effect=shutdown_sequence), \
             patch("hw.battery.eventlet") as mock_ev, \
             patch("hw.battery.play_ai_notification"), \
             patch("core.database.log_battery_reading", create=True), \
             patch.object(bus, "mark_dirty"), \
             patch.object(bus, "request_emit"), \
             patch.object(bus, "emit_notification"):
            mock_ev.sleep = MagicMock()
            bat._battery_watchdog()

        assert "battery_percent" not in state, (
            "state non deve avere la chiave flat 'battery_percent'"
        )
        assert "battery_voltage" not in state, (
            "state non deve avere la chiave flat 'battery_voltage'"
        )


class TestBatteryChargingDetection:
    """Il watchdog deve rilevare la ricarica tramite il registro CRATE del MAX17048."""

    def test_charging_detected_when_crate_positive(self):
        """CRATE positivo (>0.5) → charging=True nel dizionario batteria."""
        import hw.battery as bat
        from core.state import state, bus

        shutdown_sequence = [False, True]
        with patch("hw.battery.read_battery_max17048", return_value=(45.0, 3.75, 2.5)), \
             patch("core.utils.is_shutdown_requested", side_effect=shutdown_sequence), \
             patch("hw.battery.eventlet") as mock_ev, \
             patch("hw.battery.play_ai_notification"), \
             patch("core.database.log_battery_reading", create=True), \
             patch.object(bus, "mark_dirty"), \
             patch.object(bus, "request_emit"), \
             patch.object(bus, "emit_notification"):
            mock_ev.sleep = MagicMock()
            bat._battery_watchdog()

        batt = state.get("battery", {})
        assert batt.get("charging") is True, (
            "Con CRATE=2.5 (positivo), charging deve essere True"
        )
        assert batt.get("status") == "charging"

    def test_discharging_detected_when_crate_negative(self):
        """CRATE negativo → charging=False nel dizionario batteria."""
        import hw.battery as bat
        from core.state import state, bus

        shutdown_sequence = [False, True]
        with patch("hw.battery.read_battery_max17048", return_value=(50.0, 3.80, -3.0)), \
             patch("core.utils.is_shutdown_requested", side_effect=shutdown_sequence), \
             patch("hw.battery.eventlet") as mock_ev, \
             patch("hw.battery.play_ai_notification"), \
             patch("core.database.log_battery_reading", create=True), \
             patch.object(bus, "mark_dirty"), \
             patch.object(bus, "request_emit"), \
             patch.object(bus, "emit_notification"):
            mock_ev.sleep = MagicMock()
            bat._battery_watchdog()

        batt = state.get("battery", {})
        assert batt.get("charging") is False, (
            "Con CRATE=-3.0 (negativo), charging deve essere False"
        )

    def test_crate_register_constant_defined(self):
        """La costante REG_CRATE deve essere definita in hw/battery.py."""
        import hw.battery as bat
        assert hasattr(bat, "REG_CRATE"), "REG_CRATE non definita in hw/battery.py"
        assert bat.REG_CRATE == 0x16, f"REG_CRATE deve essere 0x16, trovato: {hex(bat.REG_CRATE)}"

    def test_charging_notification_played_on_connect(self):
        """Quando la batteria passa da scarica a in carica, deve suonare la notifica gufetto."""
        import hw.battery as bat
        from core.state import state, bus

        # Due cicli: prima in scarica, poi in carica
        crate_sequence = [-1.0, 2.0]
        call_count = [0]

        def mock_read():
            idx = min(call_count[0], len(crate_sequence) - 1)
            c = crate_sequence[idx]
            call_count[0] += 1
            return (60.0, 3.80, c)

        # 3 iterazioni: la prima in scarica, la seconda in carica (notifica), la terza esce
        shutdown_seq = [False, False, True]

        with patch("hw.battery.read_battery_max17048", side_effect=mock_read), \
             patch("core.utils.is_shutdown_requested", side_effect=shutdown_seq), \
             patch("hw.battery.eventlet") as mock_ev, \
             patch("hw.battery.play_ai_notification") as mock_notif, \
             patch("core.database.log_battery_reading", create=True), \
             patch.object(bus, "mark_dirty"), \
             patch.object(bus, "request_emit"), \
             patch.object(bus, "emit_notification"):
            mock_ev.sleep = MagicMock()
            bat._battery_watchdog()

        # La notifica di ricarica deve essere stata chiamata almeno una volta
        assert mock_notif.call_count >= 1, (
            "La notifica gufetto 'in ricarica' non è stata riprodotta"
        )


# ===========================================================================
# 7) core/media.py — _reset_media_runtime() deduplica il codice di reset
# ===========================================================================

class TestResetMediaRuntimeDeduplication:
    """_reset_media_runtime() deve essere definita e usata sia da stop_player che dal watchdog."""

    def test_reset_function_exists_and_callable(self):
        from core.media import _reset_media_runtime
        assert callable(_reset_media_runtime)

    def test_stop_player_uses_reset_function(self):
        """stop_player deve richiamare _reset_media_runtime (non duplicarne il codice)."""
        import inspect
        from core import media
        source = inspect.getsource(media.stop_player)
        assert "_reset_media_runtime" in source, (
            "stop_player non chiama _reset_media_runtime() — possibile duplicazione codice"
        )

    def test_watchdog_uses_reset_function(self):
        """_player_watchdog_loop deve richiamare _reset_media_runtime (non duplicarne il codice)."""
        import inspect
        from core import media
        source = inspect.getsource(media._player_watchdog_loop)
        assert "_reset_media_runtime" in source, (
            "_player_watchdog_loop non chiama _reset_media_runtime() — possibile duplicazione codice"
        )

    def test_reset_clears_player_running(self):
        from core import media
        from core.state import media_runtime
        media_runtime["player_running"] = True
        with patch.object(media.bus, "mark_dirty"), \
             patch.object(media.bus, "request_emit"):
            media._reset_media_runtime()
        assert media_runtime["player_running"] is False

    def test_reset_sets_mode_idle(self):
        from core import media
        from core.state import media_runtime
        media_runtime["player_mode"] = "audio_only"
        media_runtime["current_mode"] = "audio_only"
        with patch.object(media.bus, "mark_dirty"), \
             patch.object(media.bus, "request_emit"):
            media._reset_media_runtime()
        assert media_runtime["player_mode"] == "idle"
        assert media_runtime["current_mode"] == "idle"

    def test_reset_clears_playlist(self):
        from core import media
        from core.state import media_runtime
        media_runtime["current_playlist"] = ["/a/b.mp3", "/c/d.mp3"]
        media_runtime["playlist_index"] = 5
        with patch.object(media.bus, "mark_dirty"), \
             patch.object(media.bus, "request_emit"):
            media._reset_media_runtime()
        assert media_runtime["current_playlist"] == []
        assert media_runtime["playlist_index"] == 0


# ===========================================================================
# 8) Dockerfile — multi-stage build per il frontend Vue
# ===========================================================================

class TestDockerfileMultiStageBuild:
    """Il Dockerfile deve avere uno stage per il build del frontend Vue."""

    def test_dockerfile_exists(self):
        dockerfile = ROOT / "Dockerfile"
        assert dockerfile.exists(), "Dockerfile non trovato nella root del progetto"

    def test_dockerfile_has_frontend_stage(self):
        """Il Dockerfile deve avere uno stage AS frontend-builder (o simile)."""
        dockerfile_content = (ROOT / "Dockerfile").read_text()
        assert "FROM node" in dockerfile_content, (
            "Manca lo stage Node.js nel Dockerfile per buildare il frontend Vue"
        )
        assert "npm" in dockerfile_content, (
            "Manca npm install/run build nel Dockerfile"
        )

    def test_dockerfile_has_python_stage(self):
        """Il Dockerfile deve avere uno stage Python per il backend Flask."""
        dockerfile_content = (ROOT / "Dockerfile").read_text()
        assert "FROM python" in dockerfile_content, (
            "Manca lo stage Python nel Dockerfile per il backend"
        )

    def test_dockerfile_copies_frontend_dist(self):
        """Il Dockerfile deve copiare la build del frontend nello stage Python."""
        dockerfile_content = (ROOT / "Dockerfile").read_text()
        assert "frontend/dist" in dockerfile_content, (
            "Il Dockerfile non copia frontend/dist nello stage backend"
        )

    def test_dockerfile_exposes_port_5000(self):
        """Il server Flask deve essere esposto sulla porta 5000."""
        dockerfile_content = (ROOT / "Dockerfile").read_text()
        assert "EXPOSE 5000" in dockerfile_content, (
            "Il Dockerfile non espone la porta 5000"
        )
