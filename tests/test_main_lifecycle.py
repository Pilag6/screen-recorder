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
    repository.Gdk = SimpleNamespace(
        EventType=SimpleNamespace(ENTER_NOTIFY=1, LEAVE_NOTIFY=2),
        Cursor=SimpleNamespace(new_from_name=Mock()),
    )
    repository.Pango = SimpleNamespace(EllipsizeMode=SimpleNamespace(MIDDLE=2))
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
        self.ui.change_output_button = Mock()
        self.ui.rename_monitor_button = Mock()
        self.ui.source = {}
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

    def test_output_change_disabled_in_every_nonidle_state_and_when_closed(self):
        for state in ('selecting', 'countdown', 'starting', 'recording', 'stopping',
                      'cleanup_failed', 'closed', 'idle'):
            with self.subTest(state=state):
                self.ui.lifecycle.state = state
                self.ui.update_button()
                self.ui.change_output_button.set_sensitive.assert_called_with(state == 'idle')
        self.ui.lifecycle.closed = True
        self.ui.update_button()
        self.ui.change_output_button.set_sensitive.assert_called_with(False)

    def test_countdown_label_and_cancel(self):
        self.ui.update_button()
        self.ui.start_button.set_label.assert_called_with('Cancel Recording')
        self.ui.start_button.set_sensitive.assert_called_with(True)
        self.ui.on_record_clicked(None)
        self.ui.lifecycle.cancel.assert_called_once()

    def test_close_defers_quit_until_cleanup_callback(self):
        self.assertTrue(self.ui.on_close(None, None))
        self.ui.change_output_button.set_sensitive.assert_called_with(False)
        self.ui.lifecycle.close.assert_called_once()
        self.application.quit.assert_not_called()
        self.ui.lifecycle.state = 'closed'
        self.ui.change_output_button.reset_mock()
        self.ui.on_lifecycle_state('closed', 'Closed', None)
        self.ui.change_output_button.set_sensitive.assert_called_with(False)
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

    def test_arbitrary_connectors_generic_labels_and_logical_identity(self):
        result = Mock(stdout=('Monitors: 4\n'
            ' 0: +*internal 1920/300x1080/200+0+0 eDP-7\n'
            ' 1: +HDMI-A-9 1280x720-1280-20 HDMI-A-9\n'
            ' 2: +wide 3200/600x1200/250+1920+0 DP-3 DP-4\n'
            ' 3: +*virtual 800x600-800-600\n'))
        with patch.object(self.module.subprocess, 'run', return_value=result) as run:
            monitors = self.module.get_connected_monitors()
        self.assertEqual(monitors, [
            {'id': 'internal', 'label': 'Display 1 (internal)', 'x': 0, 'y': 0,
             'width': 1920, 'height': 1080},
            {'id': 'HDMI-A-9', 'label': 'Display 2 (HDMI-A-9)', 'x': -1280, 'y': -20,
             'width': 1280, 'height': 720},
            {'id': 'wide', 'label': 'Display 3 (wide)', 'x': 1920, 'y': 0,
             'width': 3200, 'height': 1200},
            {'id': 'virtual', 'label': 'Display 4 (virtual)', 'x': -800, 'y': -600,
             'width': 800, 'height': 600}])
        from engine.recording import RecordingEngine
        with patch.object(self.module.subprocess, 'run', return_value=result):
            for monitor in monitors:
                self.assertEqual(RecordingEngine().get_monitor_geometry(monitor['id']),
                                 (monitor['x'], monitor['y'], monitor['width'], monitor['height']))
                with self.assertRaises(ValueError):
                    RecordingEngine().get_monitor_geometry(monitor['label'])
        run.assert_called_once_with(['xrandr', '--listmonitors'], capture_output=True,
                                    text=True, check=True, timeout=5)

    def test_monitor_detection_skips_malformed_geometry_and_handles_failure(self):
        result = Mock(stdout='Monitors: 2\n 0: +bad invalid bad\n 1: +DP-8 80x60+1+2 DP-8\n')
        with patch.object(self.module.subprocess, 'run', return_value=result):
            self.assertEqual(self.module.get_connected_monitors()[0]['label'],
                             'Display 2 (DP-8)')
        for error in (OSError('missing'), self.module.subprocess.TimeoutExpired('xrandr', 5)):
            with patch.object(self.module.subprocess, 'run', side_effect=error):
                self.assertEqual(self.module.get_connected_monitors(), [])

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
        button = cls(first)
        button.label = text
        return button

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
        Image=SimpleNamespace(new_from_pixbuf=Mock(return_value=InertWidget()),
                              new_from_icon_name=Mock(side_effect=lambda name, size:
                                  SimpleNamespace(icon_name=name, icon_size=size))),
        IconSize=SimpleNamespace(BUTTON=1),
        Orientation=SimpleNamespace(VERTICAL=0, HORIZONTAL=1),
        WindowPosition=SimpleNamespace(CENTER=0),
        Align=SimpleNamespace(START=0, END=1),
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

    def chooser(self, response=1, filename='/custom clips/日本語'):
        dialog = Mock()
        dialog.run.return_value = response
        dialog.get_filename.return_value = filename
        self.module.Gtk.FileChooserDialog = Mock(return_value=dialog)
        self.module.Gtk.FileChooserAction = SimpleNamespace(SELECT_FOLDER=2)
        self.module.Gtk.ResponseType = SimpleNamespace(CANCEL=0, ACCEPT=1)
        return dialog

    def rename_dialog(self, text='  Work display  ', response=1):
        dialog, entry = Mock(), Mock()
        dialog.run.return_value = response
        entry.get_text.return_value = text
        self.module.Gtk.Dialog = Mock(return_value=dialog)
        self.module.Gtk.Entry = Mock(return_value=entry)
        self.module.Gtk.ResponseType = SimpleNamespace(CANCEL=0, ACCEPT=1)
        return dialog, entry

    def rename_signal(self, signal):
        callbacks = [call.args[1]
                     for call in self.ui.rename_monitor_button.connect.call_args_list
                     if call.args[0] == signal]
        self.assertEqual(len(callbacks), 1)
        return callbacks[0]

    def test_rename_button_keeps_right_alignment_and_visible_edit_icon(self):
        button = self.ui.rename_monitor_button
        button.set_halign.assert_called_once_with(self.module.Gtk.Align.END)
        image = button.set_image.call_args.args[0]
        self.assertEqual((image.icon_name, image.icon_size),
                         ('document-edit-symbolic', self.module.Gtk.IconSize.BUTTON))
        button.set_always_show_image.assert_called_once_with(True)
        self.saver.assert_not_called()

    def test_rename_pointer_on_sensitive_enter_and_reset_on_leave(self):
        button = self.ui.rename_monitor_button
        button.get_sensitive.return_value = True
        enter = SimpleNamespace(type=self.module.Gdk.EventType.ENTER_NOTIFY)
        leave = SimpleNamespace(type=self.module.Gdk.EventType.LEAVE_NOTIFY)
        self.rename_signal('enter-notify-event')(button, enter)
        self.module.Gdk.Cursor.new_from_name.assert_called_once_with(
            button.get_display.return_value, 'pointer')
        button.get_window.return_value.set_cursor.assert_called_once_with(
            self.module.Gdk.Cursor.new_from_name.return_value)
        self.rename_signal('leave-notify-event')(button, leave)
        button.get_window.return_value.set_cursor.assert_called_with(None)
        self.assertEqual(self.module.Gdk.Cursor.new_from_name.call_count, 1)

    def test_rename_insensitive_enter_resets_cursor_without_creating_pointer(self):
        button = self.ui.rename_monitor_button
        button.get_sensitive.return_value = False
        self.rename_signal('enter-notify-event')(
            button, SimpleNamespace(type=self.module.Gdk.EventType.ENTER_NOTIFY))
        button.get_window.return_value.set_cursor.assert_called_once_with(None)
        self.module.Gdk.Cursor.new_from_name.assert_not_called()
        button.get_display.assert_not_called()

    def test_rename_sensitivity_notification_clears_pointer(self):
        button = self.ui.rename_monitor_button
        enter = SimpleNamespace(type=self.module.Gdk.EventType.ENTER_NOTIFY)
        for sensitive in (False, True):
            with self.subTest(sensitive=sensitive):
                button.get_sensitive.return_value = True
                self.rename_signal('enter-notify-event')(button, enter)
                button.get_window.return_value.set_cursor.assert_called_with(
                    self.module.Gdk.Cursor.new_from_name.return_value)
                button.get_sensitive.return_value = sensitive
                button.get_window.return_value.set_cursor.reset_mock()
                self.module.Gdk.Cursor.new_from_name.reset_mock()
                self.rename_signal('notify::sensitive')(button, object())
                button.get_window.return_value.set_cursor.assert_called_once_with(None)
                self.module.Gdk.Cursor.new_from_name.assert_not_called()

    def test_rename_cursor_callbacks_are_safe_before_realization(self):
        button = self.ui.rename_monitor_button
        button.get_window.return_value = None
        for signal, event in (
                ('enter-notify-event', SimpleNamespace(
                    type=self.module.Gdk.EventType.ENTER_NOTIFY)),
                ('leave-notify-event', SimpleNamespace(
                    type=self.module.Gdk.EventType.LEAVE_NOTIFY)),
                ('notify::sensitive', object())):
            with self.subTest(signal=signal):
                self.rename_signal(signal)(button, event)
        self.module.Gdk.Cursor.new_from_name.assert_not_called()
        button.get_display.assert_not_called()
        button.get_sensitive.assert_not_called()

    def test_alias_restoration_hotplug_and_capture_identity(self):
        saved = self.Preferences(source='DP-1', monitor_names={'DP-1': 'Work display'})
        self.loader.return_value = saved
        ui = self.module.ScreenRecorder()
        ui.finish_monitor_refresh(0, self.monitors(), ui.lifecycle.token)
        self.assertEqual(ui.source['DP-1'].label, 'Work display')
        self.assertEqual(ui.get_options().source, 'DP-1')
        ui.refresh_monitors([])
        self.assertEqual(ui.get_selected(ui.source), 'region')
        ui.rename_monitor_button.set_sensitive.assert_called_with(False)
        self.assertEqual(ui.preferences, saved)
        ui.refresh_monitors(self.monitors())
        self.assertEqual(ui.source['DP-1'].label, 'Work display')
        ui.rename_monitor_button.set_sensitive.assert_called_with(True)
        self.saver.assert_not_called()

    def test_reserved_monitor_ids_preserve_region_rename_restore_and_hotplug(self):
        result = Mock(stdout=('Monitors: 4\n'
            ' 0: +region 800x600+0+0\n'
            ' 1: +monitor:region 800x600+800+0 DP-3 DP-4\n'
            ' 2: +monitor:monitor:region 800x600+1600+0\n'
            ' 3: +normal 800x600+2400+0 DP-2\n'))
        with patch.object(self.module.subprocess, 'run', return_value=result):
            monitors = self.module.get_connected_monitors()
        self.ui.preferences = self.Preferences()
        self.ui.refresh_monitors(monitors)
        self.assertEqual(set(self.ui.source), {'region', 'monitor:region',
            'monitor:monitor:region', 'monitor:monitor:monitor:region', 'normal'})
        self.assertEqual(self.ui.source['region'].label, 'Select region')
        self.assertIsNone(self.ui.selected_connected_monitor())
        for raw_id, token in (('region', 'monitor:region'),
                              ('monitor:region', 'monitor:monitor:region'),
                              ('monitor:monitor:region', 'monitor:monitor:monitor:region')):
            with self.subTest(raw_id=raw_id):
                self.ui.source[token].clicked()
                self.assertEqual(self.ui.preferences.source, token)
                self.assertEqual(self.ui.get_options().source, token)
                self.assertEqual(self.ui.selected_connected_monitor()['id'], raw_id)
                self.rename_dialog(text='Work display')
                self.ui.on_rename_monitor_clicked(None)
                self.assertEqual(self.ui.preferences.monitor_names[raw_id], 'Work display')
                saved = self.ui.preferences
                self.loader.return_value = saved
                restored = self.module.ScreenRecorder()
                restored.refresh_monitors(monitors)
                self.assertEqual(restored.get_selected(restored.source), token)
                self.assertEqual(restored.source[token].label, 'Work display')
                restored.refresh_monitors([])
                self.assertEqual(restored.get_selected(restored.source), 'region')
                self.assertIsNone(restored.selected_connected_monitor())
                self.assertEqual(restored.preferences, saved)
                restored.refresh_monitors(monitors)
                self.assertEqual(restored.selected_connected_monitor()['id'], raw_id)
        self.ui.source['region'].clicked()
        self.assertEqual(self.ui.preferences.source, 'region')
        self.assertIsNone(self.ui.selected_connected_monitor())
        self.ui.rename_monitor_button.set_sensitive.assert_called_with(False)

    def test_mixed_monitor_and_output_names_keep_distinct_selection_and_capture(self):
        result = Mock(stdout=('Monitors: 2\n'
            ' 0: DP-2 800x600+0+0\n'
            ' 1: right 1280x720+800+0 DP-2\n'))
        with patch.object(self.module.subprocess, 'run', return_value=result):
            monitors = self.module.get_connected_monitors()
        self.assertEqual([monitor['id'] for monitor in monitors], ['DP-2', 'right'])
        self.ui.preferences = self.Preferences(monitor_names={
            'DP-2': 'Left display', 'right': 'Right display'})
        self.ui.refresh_monitors(monitors)
        self.assertEqual(self.ui.source['DP-2'].label, 'Left display')
        self.assertEqual(self.ui.source['right'].label, 'Right display')
        self.ui.source['right'].clicked()
        self.assertEqual(self.ui.preferences.source, 'right')
        self.assertEqual(self.ui.get_options().source, 'right')
        from engine.recording import RecordingEngine
        with patch.object(self.module.subprocess, 'run', return_value=result):
            self.assertEqual(RecordingEngine().get_monitor_geometry(self.ui.get_options().source),
                             (800, 0, 1280, 720))
        self.rename_dialog(text='Work display')
        self.ui.on_rename_monitor_clicked(None)
        self.assertEqual(self.ui.preferences.monitor_names,
                         {'DP-2': 'Left display', 'right': 'Work display'})
        self.loader.return_value = self.ui.preferences
        restored = self.module.ScreenRecorder()
        restored.refresh_monitors(monitors)
        self.assertEqual(restored.get_selected(restored.source), 'right')
        self.assertEqual(restored.selected_connected_monitor()['id'], 'right')
        restored.refresh_monitors([])
        self.assertEqual(restored.get_selected(restored.source), 'region')
        restored.refresh_monitors(monitors)
        self.assertEqual(restored.source['right'].label, 'Work display')
        self.assertEqual(restored.get_selected(restored.source), 'right')

    def test_rename_persists_candidate_before_ui_update_and_blank_resets(self):
        self.ui.refresh_monitors(self.monitors())
        dialog, entry = self.rename_dialog()
        before = self.ui.preferences
        def save(candidate):
            self.assertIs(self.ui.preferences, before)
            self.assertEqual(self.ui.source['DP-1'].label, 'DisplayPort')
            self.assertEqual(candidate.monitor_names, {'DP-1': 'Work display'})
            return True
        self.saver.side_effect = save
        self.ui.on_rename_monitor_clicked(None)
        entry.set_text.assert_called_once_with('')
        dialog.destroy.assert_called_once()
        self.assertEqual(self.ui.source['DP-1'].label, 'Work display')
        self.assertEqual(self.ui.get_options().source, 'DP-1')
        self.assertEqual(before.monitor_names, {})
        self.saver.side_effect = None
        dialog, entry = self.rename_dialog(text='  ')
        self.ui.on_rename_monitor_clicked(None)
        entry.set_text.assert_called_once_with('Work display')
        self.assertEqual(self.ui.preferences.monitor_names, {})
        self.assertEqual(self.ui.source['DP-1'].label, 'DisplayPort')
        self.assertEqual(self.saver.call_count, 2)

    def test_rename_preserves_disconnected_aliases_and_unrelated_preferences(self):
        from dataclasses import replace
        self.ui.preferences = replace(self.saved, monitor_names={'unplugged': 'Spare'})
        self.ui.refresh_monitors(self.monitors())
        self.rename_dialog(text='参考画面')
        self.ui.on_rename_monitor_clicked(None)
        self.assertEqual(self.ui.preferences, replace(self.saved, monitor_names={
            'unplugged': 'Spare', 'DP-1': '参考画面'}))
        # A failed discovery returns an empty list, just like an unplug event.
        with patch.object(self.module.subprocess, 'run', side_effect=OSError('missing')):
            monitors = self.module.get_connected_monitors()
        self.ui.finish_monitor_refresh(0, monitors, self.ui.lifecycle.token)
        self.assertEqual(self.ui.get_selected(self.ui.source), 'region')
        self.assertEqual(self.ui.preferences.monitor_names['DP-1'], '参考画面')
        self.ui.finish_monitor_refresh(0, self.monitors(), self.ui.lifecycle.token)
        self.assertEqual(self.ui.source['DP-1'].label, '参考画面')
        self.assertEqual(self.saver.call_count, 1)

    def test_rename_cancel_save_error_and_dialog_error_leave_labels_unchanged(self):
        self.ui.refresh_monitors(self.monitors())
        for mode in ('cancel', 'save-error', 'dialog-error', 'invalid-name'):
            with self.subTest(mode=mode):
                self.saver.reset_mock()
                dialog, entry = self.rename_dialog(response=0 if mode == 'cancel' else 1)
                self.saver.return_value = mode != 'save-error'
                if mode == 'dialog-error':
                    dialog.run.side_effect = RuntimeError('dialog unavailable')
                if mode == 'invalid-name':
                    entry.get_text.return_value = 'bad\x00name'
                self.ui.on_rename_monitor_clicked(None)
                self.assertEqual(self.ui.preferences, self.saved)
                self.assertEqual(self.ui.source['DP-1'].label, 'DisplayPort')
                dialog.destroy.assert_called_once()
                if mode != 'save-error':
                    self.saver.assert_not_called()
                if mode != 'cancel':
                    self.assertIn('unchanged', self.ui.status.set_text.call_args.args[0])

    def test_rename_never_opens_busy_closed_or_for_region(self):
        self.ui.refresh_monitors(self.monitors())
        for state in ('selecting', 'countdown', 'starting', 'recording', 'stopping',
                      'cleanup_failed', 'closed'):
            with self.subTest(state=state):
                self.ui.lifecycle.state = state
                self.ui.update_button()
                self.ui.rename_monitor_button.set_sensitive.assert_called_with(False)
                self.rename_dialog()
                self.ui.on_rename_monitor_clicked(None)
                self.module.Gtk.Dialog.assert_not_called()
        self.ui.lifecycle.state = 'idle'
        for closed in (True, False):
            self.ui.lifecycle.closed = closed
            if not closed:
                self.ui.source['region'].clicked()
                self.saver.reset_mock()
            self.rename_dialog()
            self.ui.on_rename_monitor_clicked(None)
            self.module.Gtk.Dialog.assert_not_called()
        self.saver.assert_not_called()

    def test_rename_rechecks_state_token_selection_and_connection_after_modal(self):
        for change in ('busy', 'closed', 'session-ended', 'selection', 'disconnect'):
            with self.subTest(change=change):
                self.ui.lifecycle.state, self.ui.lifecycle.closed = 'idle', False
                self.ui.preferences = self.saved
                self.ui.refresh_monitors(self.monitors())
                self.saver.reset_mock()
                dialog, entry = self.rename_dialog()
                def run():
                    if change == 'busy':
                        self.ui.lifecycle.state = 'recording'
                    elif change == 'closed':
                        self.ui.lifecycle.closed = True
                    elif change == 'session-ended':
                        self.ui.lifecycle.token += 1
                    elif change == 'selection':
                        self.ui.source['region'].set_active(True)
                        self.saver.reset_mock()
                    else:
                        self.ui.refresh_monitors([])
                    return 1
                dialog.run.side_effect = run
                self.ui.on_rename_monitor_clicked(None)
                self.saver.assert_not_called()
                self.assertEqual(self.ui.preferences.monitor_names, {})
                entry.get_text.assert_not_called()
                dialog.destroy.assert_called_once()

    def test_restored_output_label_is_bounded_readable_and_snapshotted(self):
        saved = self.Preferences(output_dir='/custom clips/日本語')
        self.loader.return_value = saved
        ui = self.module.ScreenRecorder()
        ui.output_label.set_text.assert_called_with(saved.output_dir)
        ui.output_label.set_tooltip_text.assert_called_with(saved.output_dir)
        ui.output_label.set_ellipsize.assert_called_once_with(self.module.Pango.EllipsizeMode.MIDDLE)
        ui.output_label.set_max_width_chars.assert_called_once()
        ui.output_label.set_selectable.assert_called_once_with(True)
        options = ui.get_options()
        self.assertEqual(options.output_dir, saved.output_dir)
        ui.preferences = self.Preferences(output_dir='/other')
        self.assertEqual(options.output_dir, saved.output_dir)
        self.saver.assert_not_called()

    def test_chooser_accept_local_folder_validates_persists_and_always_destroys(self):
        dialog = self.chooser()
        with patch.object(self.module, 'prepare_output_directory',
                          return_value=Path('/custom clips/日本語')) as prepare:
            self.ui.on_change_output_clicked(None)
        kwargs = self.module.Gtk.FileChooserDialog.call_args.kwargs
        self.assertIs(kwargs['transient_for'], self.ui)
        self.assertTrue(kwargs['modal'])
        self.assertEqual(kwargs['action'], self.module.Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.set_local_only.assert_called_once_with(True)
        dialog.set_current_folder.assert_called_once_with(self.saved.output_dir)
        dialog.add_buttons.assert_called_once_with('Cancel', 0, 'Select', 1)
        prepare.assert_called_once_with('/custom clips/日本語')
        self.assertEqual(self.ui.preferences.output_dir, '/custom clips/日本語')
        self.saver.assert_called_once_with(self.ui.preferences)
        self.ui.output_label.set_text.assert_called_with('/custom clips/日本語')
        dialog.destroy.assert_called_once()

    def test_chooser_cancel_keeps_preferences_and_destroys(self):
        dialog = self.chooser(response=0)
        with patch.object(self.module, 'prepare_output_directory') as prepare:
            self.ui.on_change_output_clicked(None)
        prepare.assert_not_called()
        self.saver.assert_not_called()
        self.assertEqual(self.ui.preferences, self.saved)
        dialog.get_filename.assert_not_called()
        dialog.destroy.assert_called_once()

    def test_chooser_validation_failure_preserves_selection_with_actionable_status(self):
        for filename, error in (('/denied', PermissionError('Permission denied')),
                                (None, ValueError('Choose a local absolute folder'))):
            with self.subTest(filename=filename):
                dialog = self.chooser(filename=filename)
                with patch.object(self.module, 'prepare_output_directory', side_effect=error):
                    self.ui.on_change_output_clicked(None)
                self.assertEqual(self.ui.preferences, self.saved)
                self.saver.assert_not_called()
                status = self.ui.status.set_text.call_args.args[0]
                self.assertIn(str(error), status)
                self.assertIn('choose', status.lower())
                dialog.destroy.assert_called_once()

    def test_chooser_persistence_error_preserves_previous_selection(self):
        dialog = self.chooser()
        self.saver.return_value = False
        with patch.object(self.module, 'prepare_output_directory', return_value=Path('/custom')):
            self.ui.on_change_output_clicked(None)
        self.assertEqual(self.ui.preferences, self.saved)
        self.ui.output_label.set_text.assert_called_with(self.saved.output_dir)
        self.assertIn('settings', self.ui.status.set_text.call_args.args[0].lower())
        dialog.destroy.assert_called_once()

    def test_chooser_never_opens_busy_or_closed_and_rechecks_after_nested_loop(self):
        for state, closed in (('countdown', False), ('starting', False), ('recording', False),
                              ('stopping', False), ('idle', True)):
            with self.subTest(state=state, closed=closed):
                dialog = self.chooser()
                self.ui.lifecycle.state, self.ui.lifecycle.closed = state, closed
                self.ui.on_change_output_clicked(None)
                self.module.Gtk.FileChooserDialog.assert_not_called()
        for state, closed in (('countdown', False), ('recording', False), ('idle', True)):
            with self.subTest(accepted_state=state, closed=closed):
                dialog = self.chooser()
                self.ui.lifecycle.state, self.ui.lifecycle.closed = 'idle', False
                def run():
                    self.ui.lifecycle.state, self.ui.lifecycle.closed = state, closed
                    return 1
                dialog.run.side_effect = run
                with patch.object(self.module, 'prepare_output_directory') as prepare:
                    self.ui.on_change_output_clicked(None)
                prepare.assert_not_called()
                self.saver.assert_not_called()
                self.assertEqual(self.ui.preferences, self.saved)
                dialog.destroy.assert_called_once()

    def test_dialog_constructor_errors_are_nonfatal_and_do_not_destroy(self):
        self.module.GLib.Error = type('ChooserError', (Exception,), {})
        for error_type in (RuntimeError, OSError, self.module.GLib.Error):
            with self.subTest(error_type=error_type):
                dialog = self.chooser()
                self.module.Gtk.FileChooserDialog.side_effect = error_type('chooser unavailable')
                self.ui.on_change_output_clicked(None)
                self.assertEqual(self.ui.preferences, self.saved)
                self.saver.assert_not_called()
                self.assertIn('chooser unavailable', self.ui.status.set_text.call_args.args[0])
                dialog.destroy.assert_not_called()

    def test_dialog_run_error_still_destroys_and_preserves_preferences(self):
        self.module.GLib.Error = type('ChooserError', (Exception,), {})
        for error_type in (RuntimeError, OSError, self.module.GLib.Error):
            with self.subTest(error_type=error_type):
                dialog = self.chooser()
                dialog.run.side_effect = error_type('chooser unavailable')
                self.ui.on_change_output_clicked(None)
                self.assertEqual(self.ui.preferences, self.saved)
                self.saver.assert_not_called()
                self.assertIn('chooser unavailable', self.ui.status.set_text.call_args.args[0])
                dialog.destroy.assert_called_once()

    def test_dialog_destroy_errors_are_nonfatal_after_cancel(self):
        self.module.GLib.Error = type('ChooserError', (Exception,), {})
        for error_type in (RuntimeError, OSError, self.module.GLib.Error):
            with self.subTest(error_type=error_type):
                dialog = self.chooser(response=0)
                dialog.destroy.side_effect = error_type('cleanup unavailable')
                self.ui.on_change_output_clicked(None)
                self.assertEqual(self.ui.preferences, self.saved)
                self.saver.assert_not_called()
                status = self.ui.status.set_text.call_args.args[0]
                self.assertIn('cleanup unavailable', status)
                self.assertIn('chooser', status.lower())
                dialog.destroy.assert_called_once()

    def test_dialog_destroy_error_does_not_undo_accepted_preferences(self):
        dialog = self.chooser()
        dialog.destroy.side_effect = RuntimeError('cleanup unavailable')
        with patch.object(self.module, 'prepare_output_directory', return_value=Path('/custom')):
            self.ui.on_change_output_clicked(None)
        self.assertEqual(self.ui.preferences.output_dir, '/custom')
        self.saver.assert_called_once_with(self.ui.preferences)
        self.ui.output_label.set_text.assert_called_with('/custom')
        self.assertIn('cleanup unavailable', self.ui.status.set_text.call_args.args[0])
        dialog.destroy.assert_called_once()

    def test_dialog_programmer_errors_are_not_swallowed(self):
        for stage in ('constructor', 'run', 'destroy'):
            with self.subTest(stage=stage):
                dialog = self.chooser(response=0)
                target = (self.module.Gtk.FileChooserDialog if stage == 'constructor'
                          else getattr(dialog, stage))
                target.side_effect = TypeError('programmer error')
                with self.assertRaisesRegex(TypeError, 'programmer error'):
                    self.ui.on_change_output_clicked(None)
                self.assertEqual(self.ui.preferences, self.saved)
                self.saver.assert_not_called()
                if stage != 'constructor':
                    dialog.destroy.assert_called_once()

    def test_notification_uses_actual_custom_file_not_current_preference(self):
        self.ui._notified_token = None
        self.ui.lifecycle.completion = SavedRecording(1, Path('/actual clips/日本語/video.mkv'))
        with patch('pathlib.Path.is_file', return_value=True):
            self.ui.notify_completion()
        self.ui.notifier.notify_saved.assert_called_once_with(
            Path('/actual clips/日本語/video.mkv'), allow_actions=True)

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

    def test_startup_refresh_has_initialized_lifecycle_and_rename_controls(self):
        refresh = self.module.ScreenRecorder.refresh_monitors
        observed = []
        def checked_refresh(ui, monitors=None):
            # InertWidget.__getattr__ otherwise hides missing startup attributes.
            self.assertIn('lifecycle', vars(ui))
            self.assertIn('source', vars(ui))
            self.assertIn('monitors', vars(ui))
            self.assertIn('rename_monitor_button', vars(ui))
            self.assertEqual(ui.lifecycle.state, 'idle')
            self.assertFalse(ui.lifecycle.closed)
            observed.append(ui)
            return refresh(ui, monitors)
        with patch.object(self.module.ScreenRecorder, 'refresh_monitors',
                          autospec=True, side_effect=checked_refresh):
            ui = self.module.ScreenRecorder()
        self.assertEqual(observed, [ui])
        ui.rename_monitor_button.set_sensitive.assert_called_with(False)
        self.assertEqual(ui.get_selected(ui.source), 'region')
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
