import queue
import signal
import subprocess
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from engine.lifecycle import OwnedProcesses, RecordingLifecycle
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
        self.border = Child()
        self.options = RecordingOptions('monitor', 'both', 60, 'normal')
        self.life = RecordingLifecycle(
            self.engine, self.queue.put, lambda *args: self.states.append(args)
        )
        self.exists = patch('pathlib.Path.is_file', return_value=True)
        self.exists.start()
        self.spawn = patch('engine.lifecycle.subprocess.Popen', side_effect=self.popen)
        self.spawn.start()
        self.addCleanup(self.exists.stop)
        self.addCleanup(self.spawn.stop)
        self.addCleanup(self.cleanup)

    def popen(self, command, **kwargs):
        return self.border if 'recording-border.py' in str(command) else self.countdown

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

    def test_cancel_after_countdown_exit_before_callback_never_starts(self):
        self.life.begin(self.options)
        self.queue.get(timeout=2)  # Leave callbacks stale, even after normal helper exit.
        self.life.cancel()
        self.finish()
        self.engine.start.assert_not_called()
        self.assertEqual(self.life.state, 'idle')
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
        commands = [call.args[0] for call in self.spawn.mock_calls if call.args]
        self.assertTrue(any(c[-4:] == ['10', '20', '100', '98'] for c in commands))
        self.life.cancel()
        self.finish()
        self.engine.stop.assert_called_once()
        self.assertIn(('terminate',), self.border.calls)
        self.assertTrue(any(c[0] == 'wait' for c in self.border.calls))

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

    def test_unexpected_exit_cleans_and_reports(self):
        self.engine.is_recording.return_value = False
        self.life.begin(self.options)
        self.authorize()
        self.finish()
        self.engine.stop.assert_called_once()
        self.assertIn('unexpectedly', self.states[-1][1])
        self.assertEqual(self.life.state, 'idle')

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
