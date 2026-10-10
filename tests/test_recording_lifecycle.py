import os
import queue
import runpy
import signal
import subprocess
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from engine.lifecycle import BORDER_SCRIPT, COUNTDOWN_SCRIPT, OwnedProcesses, RecordingLifecycle
from engine.indicator_launcher import IndicatorPlan
from recorder import RecordingOptions


class Child:
    def __init__(self, code=None, stubborn=False):
        self.code = code
        self.stubborn = stubborn
        self.calls = []
        self.stdout = self.stderr = None

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        self.calls.append(('wait', timeout))
        if self.code is None:
            raise subprocess.TimeoutExpired('mock child', timeout)
        return self.code

    def send_signal(self, sig):
        self.calls.append(('signal', sig))
        if not self.stubborn:
            self.code = 0

    def terminate(self):
        self.calls.append(('terminate',))
        if not self.stubborn:
            self.code = -15

    def kill(self):
        self.calls.append(('kill',))
        self.code = -9


class HelperPathTests(unittest.TestCase):
    def test_helpers_exist_inside_repository(self):
        helpers = Path(__file__).resolve().parents[1] / 'helpers'
        for script, basename in ((COUNTDOWN_SCRIPT, 'recording-countdown.py'),
                                 (BORDER_SCRIPT, 'recording-border.py')):
            with self.subTest(helper=basename):
                self.assertEqual(script, helpers / basename)
                self.assertTrue(script.is_file())

    def test_helper_paths_at_import_ignore_home_and_cwd(self):
        root = Path(__file__).resolve().parents[1]
        for home, cwd in (('/nonexistent/recorder-home', '/'),
                          ('/another/nonexistent-home', '/tmp')):
            with self.subTest(home=home, cwd=cwd), \
                 patch.dict(os.environ, {'HOME': home}), \
                 patch('os.getcwd', return_value=cwd):
                module = runpy.run_path(str(root / 'engine/lifecycle.py'))
                self.assertEqual(module['COUNTDOWN_SCRIPT'],
                                 root / 'helpers/recording-countdown.py')
                self.assertEqual(module['BORDER_SCRIPT'],
                                 root / 'helpers/recording-border.py')


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.queue = queue.Queue()
        self.states = []
        self.engine = Mock()
        self.engine.get_monitor_geometry.return_value = (0, 0, 101, 99)
        self.engine.select_region.return_value = (10, 20, 101, 99)
        self.engine.start.return_value = Path('recording.mkv')
        self.engine.is_recording.return_value = True
        self.engine.stop.return_value = Path('recording.mkv')
        self.countdown = Child(0)
        self.preview = Child()
        self.border = Child()
        self.indicator = Child()
        self.plan = patch('engine.lifecycle.indicator_plan', return_value=IndicatorPlan(
            ('python', 'safe-indicator', '0', '0', '100', '98'), 'Measured REC'))
        self.plan_mock = self.plan.start()
        self.addCleanup(self.plan.stop)
        self.options = RecordingOptions('monitor', 'both', 60, 'normal')
        self.life = RecordingLifecycle(
            self.engine, self.queue.put, lambda *args: self.states.append(args)
        )
        self.exists = patch('pathlib.Path.is_file', return_value=True)
        self.exists.start()
        self.spawn = patch('engine.lifecycle.subprocess.Popen', side_effect=self.popen)
        self.spawn_mock = self.spawn.start()
        self.addCleanup(self.exists.stop)
        self.addCleanup(self.spawn.stop)
        self.addCleanup(self.cleanup)

    def popen(self, command, **kwargs):
        if 'safe-indicator' in command:
            return self.indicator
        if 'recording-border.py' in str(command):
            return self.border if self.engine.start.called else self.preview
        return self.countdown

    def cleanup(self):
        self.life.close()
        if self.life.worker:
            self.life.worker.join(2)
        self.assertFalse(self.life.worker and self.life.worker.is_alive())

    def next_callback(self):
        self.queue.get(timeout=2)()

    def authorize(self):
        # Countdown state notification, then explicit GTK start authorization.
        self.next_callback()
        self.next_callback()

    def finish(self):
        self.life.worker.join(2)
        self.assertFalse(self.life.worker.is_alive())
        while not self.queue.empty():
            self.next_callback()

    def test_region_launches_existing_repository_helpers_with_inert_children(self):
        self.exists.stop()  # Exercise real helper existence, never real subprocesses.
        helpers = Path(__file__).resolve().parents[1] / 'helpers'
        self.life.begin(RecordingOptions('region', 'none', 30, 'high'))
        self.authorize()
        self.next_callback()
        self.life.cancel()
        self.finish()
        commands = [call.args[0] for call in self.spawn_mock.call_args_list]
        self.assertEqual(sum(str(helpers / 'recording-countdown.py') in command
                             for command in commands), 1)
        self.assertEqual(sum(str(helpers / 'recording-border.py') in command
                             for command in commands), 2)
        self.assertEqual(self.life.state, 'idle')

    def test_escaped_monitor_selection_decodes_only_at_capture_boundary(self):
        for token, raw_id in (('monitor:region', 'region'),
                              ('monitor:monitor:region', 'monitor:region'),
                              ('monitor:monitor:monitor:region', 'monitor:monitor:region'),
                              ('DP-2', 'DP-2')):
            with self.subTest(token=token):
                self.engine.reset_mock()
                self.spawn_mock.reset_mock()
                self.life.begin(RecordingOptions(token, 'none', 30, 'high'))
                self.assertEqual(self.life.state, 'countdown')
                self.authorize()
                self.next_callback()
                try:
                    self.engine.select_region.assert_not_called()
                    self.engine.get_monitor_geometry.assert_called_once_with(raw_id)
                    self.assertEqual(self.engine.start.call_args.kwargs['region'], (0, 0, 100, 98))
                    self.assertNotIn('monitor', self.engine.start.call_args.kwargs)
                    self.assertFalse(any(str(BORDER_SCRIPT) in call.args[0]
                                         for call in self.spawn_mock.call_args_list))
                finally:
                    self.life.cancel()
                    self.finish()
                self.assertEqual(self.life.state, 'idle')

    def test_output_folder_snapshot_forwarded_to_engine(self):
        options = RecordingOptions('monitor', 'none', 30, 'high', '/custom clips/日本語')
        self.life.begin(options)
        self.authorize()
        self.next_callback()
        self.assertEqual(self.engine.start.call_args.kwargs['output_dir'], options.output_dir)
        self.life.cancel()
        self.finish()
        self.assertEqual(self.life.state, 'idle')

    def test_real_engine_folder_failure_returns_idle_without_ffmpeg_or_completion(self):
        import tempfile
        from engine.recording import RecordingEngine
        self.life.engine = RecordingEngine()
        self.life.engine.get_monitor_geometry = Mock(return_value=(0, 0, 100, 100))
        with tempfile.TemporaryDirectory() as root, \
             patch('recorder.os.fsync', side_effect=PermissionError('output folder denied')):
            self.life.begin(RecordingOptions('monitor', 'none', 30, 'high', root))
            self.authorize()
            self.finish()
            self.assertEqual(list(Path(root).iterdir()), [])
        self.assertEqual(self.life.state, 'idle')
        self.assertIsNone(self.life.session)
        self.assertIsNone(self.life.completion)
        self.assertIn('output folder denied', self.states[-1][1])
        self.assertFalse(any(call.args[0][0] == 'ffmpeg' for call in self.spawn_mock.call_args_list))

    def test_cancel_after_countdown_exit_before_callback_never_starts(self):
        self.life.begin(self.options)
        self.queue.get(timeout=2)  # Leave callbacks stale, even after normal helper exit.
        self.life.cancel()
        self.finish()
        self.engine.start.assert_not_called()
        self.assertEqual(self.life.state, 'idle')
        self.assertIsNone(self.life.completion)
        self.assertTrue(any(c[0] == 'wait' for c in self.countdown.calls))

    def test_close_invalidates_queued_authorization(self):
        self.life.begin(self.options)
        self.queue.get(timeout=2)
        self.life.close()
        self.finish()
        self.engine.start.assert_not_called()
        self.assertEqual(self.life.state, 'closed')

    def test_countdown_failure_and_missing_helper_do_not_start(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                self.countdown.code = 1
                with patch('pathlib.Path.is_file', return_value=not missing):
                    self.life.begin(self.options)
                    self.finish()
                self.engine.start.assert_not_called()
                self.assertEqual(self.life.state, 'idle')
                self.assertIn('error', self.states[-1][1].lower())

    def test_region_uses_same_even_geometry_and_stop_reaps_border(self):
        options = RecordingOptions('region', 'mic', 30, 'high')
        self.life.begin(options)
        self.authorize()
        self.next_callback()  # recording
        self.assertEqual(self.life.state, 'recording')
        self.assertEqual(self.engine.start.call_args.kwargs['region'], (10, 20, 100, 98))
        commands = [call.args[0] for call in self.spawn_mock.mock_calls if call.args]
        self.assertTrue(any(c[-4:] == ['10', '20', '100', '98'] for c in commands))
        self.life.cancel()
        self.finish()
        self.engine.stop.assert_called_once()
        self.assertIn(('terminate',), self.border.calls)
        self.assertTrue(any(c[0] == 'wait' for c in self.border.calls))

    def test_preview_reaped_before_ffmpeg_then_recording_border_spawned(self):
        from engine.recording import RecordingEngine
        events = []
        real_engine = RecordingEngine()
        real_engine.select_region = Mock(return_value=(-12, 20, 101, 99))
        self.life.engine = real_engine
        ffmpeg = Child()
        borders = iter((self.preview, self.border))
        terminate, wait = self.preview.terminate, self.preview.wait
        def preview_terminate():
            events.append('preview terminate')
            terminate()
        def preview_wait(timeout=None):
            events.append('preview wait')
            return wait(timeout)
        self.preview.terminate = preview_terminate
        self.preview.wait = preview_wait
        def popen(command, **kwargs):
            if str(BORDER_SCRIPT) in command:
                child = next(borders)
                events.append('preview spawn' if child is self.preview else 'border spawn')
                self.assertEqual(command[-4:], ['-12', '20', '100', '98'])
                return child
            if command[0] == 'ffmpeg':
                events.append('ffmpeg spawn')
                self.assertNotIn('countdown_border', real_engine.owner.children)
                self.assertIn('100x98', command)
                self.assertTrue(any(arg.endswith('+-12,20') for arg in command))
                return ffmpeg
            return self.popen(command, **kwargs)
        self.spawn_mock.side_effect = popen
        with patch('engine.recording.prepare_output_directory', return_value=Path('/mock recordings')), \
             patch('pathlib.Path.stat', return_value=Mock(st_size=42)):
            self.life.begin(RecordingOptions('region', 'none', 30, 'high'))
            self.authorize()
            self.next_callback()
            self.assertEqual(events, ['preview spawn', 'preview terminate', 'preview wait',
                                      'ffmpeg spawn', 'border spawn'])
            self.assertFalse(self.border.calls)
            self.life.cancel()
            self.finish()
        self.assertIn(('terminate',), self.border.calls)
        self.assertIn(('wait', 3), self.border.calls)

    def test_preview_survives_queued_authorization_and_cancel_or_close_reaps_it(self):
        for close in (False, True):
            with self.subTest(close=close):
                self.preview = Child()
                self.life.begin(RecordingOptions('region', 'none', 30, 'high'))
                self.next_callback()  # countdown state
                authorize = self.queue.get(timeout=2)  # Hold GTK authorization callback.
                self.assertEqual(self.life.state, 'countdown')
                self.assertFalse(self.preview.calls)
                self.assertTrue(any(str(BORDER_SCRIPT) in call.args[0]
                                    for call in self.spawn_mock.call_args_list))
                (self.life.close if close else self.life.cancel)()
                authorize()  # Stale GTK authorization must remain inert.
                self.finish()
                self.engine.start.assert_not_called()
                self.assertIn(('terminate',), self.preview.calls)
                self.assertIn(('wait', 3), self.preview.calls)
                self.assertEqual(self.life.state, 'closed' if close else 'idle')

    def test_live_region_countdown_cancel_or_close_reaps_preview_without_output(self):
        from engine.recording import RecordingEngine
        self.life.engine = RecordingEngine()
        self.life.engine.select_region = Mock(return_value=(10, 20, 101, 99))
        for close in (False, True):
            with self.subTest(close=close), patch('pathlib.Path.mkdir') as mkdir:
                self.preview = Child()
                self.countdown = Child()
                spawned = threading.Event()
                def popen(command, **kwargs):
                    child = self.popen(command, **kwargs)
                    if str(COUNTDOWN_SCRIPT) in command:
                        spawned.set()
                    return child
                self.spawn_mock.side_effect = popen
                self.life.begin(RecordingOptions('region', 'none', 30, 'high'))
                self.assertTrue(spawned.wait(2))
                (self.life.close if close else self.life.cancel)()
                self.finish()
                mkdir.assert_not_called()
                self.assertIn(('terminate',), self.preview.calls)
                self.assertIn(('wait', 3), self.preview.calls)
                self.assertIn(('wait', 3), self.countdown.calls)
        self.assertFalse(any(call.args[0][0] == 'ffmpeg'
                             for call in self.spawn_mock.call_args_list))

    def test_countdown_failure_timeout_or_spawn_failure_reaps_preview(self):
        for failure in ('exit', 'timeout', 'spawn'):
            with self.subTest(failure=failure):
                self.preview = Child()
                self.countdown = Child(1 if failure == 'exit' else None)
                def popen(command, **kwargs):
                    if failure == 'spawn' and str(COUNTDOWN_SCRIPT) in command:
                        raise OSError('countdown unavailable')
                    return self.popen(command, **kwargs)
                self.spawn_mock.side_effect = popen
                with patch('engine.lifecycle.time.monotonic', side_effect=[0, 16]):
                    self.life.begin(RecordingOptions('region', 'none', 30, 'high'))
                    self.finish()
                self.engine.start.assert_not_called()
                self.assertEqual(self.life.state, 'idle')
                self.assertIn(('terminate',), self.preview.calls)
                self.assertIn(('wait', 3), self.preview.calls)

    def test_missing_or_spawn_failed_preview_is_optional(self):
        for missing in (True, False):
            with self.subTest(missing=missing):
                self.engine.start.reset_mock()
                def popen(command, **kwargs):
                    if str(BORDER_SCRIPT) in command and not self.engine.start.called:
                        raise OSError('preview unavailable')
                    return self.popen(command, **kwargs)
                self.spawn_mock.side_effect = popen
                with patch('engine.lifecycle.BORDER_SCRIPT') as helper:
                    helper.is_file.return_value = not missing
                    helper.__str__.return_value = str(BORDER_SCRIPT)
                    self.life.begin(RecordingOptions('region', 'none', 30, 'high'))
                    self.authorize()
                    self.next_callback()
                    self.assertEqual(self.life.state, 'recording')
                    self.engine.start.assert_called_once()
                    self.life.cancel()
                    self.finish()
                self.assertEqual(self.life.state, 'idle')

    def test_exited_or_escalated_preview_is_reaped_before_start(self):
        for exited in (True, False):
            with self.subTest(exited=exited):
                self.engine.start.reset_mock()
                self.preview = Child(7 if exited else None, stubborn=not exited)
                def start(**kwargs):
                    self.assertNotIn('countdown_border', kwargs['owner'].children)
                    self.assertIn(('wait', 3), self.preview.calls)
                    if not exited:
                        self.assertIn(('kill',), self.preview.calls)
                    return Path('recording.mkv')
                self.engine.start.side_effect = start
                self.life.begin(RecordingOptions('region', 'none', 30, 'high'))
                self.authorize()
                self.next_callback()
                self.assertEqual(self.life.state, 'recording')
                self.engine.start.assert_called_once()
                self.life.cancel()
                self.finish()
                if exited:
                    self.assertNotIn(('terminate',), self.preview.calls)

    def test_cancel_during_preview_reap_is_checked_before_start(self):
        wait = self.preview.wait
        def preview_wait(timeout=None):
            self.life.session.cancel.set()
            return wait(timeout)
        self.preview.wait = preview_wait
        self.life.begin(RecordingOptions('region', 'none', 30, 'high'))
        self.authorize()
        self.finish()
        self.engine.start.assert_not_called()
        self.assertEqual(self.life.state, 'idle')
        self.assertIn(('wait', 3), self.preview.calls)

    def test_unreapable_preview_blocks_start_and_retains_cleanup_ownership(self):
        self.preview.stubborn = True
        self.preview.kill = Mock()  # All bounded waits fail, including cleanup retry.
        self.life.begin(RecordingOptions('region', 'none', 30, 'high'))
        self.authorize()
        self.finish()
        self.engine.start.assert_not_called()
        self.engine.stop.assert_not_called()
        self.assertEqual(self.life.state, 'cleanup_failed')
        self.assertIs(self.life.cleanup_owner.children['countdown_border'], self.preview)
        self.assertIn('countdown_border', self.life.cleanup_owner.escalated)
        self.assertTrue(all(call[1] is not None for call in self.preview.calls
                            if call[0] == 'wait'))
        self.assertFalse(self.life.begin(self.options))
        self.life.close()
        self.finish()
        self.assertEqual(self.life.state, 'cleanup_failed')
        self.assertNotIn('closed', [state[0] for state in self.states])
        self.preview.code = 0
        self.life.close()
        self.finish()
        self.assertEqual(self.life.state, 'closed')
        self.assertIsNone(self.life.cleanup_owner)
        self.assertIsNone(self.life.session)
        self.engine.start.assert_not_called()

    def test_close_during_start_waits_off_caller_and_cleans_returned_process(self):
        entered, release = threading.Event(), threading.Event()
        def start(**kwargs):
            entered.set()
            release.wait(2)
            return Path('recording.mkv')
        self.engine.start.side_effect = start
        self.life.begin(self.options)
        self.authorize()
        self.assertTrue(entered.wait(2))
        self.life.close()
        self.assertEqual(self.life.state, 'closed')
        release.set()
        self.finish()
        self.engine.stop.assert_called_once()
        self.assertNotIn('recording', [s[0] for s in self.states])
        self.assertIsNone(self.life.completion)

    def test_unexpected_exit_cleans_and_reports(self):
        self.engine.is_recording.return_value = False
        self.life.begin(self.options)
        self.authorize()
        self.finish()
        self.engine.stop.assert_called_once()
        self.assertIn('unexpectedly', self.states[-1][1])
        self.assertEqual(self.life.state, 'idle')

    def test_early_ffmpeg_exit_never_shows_rec_or_recording_border(self):
        self.engine.is_recording.return_value = False
        self.life.begin(RecordingOptions('region', 'none', 30, 'high'))
        self.authorize()
        self.finish()
        self.assertFalse(any('safe-indicator' in call.args[0]
                             for call in self.spawn_mock.call_args_list))
        borders = [call.args[0] for call in self.spawn_mock.call_args_list
                   if str(BORDER_SCRIPT) in call.args[0]]
        self.assertEqual(len(borders), 1)  # Preview only; never a recording border.
        self.assertIn(('wait', 3), self.preview.calls)
        self.assertFalse(self.border.calls)
        self.assertNotIn('recording', [state[0] for state in self.states])
        self.assertIn('unexpectedly', self.states[-1][1])

    def test_indicator_spawned_owned_and_reaped_on_stop(self):
        self.life.begin(self.options)
        self.authorize()
        self.next_callback()
        self.assertTrue(any('safe-indicator' in call.args[0]
                            for call in self.spawn_mock.call_args_list))
        self.plan_mock.assert_called_once_with((0, 0, 100, 98))
        self.assertFalse(any('recording-border.py' in str(call.args[0])
                             for call in self.spawn_mock.call_args_list))
        self.life.cancel()
        self.finish()
        self.assertIn(('terminate',), self.indicator.calls)
        self.assertIn(('wait', 3), self.indicator.calls)

    def test_indicator_exit_falls_back_without_stopping_recording(self):
        self.indicator.code = 2
        self.life.begin(self.options)
        self.authorize()
        self.next_callback()
        self.next_callback()
        self.assertEqual(self.life.state, 'recording')
        self.assertIn('in-window', self.life.indicator_reason)
        self.engine.stop.assert_not_called()
        self.life.cancel()
        self.finish()
        self.assertIn(('wait', 3), self.indicator.calls)

    def test_indicator_and_border_launch_errors_are_optional(self):
        def popen(command, **kwargs):
            if 'safe-indicator' in command or 'recording-border.py' in str(command):
                raise OSError('mock helper unavailable')
            return self.countdown
        self.spawn_mock.side_effect = popen
        self.life.begin(RecordingOptions('region', 'none', 30, 'high'))
        self.authorize()
        self.next_callback()
        self.assertEqual(self.life.state, 'recording')
        self.assertIn('in-window', self.life.indicator_reason)
        self.assertIn('border', self.states[-1][1].lower())
        self.life.cancel()
        self.finish()

    def test_live_countdown_cancel_real_engine_never_creates_output(self):
        from engine.recording import RecordingEngine
        self.life.engine = RecordingEngine()
        self.life.engine.get_monitor_geometry = Mock(return_value=(0, 0, 100, 98))
        self.countdown.code = None
        with patch('pathlib.Path.mkdir') as mkdir:
            self.life.begin(RecordingOptions('monitor', 'none', 30, 'high'))
            self.next_callback()
            self.life.cancel()
            self.finish()
        mkdir.assert_not_called()
        self.assertFalse(any(call.args[0][0] == 'ffmpeg' for call in self.spawn_mock.call_args_list))
        self.assertIn(('terminate',), self.countdown.calls)
        self.assertIn(('wait', 3), self.countdown.calls)

    def test_close_during_ffmpeg_popen_reaps_child_returned_after_close(self):
        from engine.recording import RecordingEngine
        real_engine = RecordingEngine()
        real_engine.get_monitor_geometry = Mock(return_value=(0, 0, 100, 98))
        self.life.engine = real_engine
        entered, release = threading.Event(), threading.Event()
        ffmpeg = Child()
        def popen(command, **kwargs):
            if command[0] == 'ffmpeg':
                entered.set()
                release.wait(2)
                return ffmpeg
            return self.popen(command, **kwargs)
        self.spawn_mock.side_effect = popen
        with patch('engine.recording.prepare_output_directory', return_value=Path('/mock recordings')), \
             patch('pathlib.Path.stat', return_value=Mock(st_size=42)):
            self.life.begin(RecordingOptions('monitor', 'none', 30, 'high'))
            self.authorize()
            self.assertTrue(entered.wait(2))
            self.life.close()
            self.assertTrue(self.life.worker.is_alive())
            self.assertNotIn('closed', [state[0] for state in self.states])
            release.set()
            self.finish()
        self.assertIn(('signal', signal.SIGINT), ffmpeg.calls)
        self.assertTrue(any(call[0] == 'wait' for call in ffmpeg.calls))
        self.assertIsNone(real_engine.process)
        self.assertEqual(self.life.state, 'closed')

    def test_close_during_selection_invalidates_result(self):
        entered, release = threading.Event(), threading.Event()
        def select(**kwargs):
            entered.set()
            release.wait(2)
            return (0, 0, 100, 98)
        self.engine.select_region.side_effect = select
        self.life.begin(RecordingOptions('region', 'none', 30, 'high'))
        self.assertTrue(entered.wait(2))
        self.life.close()
        release.set()
        self.finish()
        self.spawn_mock.assert_not_called()
        self.engine.start.assert_not_called()
        self.assertEqual(self.life.state, 'closed')

    def test_countdown_timeout_or_launch_failure_never_starts(self):
        self.countdown.code = None
        with patch('engine.lifecycle.time.monotonic', side_effect=[0, 16]):
            self.life.begin(self.options)
            self.finish()
        self.assertIn('timed out', self.states[-1][1])
        self.engine.start.assert_not_called()
        self.spawn_mock.side_effect = OSError('countdown unavailable')
        self.life.begin(self.options)
        self.finish()
        self.assertIn('unavailable', self.states[-1][1])
        self.engine.start.assert_not_called()

    def test_stale_completion_cannot_replace_new_session(self):
        self.life.begin(self.options)
        old_notification = self.queue.get(timeout=2)
        self.life.cancel()
        self.life.worker.join(2)
        callbacks = []
        while not self.queue.empty():
            callbacks.append(self.queue.get())
        for callback in callbacks:
            callback()
        self.assertEqual(self.life.state, 'idle')
        self.life.begin(self.options)
        current_session = self.life.session
        for callback in [old_notification, *callbacks]:
            callback()
        self.assertIs(self.life.session, current_session)
        self.assertEqual(self.life.state, 'countdown')
        self.life.cancel()
        self.finish()

    def test_unreaped_children_prevent_closed_callback_and_allow_retry(self):
        child = Child(stubborn=True)
        child.kill = Mock()  # Even final bounded wait fails; child remains owned.
        def start(**kwargs):
            kwargs['owner'].add('ffmpeg', child)
            return Path('recording.mkv')
        self.engine.start.side_effect = start
        self.life.begin(self.options)
        self.authorize()
        self.next_callback()
        self.life.close()
        self.finish()
        self.assertEqual(self.life.state, 'cleanup_failed')
        self.assertNotIn('closed', [state[0] for state in self.states])
        self.assertIsNotNone(self.life.session)
        child.code = 0
        self.life.close()
        self.finish()
        self.assertEqual(self.life.state, 'closed')
        self.assertIsNone(self.life.session)

    def test_save_error_is_not_reported_as_saved(self):
        self.engine.stop.side_effect = RuntimeError('FFmpeg failed')
        self.life.begin(self.options)
        self.authorize()
        self.next_callback()
        self.life.cancel()
        self.finish()
        self.assertIn('error', self.states[-1][1].lower())
        self.assertNotIn('Saved:', self.states[-1][1])

    def test_success_metadata_published_only_after_stop_and_cleanup(self):
        self.life.begin(self.options)
        self.authorize()
        self.next_callback()
        self.assertIsNone(self.life.completion)
        self.life.cancel()
        self.life.worker.join(2)
        self.assertIsNone(self.life.completion)  # GTK has not accepted completion yet.
        self.finish()
        self.assertEqual(self.life.completion.output, self.engine.stop.return_value)
        self.assertEqual(self.life.completion.token, 1)
        self.assertFalse(self.indicator.poll() is None)
        self.life.begin(self.options)
        self.assertIsNone(self.life.completion)
        self.life.cancel()
        self.finish()
        self.assertIsNone(self.life.completion)

    def test_close_after_recording_publishes_success_before_closed_callback(self):
        observed = []
        self.life.on_state = lambda *args: observed.append((args[0], self.life.completion))
        self.life.begin(self.options)
        self.authorize()
        self.next_callback()
        self.life.close()
        self.finish()
        self.assertEqual(observed[-1][0], 'closed')
        self.assertEqual(observed[-1][1].output, Path('recording.mkv'))

    def test_successful_completion_replay_cannot_publish_into_new_session(self):
        self.life.begin(self.options)
        self.authorize()
        self.next_callback()
        self.life.cancel()
        self.life.worker.join(2)
        complete = self.queue.get(timeout=2)
        complete()
        self.assertIsNotNone(self.life.completion)
        self.life.begin(self.options)
        current = self.life.session
        complete()
        self.assertIs(self.life.session, current)
        self.assertIsNone(self.life.completion)
        self.assertEqual(self.life.state, 'countdown')
        self.life.cancel()
        self.finish()

    def test_cleanup_error_even_after_reaping_suppresses_success(self):
        cleanup = OwnedProcesses.cleanup
        def fail_after_cleanup(owner):
            cleanup(owner)
            raise OSError('stream cleanup failed')
        with patch.object(OwnedProcesses, 'cleanup', fail_after_cleanup):
            self.life.begin(self.options)
            self.authorize()
            self.next_callback()
            self.life.cancel()
            self.finish()
        self.assertEqual(self.life.state, 'idle')
        self.assertIsNone(self.life.completion)
        self.assertIn('Cleanup error', self.states[-1][1])

    def test_completion_negative_cases(self):
        for failure in ('empty', 'forced', 'unexpected', 'startup', 'cleanup'):
            with self.subTest(failure=failure):
                self.engine.stop.side_effect = None
                self.engine.stop.return_value = Path('recording.mkv')
                self.engine.is_recording.return_value = failure != 'startup'
                self.indicator = Child()
                if failure == 'empty':
                    self.engine.stop.return_value = None
                if failure == 'forced':
                    self.engine.stop.side_effect = RuntimeError('forced stop')
                if failure == 'cleanup':
                    self.indicator.wait = Mock(side_effect=OSError('cleanup failed'))
                self.life.begin(self.options)
                self.authorize()
                if failure != 'startup':
                    self.next_callback()
                    if failure == 'unexpected':
                        self.engine.is_recording.return_value = False
                    else:
                        self.life.cancel()
                self.finish()
                self.assertIsNone(self.life.completion)
                if failure == 'cleanup':
                    self.indicator.wait = Mock(return_value=0)
                    self.life.retry_cleanup()
                    self.finish()
                    self.assertIsNone(self.life.completion)

    def test_double_start_and_restart_while_stopping_are_rejected(self):
        self.life.begin(self.options)
        self.assertFalse(self.life.begin(self.options))
        self.life.cancel()
        self.assertFalse(self.life.begin(self.options))
        self.finish()
        self.assertTrue(self.life.begin(self.options))
        self.life.cancel()
        self.finish()


class OwnershipTests(unittest.TestCase):
    def test_bounded_escalation_and_already_exited_reaping(self):
        owner = OwnedProcesses()
        stubborn = Child(stubborn=True)
        exited = Child(7)
        owner.add('ffmpeg', stubborn)
        owner.add('indicator', exited)
        owner.reap('ffmpeg', signal.SIGINT)
        owner.cleanup()
        self.assertEqual([c[0] for c in stubborn.calls],
                         ['signal', 'wait', 'terminate', 'wait', 'kill', 'wait'])
        self.assertTrue(all(c[1] is not None for c in stubborn.calls if c[0] == 'wait'))
        self.assertTrue(any(c[0] == 'wait' for c in exited.calls))
        self.assertFalse(owner.children)

    def test_cleanup_attempts_every_child_on_error(self):
        owner = OwnedProcesses()
        bad, good = Child(), Child()
        bad.wait = Mock(side_effect=OSError('denied'))
        owner.add('bad', bad)
        owner.add('good', good)
        with self.assertRaises(RuntimeError):
            owner.cleanup()
        self.assertTrue(any(c[0] == 'wait' for c in good.calls))
