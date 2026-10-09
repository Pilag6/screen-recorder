"""Import the UI against inert GTK stand-ins; never initialize a display."""
import importlib.util
import sys
import threading
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace

from engine.lifecycle import SavedRecording
from unittest.mock import Mock, patch


class InertApplication:
    def __init__(self, **kwargs):
        self.application_id = kwargs.get('application_id')
        self.add_window = Mock()
        self.quit = Mock()


def load_main(gtk=None, pixbuf=None):
    gi = ModuleType('gi')
    gi.require_version = Mock()
    repository = ModuleType('gi.repository')
    repository.Gtk = gtk or SimpleNamespace(Window=object, Application=InertApplication,
                                            main_quit=Mock())
    repository.Gdk = SimpleNamespace()
    repository.GLib = SimpleNamespace(idle_add=Mock(), timeout_add_seconds=Mock(),
                                      Error=RuntimeError)
    repository.GdkPixbuf = pixbuf or SimpleNamespace(
        Pixbuf=SimpleNamespace(new_from_file_at_scale=Mock()))
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
        self.application = Mock()
        self.ui.get_application = Mock(return_value=self.application)
        self.ui.show_all = Mock()
        self.ui.hide = Mock()
        self.ui.iconify = Mock()
        self.ui.set_title = Mock()
        self.ui.notifier = Mock()
        self.ui._iconified_token = None
        self.ui._notified_token = None
        self.ui.lifecycle.completion = None
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
        self.application.quit.assert_not_called()
        self.ui.lifecycle.state = 'closed'
        self.ui.on_lifecycle_state('closed', 'Closed', None)
        self.application.quit.assert_called_once()

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
        self.application.quit.assert_not_called()

    def test_elapsed_timer_warned_and_preserves_audio_status(self):
        self.ui.lifecycle.state = 'recording'
        self.ui.lifecycle.started_at = 10
        self.ui.recording_status = 'Recording... Audio: both'
        with patch.object(self.module.time, 'monotonic', return_value=71):
            self.ui.check_recording_status()
        self.ui.status.set_text.assert_called_with('REC 00:01:01 — Recording... Audio: both')

    def test_recording_title_tracks_elapsed_timer_and_preserves_status(self):
        self.ui.lifecycle.state = 'recording'
        self.ui.lifecycle.started_at = 10
        self.ui.lifecycle.indicator_reason = 'REC helper available'
        with patch.object(self.module.time, 'monotonic', return_value=10):
            self.ui.on_lifecycle_state('recording', 'Recording... Audio: both')
        self.ui.set_title.assert_called_with('REC 00:00:00 — Screen Recorder')
        for now, elapsed in ((71, '00:01:01'), (3671, '01:01:01'), (9, '00:00:00')):
            with self.subTest(now=now), \
                 patch.object(self.module.time, 'monotonic', return_value=now):
                self.assertTrue(self.ui.check_recording_status())
                self.ui.set_title.assert_called_with(f'REC {elapsed} — Screen Recorder')
                self.ui.status.set_text.assert_called_with(
                    f'REC {elapsed} — Recording... Audio: both'
                )
        self.ui.notifier.notify_saved.assert_not_called()

    def test_nonrecording_states_reset_title_and_timer_does_not_restore_rec(self):
        for state in ('selecting', 'countdown', 'starting', 'stopping',
                      'cleanup_failed', 'idle', 'closed'):
            with self.subTest(state=state):
                self.ui.lifecycle.state = 'recording'
                self.ui.lifecycle.started_at = 10
                self.ui.lifecycle.indicator_reason = 'REC'
                with patch.object(self.module.time, 'monotonic', return_value=71):
                    self.ui.on_lifecycle_state('recording', 'Recording')
                self.ui.set_title.reset_mock()
                self.ui.lifecycle.state = state
                self.ui.on_lifecycle_state(state, state)
                self.ui.set_title.assert_called_with('Screen Recorder')
                self.ui.set_title.reset_mock()
                self.ui.check_recording_status()
                self.ui.set_title.assert_not_called()

    def test_fallback_title_and_tooltip_do_not_reiconify_restored_window(self):
        self.ui.lifecycle.state = 'recording'
        self.ui.lifecycle.started_at = 10
        for reason in ('REC helper absent', 'REC launch failed', 'REC exited (1)'):
            with self.subTest(reason=reason):
                self.ui.lifecycle.token += 1
                self.ui.lifecycle.indicator_reason = reason
                self.ui.iconify.reset_mock()
                with patch.object(self.module.time, 'monotonic', return_value=10):
                    self.ui.on_lifecycle_state('recording', 'Recording — REC fallback')
                self.ui.iconify.assert_called_once()
                # The user restored the window before a repeated fallback callback.
                with patch.object(self.module.time, 'monotonic', return_value=71):
                    self.ui.on_lifecycle_state('recording', 'Recording — REC fallback')
                self.ui.iconify.assert_called_once()
                self.ui.set_title.assert_called_with('REC 00:01:01 — Screen Recorder')
                tooltip = self.ui.status.set_tooltip_text.call_args.args[0]
                self.assertIn(reason, tooltip)
                self.assertIn('window title', tooltip.lower())
                self.assertIn('restore', tooltip.lower())
                self.assertIn('stop recording', tooltip.lower())
        self.ui.show_all.assert_not_called()
        self.ui.hide.assert_not_called()
        self.ui.notifier.notify_saved.assert_not_called()
        self.ui.on_record_clicked(None)
        self.ui.lifecycle.cancel.assert_called_once()

    def test_recording_iconifies_once_without_hiding_or_representing(self):
        self.ui.lifecycle.token = 1
        self.ui.lifecycle.indicator_reason = 'REC'
        for state in ('selecting', 'countdown', 'starting'):
            self.ui.lifecycle.state = state
            self.ui.on_lifecycle_state(state, state)
        self.ui.iconify.assert_not_called()
        self.ui.show_all.reset_mock()
        self.ui.hide.reset_mock()
        self.ui.lifecycle.state = 'recording'
        self.ui.on_lifecycle_state('recording', 'Recording')
        self.ui.on_lifecycle_state('recording', 'Overlay fallback')
        self.ui.iconify.assert_called_once()
        self.ui.show_all.assert_not_called()
        self.ui.hide.assert_not_called()
        self.ui.on_record_clicked(None)  # Restored window still permits Stop.
        self.ui.lifecycle.cancel.assert_called_once()
        self.ui.lifecycle.token = 2
        self.ui.on_lifecycle_state('recording', 'Recording again')
        self.assertEqual(self.ui.iconify.call_count, 2)

    def test_notifications_require_metadata_and_existing_file(self):
        self.ui.lifecycle.state = 'idle'
        with patch('pathlib.Path.is_file', return_value=True):
            self.ui.on_lifecycle_state('idle', 'Saved: fake.mkv', Path('fake.mkv'))
            self.ui.notifier.notify_saved.assert_not_called()
            self.ui.lifecycle.completion = SavedRecording(1, Path('real.mkv'))
            self.ui.on_lifecycle_state('idle', 'Anything', Path('fake.mkv'))
            self.ui.on_lifecycle_state('idle', 'Duplicate')
        self.ui.notifier.notify_saved.assert_called_once_with(Path('real.mkv'), allow_actions=True)
        self.ui.lifecycle.completion = SavedRecording(2, Path('gone.mkv'))
        with patch('pathlib.Path.is_file', return_value=False):
            self.ui.on_lifecycle_state('idle', 'Saved')
        self.assertEqual(self.ui.notifier.notify_saved.call_count, 1)
        self.ui.lifecycle.state = 'countdown'
        self.ui.on_lifecycle_state('idle', 'Stale completion')
        self.assertEqual(self.ui.notifier.notify_saved.call_count, 1)

    def test_stale_recording_dispatch_and_file_recheck_error_are_inert(self):
        self.ui.lifecycle.state = 'stopping'
        self.ui.on_lifecycle_state('recording', 'Stale REC')
        self.ui.iconify.assert_not_called()
        self.ui.show_all.assert_not_called()
        self.ui.set_title.assert_not_called()
        self.ui.lifecycle.completion = SavedRecording(1, Path('real.mkv'))
        for state in ('stopping', 'cleanup_failed'):
            self.ui.lifecycle.state = state
            self.ui.on_lifecycle_state(state, 'Saved: misleading.mkv')
        self.ui.notifier.notify_saved.assert_not_called()
        self.ui.lifecycle.state = 'idle'
        with patch('pathlib.Path.is_file', side_effect=OSError('unavailable')):
            self.ui.on_lifecycle_state('idle', 'Saved')
        self.ui.notifier.notify_saved.assert_not_called()

    def test_close_notification_precedes_quit_and_has_no_action(self):
        calls = []
        self.ui.lifecycle.closed = True
        self.ui.lifecycle.state = 'closed'
        self.ui.lifecycle.completion = SavedRecording(1, Path('real.mkv'))
        self.ui.notifier.close.side_effect = lambda: calls.append('disarm')
        self.ui.notifier.notify_saved.side_effect = lambda *a, **kw: calls.append('notify')
        self.application.quit.side_effect = lambda: calls.append('quit')
        with patch('pathlib.Path.is_file', return_value=True):
            self.ui.on_lifecycle_state('closed', 'Saved')
        self.assertEqual(calls, ['disarm', 'notify', 'quit'])
        self.ui.notifier.notify_saved.assert_called_once_with(Path('real.mkv'), allow_actions=False)

    def test_negative_monitor_offsets_parsed(self):
        result = Mock(stdout='Monitors: 1\n 0: +DP-1 101/1x99/1-100+20 DP-1\n')
        with patch.object(self.module.subprocess, 'run', return_value=result):
            monitors = self.module.get_connected_monitors()
        self.assertEqual((monitors[0]['x'], monitors[0]['y']), (-100, 20))


class InertWidget:
    """Enough container behavior for construction without a GTK display."""
    def __init__(self, **kwargs):
        self.children = []

    def __getattr__(self, name):
        method = Mock()
        setattr(self, name, method)
        return method

    def pack_start(self, child, *args):
        self.children.append(child)

    def get_children(self):
        return list(self.children)

    def remove(self, child):
        self.children.remove(child)


class InertRadio(InertWidget):
    def __init__(self, first=None):
        super().__init__()
        self.group = first.group if first is not None else []
        self.active = first is None  # GTK implicitly activates the first button.
        self.handlers = []
        self.group.append(self)

    @classmethod
    def new_with_label(cls, first, text):
        return cls(first)

    new_with_label_from_widget = new_with_label

    def connect(self, signal, callback, *args):
        assert signal in ('toggled', 'clicked')
        self.handlers.append((signal, callback, args))

    def disconnect_by_func(self, callback):
        self.handlers = [(signal, handler, args)
                         for signal, handler, args in self.handlers
                         if handler != callback]

    def get_active(self):
        return self.active

    def emit_toggled(self):
        for signal, callback, args in self.handlers:
            if signal == 'toggled':
                callback(self, *args)

    def emit_clicked(self):
        for signal, callback, args in self.handlers:
            if signal == 'clicked':
                callback(self, *args)

    def clicked(self):
        self.set_active(True)
        self.emit_clicked()

    def set_active(self, active):
        if self.active == active:
            return
        if active:
            for button in self.group:
                if button.active:
                    button.active = False
                    button.emit_toggled()
        self.active = active
        self.emit_toggled()


def construction_gtk():
    return SimpleNamespace(
        Window=InertWidget, Application=InertApplication,
        Box=InertWidget, Grid=InertWidget, Label=InertWidget,
        Button=InertWidget, Separator=InertWidget, RadioButton=InertRadio,
        HeaderBar=InertWidget,
        Image=SimpleNamespace(new_from_pixbuf=Mock(return_value=InertWidget())),
        Orientation=SimpleNamespace(VERTICAL=0, HORIZONTAL=1),
        WindowPosition=SimpleNamespace(CENTER=0),
    )


class MainPreferencesTests(unittest.TestCase):
    def setUp(self):
        from preferences import Preferences
        self.Preferences = Preferences
        self.pixbuf_loader = Mock()
        self.module = load_main(construction_gtk(), SimpleNamespace(
            Pixbuf=SimpleNamespace(new_from_file_at_scale=self.pixbuf_loader)))
        self.module.Gdk.EventMask = SimpleNamespace(ENTER_NOTIFY_MASK=1,
                                                    LEAVE_NOTIFY_MASK=2)
        self.module.GLib.markup_escape_text = lambda text: text
        self.saved = Preferences(source='DP-1', audio='mic', fps=60, quality='normal')
        self.load = patch.object(self.module, 'load_preferences',
                                 return_value=self.saved, create=True)
        self.save = patch.object(self.module, 'save_preferences',
                                 return_value=True, create=True)
        self.loader = self.load.start()
        self.saver = self.save.start()
        self.addCleanup(self.load.stop)
        self.addCleanup(self.save.stop)
        # Construction cannot create an engine/notifier with device side effects.
        self.engine = patch.object(self.module, 'RecordingEngine')
        self.notifier = patch.object(self.module, 'DesktopNotifier')
        self.engine.start()
        self.notifier.start()
        self.addCleanup(self.engine.stop)
        self.addCleanup(self.notifier.stop)
        self.ui = self.module.ScreenRecorder()

    def monitors(self):
        return [{'id': 'DP-1', 'label': 'DisplayPort'}]

    def test_constructor_installs_native_header_with_scaled_left_icon(self):
        self.ui.set_titlebar.assert_called_once()
        header = self.ui.set_titlebar.call_args.args[0]
        header.set_title.assert_called_once_with('Screen Recorder')
        header.set_show_close_button.assert_called_once_with(True)
        header.set_decoration_layout.assert_called_once_with(':minimize,close')
        expected_path = Path(self.module.__file__).resolve().parent / 'assets/screen-recorder-icon.png'
        self.pixbuf_loader.assert_called_once_with(str(expected_path), 28, 28, True)
        self.module.Gtk.Image.new_from_pixbuf.assert_called_once_with(
            self.pixbuf_loader.return_value)
        self.assertEqual(header.get_children(),
                         [self.module.Gtk.Image.new_from_pixbuf.return_value])
        self.ui.connect.assert_called_once_with('delete-event', self.ui.on_close)
        self.saver.assert_not_called()

    def test_header_icon_is_resolved_from_module_not_working_directory(self):
        self.pixbuf_loader.reset_mock()
        with patch.object(self.module, '__file__', '/opt/screen-recorder/main.py'):
            self.ui.create_header_bar()
        self.pixbuf_loader.assert_called_once_with(
            '/opt/screen-recorder/assets/screen-recorder-icon.png', 28, 28, True)

    def test_missing_or_corrupt_header_icon_does_not_block_startup(self):
        for error in (self.module.GLib.Error('missing icon'),
                      self.module.GLib.Error('corrupt icon'), OSError('unreadable')):
            with self.subTest(error=error):
                self.pixbuf_loader.side_effect = error
                ui = self.module.ScreenRecorder()
                ui.set_titlebar.assert_called_once()
                header = ui.set_titlebar.call_args.args[0]
                header.set_title.assert_called_once_with('Screen Recorder')
                header.set_show_close_button.assert_called_once_with(True)
                header.set_decoration_layout.assert_called_once_with(':minimize,close')
                self.assertEqual(header.get_children(), [])
                self.assertEqual(ui.get_selected(ui.audio), 'mic')
                ui.connect.assert_called_once_with('delete-event', ui.on_close)
        self.saver.assert_not_called()

    def test_constructor_restores_static_values_without_saving_implicit_activation(self):
        self.loader.assert_called_once_with()
        self.assertEqual(self.ui.get_selected(self.ui.audio), 'mic')
        self.assertEqual(self.ui.get_selected(self.ui.fps), '60')
        self.assertEqual(self.ui.get_selected(self.ui.quality), 'normal')
        self.assertEqual(self.ui.get_selected(self.ui.source), 'region')
        self.saver.assert_not_called()

    def test_default_constructor_keeps_existing_defaults_without_saving(self):
        self.loader.return_value = self.Preferences()
        ui = self.module.ScreenRecorder()
        for group, expected in ((ui.source, 'region'), (ui.audio, 'both'),
                                (ui.fps, '30'), (ui.quality, 'high')):
            self.assertEqual(ui.get_selected(group), expected)
        self.saver.assert_not_called()

    def test_async_initial_detection_restores_connector_without_saving(self):
        self.ui._monitor_pending = True
        self.ui._monitor_generation = 1
        self.ui.finish_monitor_refresh(1, self.monitors(), self.ui.lifecycle.token)
        self.assertEqual(self.ui.get_selected(self.ui.source), 'DP-1')
        self.assertFalse(self.ui._monitor_pending)
        self.saver.assert_not_called()

    def test_disconnected_source_survives_other_changes_and_reconnect(self):
        self.ui.refresh_monitors(self.monitors())
        self.ui.refresh_monitors([])
        self.assertEqual(self.ui.get_selected(self.ui.source), 'region')
        self.ui.audio['none'].set_active(True)
        self.saver.assert_called_once_with(
            self.Preferences(source='DP-1', audio='none', fps=60, quality='normal'))
        self.ui.refresh_monitors(self.monitors())
        self.assertEqual(self.ui.get_selected(self.ui.source), 'DP-1')
        self.assertEqual(self.saver.call_count, 1)

    def test_change_before_initial_detection_keeps_preferred_connector(self):
        self.ui.audio['system'].set_active(True)
        self.saver.assert_called_once_with(
            self.Preferences(source='DP-1', audio='system', fps=60, quality='normal'))
        self.ui.finish_monitor_refresh(0, self.monitors(), self.ui.lifecycle.token)
        self.assertEqual(self.ui.get_selected(self.ui.source), 'DP-1')
        self.assertEqual(self.saver.call_count, 1)

    def test_click_already_active_fallback_replaces_preference_and_stays_region(self):
        region = self.ui.source['region']
        self.assertTrue(region.get_active())
        region.clicked()
        self.saver.assert_called_once_with(
            self.Preferences(audio='mic', fps=60, quality='normal'))
        region.clicked()
        self.assertEqual(self.saver.call_count, 1)
        self.ui.refresh_monitors(self.monitors())
        self.assertEqual(self.ui.get_selected(self.ui.source), 'region')
        self.assertEqual(self.saver.call_count, 1)

    def test_source_click_saves_once_and_inactive_click_signal_is_ignored(self):
        self.ui.refresh_monitors(self.monitors())
        self.ui.source['region'].emit_clicked()
        self.saver.assert_not_called()
        self.ui.source['region'].clicked()
        self.saver.assert_called_once_with(
            self.Preferences(audio='mic', fps=60, quality='normal'))
        self.ui.source['DP-1'].clicked()
        self.assertEqual(self.saver.call_count, 2)
        self.assertEqual(self.saver.call_args.args[0].source, 'DP-1')

    def test_retired_fallback_click_cannot_change_preferences(self):
        old_region = self.ui.source['region']
        self.ui.refresh_monitors(self.monitors())
        old_region.clicked()
        self.saver.assert_not_called()
        self.ui.audio['none'].set_active(True)
        self.assertEqual(self.saver.call_args.args[0].source, 'DP-1')

    def test_explicit_source_selection_replaces_preference(self):
        self.ui.refresh_monitors(self.monitors())
        self.ui.source['region'].set_active(True)
        self.saver.assert_called_once_with(
            self.Preferences(audio='mic', fps=60, quality='normal'))
        self.ui.refresh_monitors([])
        self.ui.refresh_monitors(self.monitors())
        self.assertEqual(self.ui.get_selected(self.ui.source), 'region')
        self.ui.source['DP-1'].set_active(True)
        self.assertEqual(self.saver.call_count, 2)
        self.assertEqual(self.saver.call_args.args[0].source, 'DP-1')

    def test_each_active_selection_saves_immediately_and_inactive_is_ignored(self):
        self.ui.audio['mic'].set_active(False)
        self.saver.assert_not_called()
        self.ui.audio['system'].set_active(True)
        self.ui.fps['30'].set_active(True)
        self.ui.quality['high'].set_active(True)
        self.assertEqual(self.saver.call_count, 3)
        self.assertEqual(self.saver.call_args.args[0],
                         self.Preferences(source='DP-1', audio='system', fps=30))
        self.assertIs(type(self.saver.call_args.args[0].fps), int)

    def test_rebuild_ignores_old_group_activation_during_teardown(self):
        self.ui.refresh_monitors(self.monitors())
        old_region = self.ui.source['region']
        remove = self.ui.source_container.remove

        def teardown(child):
            # GTK can change an old radio group's active member on destruction.
            old_region.set_active(True)
            remove(child)

        with patch.object(self.ui.source_container, 'remove', side_effect=teardown):
            self.ui.refresh_monitors([])
        self.saver.assert_not_called()
        self.ui.audio['none'].set_active(True)
        self.assertEqual(self.saver.call_args.args[0].source, 'DP-1')

    def test_rebuilds_never_save_and_failure_does_not_block_next_change(self):
        for monitors in (self.monitors(), [], self.monitors()):
            self.ui.refresh_monitors(monitors)
        self.saver.assert_not_called()
        self.saver.return_value = False
        self.ui.audio['none'].set_active(True)
        self.assertEqual(self.ui.get_selected(self.ui.audio), 'none')
        self.ui.quality['high'].set_active(True)
        self.assertEqual(self.saver.call_count, 2)


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.module = load_main()
        self.window = Mock()
        self.window.lifecycle = SimpleNamespace(state='idle', closed=False, token=7)
        self.factory = patch.object(self.module, 'ScreenRecorder', return_value=self.window)
        self.factory_mock = self.factory.start()
        self.addCleanup(self.factory.stop)
        self.application = self.module.ScreenRecorderApplication()

    def test_application_id_is_stable_and_window_creation_is_lazy(self):
        self.assertEqual(self.application.application_id,
                         'io.github.screenrecorder.ScreenRecorder')
        self.factory_mock.assert_not_called()
        self.application.add_window.assert_not_called()
        self.application.do_activate()
        self.factory_mock.assert_called_once_with()
        self.application.add_window.assert_called_once_with(self.window)

    def test_repeated_activation_restores_and_presents_same_window(self):
        for _ in range(3):
            self.application.do_activate()
        self.factory_mock.assert_called_once_with()
        self.application.add_window.assert_called_once_with(self.window)
        self.assertIs(self.application.window, self.window)
        self.assertEqual(self.window.method_calls,
                         [call for _ in range(3) for call in
                          [('show_all', (), {}), ('deiconify', (), {}), ('present', (), {})]])

    def test_activation_preserves_countdown_and_recording_objects_and_state(self):
        for state in ('countdown', 'recording'):
            with self.subTest(state=state):
                self.window.lifecycle.state = state
                lifecycle, engine = self.window.lifecycle, self.window.engine
                self.application.do_activate()
                self.assertIs(self.window.lifecycle, lifecycle)
                self.assertIs(self.window.engine, engine)
                self.assertEqual((lifecycle.state, lifecycle.token), (state, 7))
                self.window.on_record_clicked.assert_not_called()
                self.window.start_recording.assert_not_called()
                self.window.stop_recording.assert_not_called()
        self.factory_mock.assert_called_once_with()

    def test_activation_during_close_does_not_recreate_or_quit(self):
        self.application.do_activate()
        self.window.reset_mock()
        self.window.lifecycle.closed = True
        for state in ('stopping', 'closed'):
            self.window.lifecycle.state = state
            self.application.do_activate()
        self.factory_mock.assert_called_once_with()
        self.window.show_all.assert_not_called()
        self.application.quit.assert_not_called()

    def test_cleanup_failure_can_restore_existing_window(self):
        self.application.do_activate()
        self.window.reset_mock()
        self.window.lifecycle.closed = True
        self.window.lifecycle.state = 'cleanup_failed'
        self.application.do_activate()
        self.factory_mock.assert_called_once_with()
        self.window.show_all.assert_called_once_with()
        self.window.deiconify.assert_called_once_with()
        self.window.present.assert_called_once_with()
        self.application.quit.assert_not_called()
