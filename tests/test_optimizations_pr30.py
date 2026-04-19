"""
tests/test_optimizations_pr30.py — Test PR 30: ottimizzazioni architettura.

Copre:
  A) hw/buttons.py: chiamata Python diretta invece di HTTP
  B) core/media.py: _reset_media_runtime() deduplica stop_player e watchdog
  C) core/state.py: EventBus worker rispetta is_shutdown_requested()
  H) core/database.py: connection reuse threading.local() + WAL mode
  Standby) core/hardware.py: WiFi block/unblock, USB, CPU governor, standby_details
"""
import os
import sys
import time
import threading
import tempfile

import pytest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ===========================================================================
# B) core/media.py — _reset_media_runtime()
# ===========================================================================

class TestResetMediaRuntime:
    def test_reset_function_exists(self):
        from core.media import _reset_media_runtime
        assert callable(_reset_media_runtime)

    def test_reset_clears_all_fields(self):
        from core import media
        from core.state import media_runtime
        # Set some running state
        media_runtime["player_running"] = True
        media_runtime["player_mode"] = "audio_only"
        media_runtime["current_file"] = "/media/test.mp3"
        media_runtime["current_rfid_uid"] = "AA:BB"
        media_runtime["current_rfid"] = "AA:BB"
        media_runtime["current_profile_name"] = "profile"
        media_runtime["current_mode"] = "audio_only"
        media_runtime["current_media_path"] = "/media/test.mp3"
        media_runtime["current_playlist"] = ["/a", "/b"]
        media_runtime["playlist_index"] = 2

        with patch.object(media.bus, "mark_dirty"), \
             patch.object(media.bus, "request_emit"):
            media._reset_media_runtime()

        assert media_runtime["player_running"] is False
        assert media_runtime["player_mode"] == "idle"
        assert media_runtime["current_file"] is None
        assert media_runtime["current_rfid_uid"] is None
        assert media_runtime["current_rfid"] is None
        assert media_runtime["current_profile_name"] is None
        assert media_runtime["current_mode"] == "idle"
        assert media_runtime["current_media_path"] is None
        assert media_runtime["current_playlist"] == []
        assert media_runtime["playlist_index"] == 0

    def test_reset_calls_eventbus(self):
        from core import media
        with patch.object(media.bus, "mark_dirty") as mock_dirty, \
             patch.object(media.bus, "request_emit") as mock_emit:
            media._reset_media_runtime()
        mock_dirty.assert_called_once_with("media")
        mock_emit.assert_called_once_with("public")

    def test_stop_player_uses_reset(self):
        """stop_player deve richiamare _reset_media_runtime se player_running=True."""
        from core import media
        from core.state import media_runtime
        media_runtime["player_running"] = True

        with patch("core.media._save_resume_if_needed"), \
             patch("core.media._reset_media_runtime") as mock_reset, \
             patch.object(media.bus, "mark_dirty"), \
             patch.object(media.bus, "request_emit"):
            # Patch player_proc to be None (no process to terminate)
            media.player_proc = None
            media.stop_player()

        mock_reset.assert_called_once()


# ===========================================================================
# C) core/state.py — EventBus worker graceful shutdown
# ===========================================================================

class TestEventBusShutdown:
    def test_worker_calls_flush_on_shutdown(self):
        """Il worker deve fermarsi e chiamare _flush() quando shutdown è richiesto."""
        from core import state
        bus = state.bus
        calls = []

        original_flush = bus._flush
        def mock_flush():
            calls.append("flush")
        bus._flush = mock_flush

        # Simulate: shutdown already requested → loop body skips, final flush happens
        with patch("core.state.is_shutdown_requested", return_value=True), \
             patch("core.state.eventlet") as mock_ev:
            mock_ev.sleep = MagicMock()
            bus._worker()

        assert "flush" in calls  # last flush called
        bus._flush = original_flush  # restore

    def test_flush_method_exists(self):
        from core.state import bus
        assert hasattr(bus, "_flush")
        assert callable(bus._flush)


# ===========================================================================
# H) core/database.py — connection reuse + WAL mode
# ===========================================================================

class TestDatabaseConnectionReuse:
    def setup_method(self):
        import core.database as db_module
        from core.database import close_db
        close_db()  # reset thread-local state
        self._tmpdir = tempfile.mkdtemp()
        self._orig_db_path = db_module.DB_PATH
        db_module.DB_PATH = os.path.join(self._tmpdir, "test_conn_reuse.db")
        db_module.init_db()

    def teardown_method(self):
        import core.database as db_module
        from core.database import close_db
        close_db()
        db_module.DB_PATH = self._orig_db_path

    def test_same_thread_reuses_connection(self):
        """La stessa connessione deve essere ritornata nello stesso thread."""
        from core.database import _get_conn
        conn1 = _get_conn()
        conn2 = _get_conn()
        assert conn1 is conn2

    def test_wal_mode_enabled(self):
        """WAL journal mode deve essere attivato alla prima connessione."""
        from core.database import _get_conn
        conn = _get_conn()
        cur = conn.execute("PRAGMA journal_mode")
        mode = cur.fetchone()[0]
        assert mode == "wal"

    def test_close_db_resets_connection(self):
        """close_db() deve permettere la creazione di una nuova connessione."""
        from core.database import _get_conn, close_db
        conn1 = _get_conn()
        close_db()
        conn2 = _get_conn()
        # After close, a new connection is created
        assert conn1 is not conn2

    def test_close_db_function_exists(self):
        from core.database import close_db
        assert callable(close_db)

    def test_connection_path_change_resets(self):
        """Se DB_PATH cambia, la connessione viene ricreata."""
        import core.database as db_module
        from core.database import _get_conn, close_db
        conn1 = _get_conn()
        # Change DB_PATH
        new_path = os.path.join(self._tmpdir, "test_conn_new.db")
        db_module.DB_PATH = new_path
        db_module.init_db()
        conn2 = _get_conn()
        assert conn1 is not conn2


# ===========================================================================
# A) hw/buttons.py — chiamata Python diretta
# ===========================================================================

class TestButtonsDirectCall:
    def test_no_top_level_requests_import(self):
        """requests non deve essere importato al top-level di hw/buttons.py."""
        import ast, pathlib
        src = pathlib.Path(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "hw", "buttons.py")
        ).read_text()
        tree = ast.parse(src)
        top_imports = [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.Import, ast.ImportFrom))
            and any(
                (alias.name if isinstance(n, ast.Import) else n.module or "").startswith("requests")
                for alias in n.names
            )
            and isinstance(getattr(n, "col_offset", 0), int)
        ]
        # All 'import requests' must be inside function bodies, not at module level
        module_level = [n for n in top_imports if n.col_offset == 0]
        assert module_level == [], "import requests found at module level"

    def test_action_play_pause_direct_call(self):
        """action_play_pause deve chiamare _send_mpv_command direttamente."""
        import hw.buttons as btns
        original = btns._DIRECT_AVAILABLE
        original_fn = btns._send_mpv_command
        btns._DIRECT_AVAILABLE = True
        mock_fn = MagicMock()
        btns._send_mpv_command = mock_fn
        btns.action_play_pause()
        mock_fn.assert_called_once_with(["cycle", "pause"])
        btns._DIRECT_AVAILABLE = original
        btns._send_mpv_command = original_fn

    def test_action_next_direct_call(self):
        import hw.buttons as btns
        original = btns._DIRECT_AVAILABLE
        original_fn = btns._send_mpv_command
        btns._DIRECT_AVAILABLE = True
        mock_fn = MagicMock()
        btns._send_mpv_command = mock_fn
        btns.action_next()
        mock_fn.assert_called_once_with(["playlist-next"])
        btns._DIRECT_AVAILABLE = original
        btns._send_mpv_command = original_fn

    def test_action_prev_direct_call(self):
        import hw.buttons as btns
        original = btns._DIRECT_AVAILABLE
        original_fn = btns._send_mpv_command
        btns._DIRECT_AVAILABLE = True
        mock_fn = MagicMock()
        btns._send_mpv_command = mock_fn
        btns.action_prev()
        mock_fn.assert_called_once_with(["playlist-prev"])
        btns._DIRECT_AVAILABLE = original
        btns._send_mpv_command = original_fn

    def test_action_power_hold_direct_call(self):
        import hw.buttons as btns
        original = btns._DIRECT_AVAILABLE
        original_fn = btns._perform_standby
        btns._DIRECT_AVAILABLE = True
        mock_fn = MagicMock()
        btns._perform_standby = mock_fn
        # action_power_hold is now a no-op: verify _perform_standby is never called
        btns.action_power_hold()
        mock_fn.assert_not_called()
        btns._DIRECT_AVAILABLE = original
        btns._perform_standby = original_fn

    def test_action_power_press_calls_wake_when_in_standby(self):
        import hw.buttons as btns
        from unittest.mock import patch
        original = btns._DIRECT_AVAILABLE
        original_wake = btns._wake_from_standby
        btns._DIRECT_AVAILABLE = True
        mock_wake = MagicMock()
        btns._wake_from_standby = mock_wake
        # action_power_press uses core.hardware.get_standby_state() internally
        with patch("core.hardware.get_standby_state", return_value="standby"):
            btns.action_power_press()
        mock_wake.assert_called_once()
        btns._DIRECT_AVAILABLE = original
        btns._wake_from_standby = original_wake

    def test_action_power_press_no_wake_when_awake(self):
        import hw.buttons as btns
        from unittest.mock import patch
        original = btns._DIRECT_AVAILABLE
        original_wake = btns._wake_from_standby
        original_run = btns._run_cmd
        btns._DIRECT_AVAILABLE = True
        mock_wake = MagicMock()
        mock_run = MagicMock()
        btns._wake_from_standby = mock_wake
        btns._run_cmd = mock_run
        # action_power_press uses core.hardware.get_standby_state() internally
        with patch("core.hardware.get_standby_state", return_value="awake"):
            btns.action_power_press()
        mock_wake.assert_not_called()
        btns._DIRECT_AVAILABLE = original
        btns._wake_from_standby = original_wake
        btns._run_cmd = original_run

    def test_action_volume_up_respects_parental_control(self):
        """action_volume_up non deve superare parental_control.max_volume."""
        import hw.buttons as btns
        original = btns._DIRECT_AVAILABLE
        btns._DIRECT_AVAILABLE = True
        mock_runtime = {"current_volume": 75}
        mock_state = {"parental_control": {"max_volume": 80}}
        mock_run = MagicMock()
        btns._media_runtime = mock_runtime
        btns._state = mock_state
        btns._run_cmd = mock_run
        btns.action_volume_up()
        # 75 + 5 = 80, equals max_volume → allowed
        mock_run.assert_called_with(["amixer", "sset", "Master", "80%"])
        assert mock_runtime["current_volume"] == 80
        btns._DIRECT_AVAILABLE = original

    def test_action_volume_up_capped_at_parental_max(self):
        """action_volume_up non deve superare parental_control.max_volume."""
        import hw.buttons as btns
        original = btns._DIRECT_AVAILABLE
        btns._DIRECT_AVAILABLE = True
        mock_runtime = {"current_volume": 78}
        mock_state = {"parental_control": {"max_volume": 80}}
        mock_run = MagicMock()
        btns._media_runtime = mock_runtime
        btns._state = mock_state
        btns._run_cmd = mock_run
        btns.action_volume_up()
        # 78 + 5 = 83 > 80 → capped to 80
        mock_run.assert_called_with(["amixer", "sset", "Master", "80%"])
        assert mock_runtime["current_volume"] == 80
        btns._DIRECT_AVAILABLE = original

    def test_action_volume_down_direct_call(self):
        import hw.buttons as btns
        original = btns._DIRECT_AVAILABLE
        btns._DIRECT_AVAILABLE = True
        mock_runtime = {"current_volume": 20}
        mock_state = {}
        mock_run = MagicMock()
        btns._media_runtime = mock_runtime
        btns._state = mock_state
        btns._run_cmd = mock_run
        btns.action_volume_down()
        mock_run.assert_called_with(["amixer", "sset", "Master", "15%"])
        assert mock_runtime["current_volume"] == 15
        btns._DIRECT_AVAILABLE = original

    def test_gpio_pins_unchanged(self):
        """I pin GPIO devono restare quelli della scheda tecnica 2026."""
        import hw.buttons as btns
        assert btns.PIN_PLAY_PAUSE == 5
        assert btns.PIN_NEXT == 6
        assert btns.PIN_PREV == 13
        assert btns.PIN_POWER == 3


# ===========================================================================
# Standby — core/hardware.py
# ===========================================================================

class TestStandbyDetails:
    def setup_method(self):
        import core.hardware as hw
        hw._standby_state = hw.STANDBY_AWAKE
        hw._standby_details.update({
            "in_standby": False,
            "state": hw.STANDBY_AWAKE,
            "wifi_blocked": False,
            "usb_suspended": False,
            "hdmi_off": False,
            "cpu_governor": None,
            "previous_governor": None,
            "entered_ts": None,
            "last_wake_reason": None,
        })

    def test_get_standby_details_returns_dict(self):
        from core.hardware import get_standby_details
        details = get_standby_details()
        assert isinstance(details, dict)
        assert "in_standby" in details
        assert "state" in details
        assert "wifi_blocked" in details
        assert "usb_suspended" in details
        assert "hdmi_off" in details
        assert "cpu_governor" in details
        assert "previous_governor" in details
        assert "entered_ts" in details
        assert "last_wake_reason" in details

    def test_get_standby_details_is_copy(self):
        """get_standby_details deve ritornare una copia, non il riferimento interno."""
        from core.hardware import get_standby_details, _standby_details
        details = get_standby_details()
        details["in_standby"] = "modified"
        assert _standby_details["in_standby"] != "modified"

    def test_perform_standby_sets_details(self):
        import core.hardware as hw
        with patch("core.hardware.run_cmd", return_value=(0, "", "")), \
             patch("core.hardware.amp_off"), \
             patch("core.hardware.eventlet") as mock_ev, \
             patch("core.media.stop_player"), \
             patch("hw.battery.play_ai_notification"), \
             patch.object(hw.bus, "emit_notification"), \
             patch.object(hw.bus, "request_emit"), \
             patch.object(hw.bus, "mark_dirty"), \
             patch("core.hardware._get_current_governor", return_value="ondemand"), \
             patch("core.hardware._block_wifi", return_value=True), \
             patch("core.hardware._suspend_usb", return_value=True):
            mock_ev.sleep = MagicMock()
            hw.perform_standby()

        details = hw._standby_details
        assert details["in_standby"] is True
        assert details["state"] == hw.STANDBY_STANDBY
        assert details["previous_governor"] == "ondemand"
        assert details["cpu_governor"] == "powersave"
        assert details["wifi_blocked"] is True
        assert details["usb_suspended"] is True
        assert details["hdmi_off"] is True
        assert details["entered_ts"] is not None

    def test_wake_from_standby_clears_details(self):
        import core.hardware as hw
        hw._standby_state = hw.STANDBY_STANDBY
        hw._standby_details.update({
            "in_standby": True,
            "state": hw.STANDBY_STANDBY,
            "wifi_blocked": True,
            "usb_suspended": True,
            "previous_governor": "ondemand",
        })
        with patch("core.hardware.run_cmd", return_value=(0, "", "")), \
             patch("core.hardware.amp_on"), \
             patch("core.hardware._unblock_wifi"), \
             patch("core.hardware._resume_usb"), \
             patch("core.hardware._set_governor"), \
             patch("hw.battery.play_ai_notification"), \
             patch.object(hw.bus, "mark_dirty"), \
             patch.object(hw.bus, "request_emit"):
            hw.wake_from_standby(reason="button")

        assert hw._standby_details["in_standby"] is False
        assert hw._standby_details["state"] == hw.STANDBY_AWAKE
        assert hw._standby_details["last_wake_reason"] == "button"

    def test_wake_from_standby_restores_governor(self):
        import core.hardware as hw
        hw._standby_state = hw.STANDBY_STANDBY
        hw._standby_details["previous_governor"] = "performance"
        hw._standby_details["wifi_blocked"] = False
        hw._standby_details["usb_suspended"] = False

        with patch("core.hardware.run_cmd", return_value=(0, "", "")), \
             patch("core.hardware.amp_on"), \
             patch("core.hardware._set_governor") as mock_gov, \
             patch("hw.battery.play_ai_notification"), \
             patch.object(hw.bus, "mark_dirty"), \
             patch.object(hw.bus, "request_emit"):
            hw.wake_from_standby()

        mock_gov.assert_called_with("performance")

    def test_public_snapshot_includes_standby_details(self):
        from core.state import build_public_snapshot
        from core.hardware import get_standby_details
        with patch("core.state.bus") as mock_bus:
            mock_bus.cached_public_json = None
            snap = build_public_snapshot()
        assert "standby_details" in snap

    def test_is_wifi_only_interface_wlan(self):
        """_is_wifi_only_interface ritorna True se wlan nell'output di ip route."""
        import core.hardware as hw
        with patch("core.hardware.run_cmd", return_value=(0, "10.0.0.1 via 192.168.1.1 dev wlan0", "")):
            assert hw._is_wifi_only_interface() is True

    def test_is_wifi_only_interface_eth(self):
        """_is_wifi_only_interface ritorna False se eth nell'output."""
        import core.hardware as hw
        with patch("core.hardware.run_cmd", return_value=(0, "10.0.0.1 via 192.168.1.1 dev eth0", "")):
            assert hw._is_wifi_only_interface() is False

    def test_block_wifi_skips_if_only_interface(self):
        import core.hardware as hw
        with patch("core.hardware._is_wifi_only_interface", return_value=True), \
             patch("core.hardware.run_cmd") as mock_run:
            result = hw._block_wifi()
        assert result is False
        mock_run.assert_not_called()

    def test_suspend_usb_skips_if_path_missing(self):
        import core.hardware as hw
        original = hw._USB_POWER_PATH
        hw._USB_POWER_PATH = "/nonexistent/path/power/control"
        result = hw._suspend_usb()
        hw._USB_POWER_PATH = original
        assert result is False
