"""Import the UI against inert GTK stand-ins; never initialize a display."""
import importlib.util
import sys
import threading
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


def load_main():
    gi = ModuleType('gi')
    gi.require_version = Mock()
    repository = ModuleType('gi.repository')
    repository.Gtk = SimpleNamespace(Window=object, main_quit=Mock())
    repository.Gdk = SimpleNamespace()
    repository.GLib = SimpleNamespace(idle_add=Mock(), timeout_add_seconds=Mock())
    spec = importlib.util.spec_from_file_location('tested_main', 'main.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'gi': gi, 'gi.repository': repository}):
        spec.loader.exec_module(module)
    return module


class MainTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main()
        self.ui = self.module.ScreenRecorder.__new__(self.module.ScreenRecorder)
        self.ui.lifecycle = SimpleNamespace(state='countdown', closed=False,
                                           cancel=Mock(), close=Mock(), started_at=None, token=0)
        self.ui.start_button = Mock()
        self.ui.status = Mock()
        self.ui.source_container = Mock()
        self.ui.audio = self.ui.fps = self.ui.quality = {'x': Mock()}
        self.ui.show_all = Mock()
        self.ui.hide = Mock()
        self.ui.monitors = []
        self.ui._monitor_pending = False
        self.ui._monitor_generation = 0

    def test_countdown_label_and_cancel(self):
        self.ui.update_button()
        self.ui.start_button.set_label.assert_called_with('Cancel Recording')
        self.ui.start_button.set_sensitive.assert_called_with(True)
        self.ui.on_record_clicked(None)
        self.ui.lifecycle.cancel.assert_called_once()

    def test_close_defers_quit_until_cleanup_callback(self):
        self.assertTrue(self.ui.on_close(None, None))
        self.ui.lifecycle.close.assert_called_once()
        self.module.Gtk.main_quit.assert_not_called()
        self.ui.on_lifecycle_state('closed', 'Closed', None)
        self.module.Gtk.main_quit.assert_called_once()

    def test_stale_monitor_results_do_not_update_busy_or_closed_ui(self):
        self.ui.refresh_monitors = Mock()
        for state in ('countdown', 'starting', 'recording', 'closed'):
            self.ui.lifecycle.state = state
            self.ui.finish_monitor_refresh(0, [{'id': 'DP-1'}])
        self.ui.refresh_monitors.assert_not_called()
        self.ui.lifecycle.state = 'idle'
        self.ui._monitor_generation = 2
        self.ui.finish_monitor_refresh(1, [{'id': 'DP-1'}])
        self.ui.refresh_monitors.assert_not_called()

    def test_monitor_detection_runs_off_caller_and_posts_guarded_result(self):
        entered, release = threading.Event(), threading.Event()
        threads = []
        actual_thread = threading.Thread
        def make_thread(**kwargs):
            thread = actual_thread(**kwargs)
            threads.append(thread)
            return thread
        def detect():
            entered.set()
            release.wait(2)
            return [{'id': 'DP-1'}]
        self.ui.lifecycle.state = 'idle'
        self.ui.refresh_monitors = Mock()
        with patch.object(self.module, 'get_connected_monitors', side_effect=detect), \
             patch.object(self.module.threading, 'Thread', side_effect=make_thread):
            self.assertTrue(self.ui.check_monitor_changes())
            self.assertTrue(entered.wait(2))
            self.assertFalse(threads[0].daemon)  # Close must not abandon xrandr reaping.
            self.ui.refresh_monitors.assert_not_called()
            self.assertTrue(self.ui._monitor_pending)
            self.ui.lifecycle.token += 1  # A session began before geometry returned.
            release.set()
            threads[0].join(2)
        args = self.module.GLib.idle_add.call_args.args
        args[0](*args[1:])
        self.ui.refresh_monitors.assert_not_called()
        self.assertFalse(self.ui._monitor_pending)

    def test_cleanup_failure_during_close_shows_retry_not_quit(self):
        self.ui.lifecycle.closed = True
        self.ui.lifecycle.state = 'cleanup_failed'
        self.ui.on_lifecycle_state('cleanup_failed', 'Cleanup error', None)
        self.ui.show_all.assert_called_once()
        self.ui.start_button.set_label.assert_called_with('Retry cleanup')
        self.module.Gtk.main_quit.assert_not_called()

    def test_elapsed_timer_warned_and_preserves_audio_status(self):
        self.ui.lifecycle.state = 'recording'
        self.ui.lifecycle.started_at = 10
        self.ui.recording_status = 'Recording... Audio: both'
        with patch.object(self.module.time, 'monotonic', return_value=71):
            self.ui.check_recording_status()
        self.ui.status.set_text.assert_called_with('REC 00:01:01 — Recording... Audio: both')

    def test_negative_monitor_offsets_parsed(self):
        result = Mock(stdout='Monitors: 1\n 0: +DP-1 101/1x99/1-100+20 DP-1\n')
        with patch.object(self.module.subprocess, 'run', return_value=result):
            monitors = self.module.get_connected_monitors()
        self.assertEqual((monitors[0]['x'], monitors[0]['y']), (-100, 20))
