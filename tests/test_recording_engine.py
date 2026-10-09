import signal
import subprocess
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from engine.recording import RecordingEngine, normalize_geometry
from engine.lifecycle import Cancelled, OwnedProcesses
from recorder import RecordingOptions


class EngineTests(unittest.TestCase):
    def test_normalization_and_validation(self):
        self.assertEqual(normalize_geometry((-12, -8, 101, 99)), (-12, -8, 100, 98))
        for geometry in ((0, 0, 1, 20), (0, 0, 20, -1), (0, 1, 2), (0, 0, 2.5, 4)):
            with self.subTest(geometry=geometry), self.assertRaises(ValueError):
                normalize_geometry(geometry)
        RecordingOptions('region', 'both', 60, 'normal').validate()
        for options in (RecordingOptions('', 'none', 30, 'high'),
                        RecordingOptions('region', 'bad', 30, 'high'),
                        RecordingOptions('region', 'none', 15, 'high'),
                        RecordingOptions('region', 'none', 30, 'bad')):
            with self.assertRaises(ValueError):
                options.validate()

    def test_cancelled_start_does_not_make_directory_or_spawn(self):
        engine = RecordingEngine()
        event = threading.Event()
        event.set()
        with patch('engine.recording.subprocess.Popen') as spawn, \
             patch('pathlib.Path.mkdir') as mkdir:
            with self.assertRaises(Cancelled):
                engine.start(region=(0, 0, 100, 100), cancel=event)
        spawn.assert_not_called()
        mkdir.assert_not_called()

    def test_options_preserved_in_ffmpeg_command(self):
        for audio in ('none', 'system', 'mic', 'both'):
            for fps in (30, 60):
                for quality, crf in (('normal', '28'), ('high', '23')):
                    with self.subTest(audio=audio, fps=fps, quality=quality):
                        engine = RecordingEngine()
                        child = Mock()
                        child.poll.return_value = None
                        with patch('engine.recording.subprocess.Popen', return_value=child) as spawn, \
                             patch('pathlib.Path.mkdir'), \
                             patch.object(engine, 'get_default_audio_devices', return_value=('sink.monitor', 'mic')):
                            output = engine.start(region=(-10, 4, 101, 99), audio=audio,
                                                  fps=fps, quality=quality)
                        command = spawn.call_args.args[0]
                        self.assertIn('100x98', command)
                        self.assertIn(str(fps), command)
                        self.assertIn(crf, command)
                        self.assertTrue(any(arg.endswith('+-10,4') for arg in command))
                        self.assertEqual(output.parent, Path.home() / 'Videos' / 'Recordings')
                        if audio == 'none':
                            self.assertIn('-an', command)
                        if audio in ('system', 'both'):
                            self.assertIn('sink.monitor', command)
                        if audio in ('mic', 'both'):
                            self.assertIn('mic', command)
                        if audio == 'both':
                            self.assertIn('[1:a][2:a]amix=inputs=2:duration=longest:dropout_transition=0[a]', command)

    def test_monitor_supports_negative_offsets(self):
        engine = RecordingEngine()
        result = Mock(stdout='Monitors: 1\n 0: +DP-1 101/1x99/1-100+20 DP-1\n')
        with patch('engine.recording.subprocess.run', return_value=result):
            self.assertEqual(engine.get_monitor_geometry('DP-1'), (-100, 20, 101, 99))

    def test_exited_ffmpeg_is_reaped_by_stop(self):
        engine = RecordingEngine()
        engine.process = Mock()
        engine.process.poll.return_value = 1
        process = engine.process
        engine.output_file = Path('file.mkv')
        process.wait.return_value = 1
        with self.assertRaisesRegex(RuntimeError, 'FFmpeg'):
            engine.stop()
        process.wait.assert_called_once()
        process.send_signal.assert_not_called()
        self.assertIsNone(engine.process)

    def test_saved_requires_successful_exit_and_nonempty_file(self):
        for code, exists, size, saved in ((0, True, 123, True), (255, True, 123, True),
                                          (1, True, 123, False), (0, False, 0, False),
                                          (0, True, 0, False)):
            with self.subTest(code=code, exists=exists, size=size):
                engine = RecordingEngine()
                engine.process = Mock(stdout=None, stderr=None)
                engine.process.poll.return_value = code
                engine.process.wait.return_value = code
                engine.output_file = Path('file.mkv')
                with patch('pathlib.Path.is_file', return_value=exists), \
                     patch('pathlib.Path.stat', return_value=Mock(st_size=size)):
                    if saved:
                        self.assertEqual(engine.stop(), Path('file.mkv'))
                    else:
                        with self.assertRaises(RuntimeError):
                            engine.stop()
                self.assertIsNone(engine.process)

    def test_selection_uses_red_outline_and_normalized_geometry(self):
        child = Mock(stdout=None, stderr=None, returncode=0)
        child.communicate.return_value = ('-12 20 101 99', '')
        child.poll.return_value = 0
        child.wait.return_value = 0
        with patch('engine.lifecycle.subprocess.Popen', return_value=child) as spawn:
            geometry = RecordingEngine().select_region()
        self.assertEqual(spawn.call_args.args[0],
                         ['slop', '--color=1,0.15,0.15,1', '-f', '%x %y %w %h'])
        self.assertEqual(geometry, (-12, 20, 100, 98))
        child.wait.assert_called_once()

    def test_selection_cancellation_owns_and_reaps_slop(self):
        engine = RecordingEngine()
        owner = OwnedProcesses()
        event = threading.Event()
        child = Mock()
        child.poll.return_value = None
        def communicate(timeout):
            event.set()
            raise subprocess.TimeoutExpired('slop', timeout)
        child.communicate.side_effect = communicate
        with patch('engine.lifecycle.subprocess.Popen', return_value=child):
            with self.assertRaises(Cancelled):
                engine.select_region(cancel=event, owner=owner)
            owner.cleanup()
        child.terminate.assert_called_once()
        child.wait.assert_called_once()

    def test_cancel_during_audio_lookup_no_output(self):
        engine = RecordingEngine()
        event = threading.Event()
        def audio(mode):
            event.set()
            return []
        with patch.object(engine, 'build_audio_arguments', side_effect=audio), \
             patch('pathlib.Path.mkdir') as mkdir, patch('engine.recording.subprocess.Popen') as spawn:
            with self.assertRaises(Cancelled):
                engine.start(region=(0, 0, 100, 100), audio='both', cancel=event)
        mkdir.assert_not_called()
        spawn.assert_not_called()
