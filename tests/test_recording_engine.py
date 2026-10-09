import signal
import subprocess
import threading
import tempfile
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
                             patch('engine.recording.prepare_output_directory',
                                   return_value=Path.home() / 'Videos/Recordings'), \
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

    def test_output_options_default_and_legacy_arguments(self):
        options = RecordingOptions('region', 'none', 30, 'high')
        self.assertEqual(options.output_dir, str(Path.home() / 'Videos/Recordings'))
        custom = RecordingOptions('region', 'none', 30, 'high', '/custom clips/日本語')
        custom.validate()
        self.assertEqual(custom.to_arguments(), options.to_arguments())
        for value in ('relative', '', '/bad\x00path', None, 123):
            with self.subTest(value=value), self.assertRaises(ValueError):
                RecordingOptions('region', 'none', 30, 'high', value).validate()

    def test_directory_helper_creates_parents_and_removes_probe(self):
        from recorder import prepare_output_directory
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'new' / 'Clips 日本語'
            self.assertEqual(prepare_output_directory(str(folder)), folder)
            self.assertTrue(folder.is_dir())
            self.assertEqual(list(folder.iterdir()), [])
            file = Path(root) / 'not-a-directory'
            file.write_text('file')
            with self.assertRaises(OSError):
                prepare_output_directory(str(file))

    def test_probe_write_failure_removes_probe(self):
        from recorder import prepare_output_directory
        factory = tempfile.NamedTemporaryFile
        with tempfile.TemporaryDirectory() as root:
            for method in ('write', 'flush'):
                def failing_probe(**kwargs):
                    probe = factory(**kwargs)
                    setattr(probe, method, Mock(side_effect=PermissionError('read-only')))
                    return probe
                with self.subTest(method=method), \
                     patch('recorder.tempfile.NamedTemporaryFile', side_effect=failing_probe):
                    with self.assertRaises(PermissionError):
                        prepare_output_directory(root)
                self.assertEqual(list(Path(root).iterdir()), [])
            with patch('recorder.os.fsync', side_effect=PermissionError('read-only')):
                with self.assertRaises(PermissionError):
                    prepare_output_directory(root)
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_directory_creation_and_probe_open_denied_never_spawn(self):
        with tempfile.TemporaryDirectory() as root:
            for target in ('recorder.Path.mkdir', 'recorder.tempfile.NamedTemporaryFile'):
                with self.subTest(target=target), \
                     patch(target, side_effect=PermissionError('denied')), \
                     patch('engine.recording.subprocess.Popen') as spawn:
                    with self.assertRaises(PermissionError):
                        RecordingEngine().start(region=(0, 0, 100, 100), output_dir=root)
                    spawn.assert_not_called()
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_custom_output_is_ffmpeg_destination_without_default_directory(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'custom clips' / '日本語'
            with patch('engine.recording.subprocess.Popen') as spawn:
                output = RecordingEngine().start(region=(0, 0, 100, 100),
                                                  output_dir=str(folder))
            self.assertEqual(output.parent, folder)
            self.assertEqual(spawn.call_args.args[0][-1], str(output))
            self.assertEqual(list(folder.iterdir()), [])  # Only a mocked capture.

    def test_invalid_or_unwritable_output_never_spawns(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / 'file'
            file.touch()
            for folder in ('relative', str(file)):
                with self.subTest(folder=folder), \
                     patch('engine.recording.subprocess.Popen') as spawn:
                    with self.assertRaises((ValueError, OSError)):
                        RecordingEngine().start(region=(0, 0, 100, 100), output_dir=folder)
                    spawn.assert_not_called()
            with patch('recorder.os.fsync', side_effect=PermissionError('denied')), \
                 patch('engine.recording.subprocess.Popen') as spawn:
                with self.assertRaises(PermissionError):
                    RecordingEngine().start(region=(0, 0, 100, 100), output_dir=root)
                spawn.assert_not_called()
            self.assertEqual(list(Path(root).iterdir()), [file])

    def test_cancel_during_folder_validation_prevents_spawn(self):
        event = threading.Event()
        def prepare(folder):
            event.set()
            return Path(folder)
        with patch('engine.recording.prepare_output_directory', side_effect=prepare), \
             patch('engine.recording.subprocess.Popen') as spawn:
            with self.assertRaises(Cancelled):
                RecordingEngine().start(region=(0, 0, 100, 100), cancel=event,
                                        output_dir='/custom clips')
        spawn.assert_not_called()

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
