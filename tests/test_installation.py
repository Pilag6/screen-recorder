"""Installation tests never activate GTK or use the real HOME/XDG tree."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

try:
    import gi
    gi.require_version('Gio', '2.0')
    from gi.repository import Gio
except (ImportError, ValueError):
    Gio = None


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('installation', ROOT / 'installation.py')
installation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installation)


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        # Exercise shell and desktop escaping, not just the easy space case.
        self.home = self.base / "home space ' quote \" $money %f \\ end"
        self.home.mkdir()
        self.env = {'HOME': str(self.home), 'PATH': '/usr/bin:/bin'}
        for name in ('DATA_HOME', 'CONFIG_HOME', 'CACHE_HOME', 'STATE_HOME',
                     'RUNTIME_DIR', 'DATA_DIRS', 'CONFIG_DIRS'):
            path = self.base / ('xdg ' + name + " ' \" $ % \\")
            path.mkdir()
            self.env['XDG_' + name] = str(path)
        self.environment = mock.patch.dict(os.environ, self.env, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.layout = installation.Layout.from_environment()
        self.source = self.base / 'checkout'
        self.source.mkdir()
        for name in ('main.py', 'recorder.py', 'preferences.py', 'version.py',
                     'LICENSE', 'THIRD_PARTY.md', 'installation.py', 'uninstall.sh'):
            shutil.copyfile(ROOT / name, self.source / name)
        for name in ('engine', 'helpers', 'assets'):
            shutil.copytree(ROOT / name, self.source / name,
                            ignore=shutil.ignore_patterns('__pycache__'))
        self.dependencies = mock.patch.object(installation, 'check_dependencies')
        self.dependencies.start()
        self.addCleanup(self.dependencies.stop)

    def install(self):
        installation.install(self.source, self.layout)

    def manifest(self):
        return json.loads(self.layout.manifest.read_text())

    def test_payload_repeat_and_helper_bytes(self):
        self.install()
        first = self.layout.manifest.read_bytes()
        self.install()
        self.assertEqual(first, self.layout.manifest.read_bytes())
        expected = {'main.py', 'recorder.py', 'preferences.py', 'version.py',
                    'LICENSE', 'THIRD_PARTY.md', 'installation.py', 'uninstall.sh'}
        for directory, pattern in (('engine', '**/*.py'), ('helpers', '*.py'), ('assets', '*')):
            expected.update(str(path.relative_to(self.source))
                            for path in (self.source / directory).glob(pattern))
        self.assertEqual(set(self.manifest()['files']),
                         {'payload/' + name for name in expected} | {'launcher', 'desktop'})
        for name in expected:
            self.assertEqual((self.source / name).read_bytes(),
                             (self.layout.payload / name).read_bytes())
        self.assertEqual(hashlib.sha256((self.layout.payload / 'helpers/recording-indicator.py')
                                       .read_bytes()).hexdigest(),
                         '331cef288c4168bbea54507717db68ed79a168b54f05cf407376a9b6a4a2303d')
        self.assertIn('io.github.screenrecorder.ScreenRecorder',
                      (self.layout.payload / 'main.py').read_text())
        self.assertTrue(os.access(self.layout.launcher, os.X_OK))

    def test_release_metadata_payload(self):
        payload = installation.collect_payload(ROOT)
        for name in ('version.py', 'LICENSE', 'THIRD_PARTY.md'):
            with self.subTest(name=name):
                key = 'payload/' + name
                self.assertIn(key, set(payload))
                content, mode = payload[key]
                self.assertEqual(content, (ROOT / name).read_bytes())
                self.assertEqual(mode, 0o644)
                self.assertEqual(self.layout.target(key), self.layout.payload / name)

    def test_missing_release_metadata_refused_before_writes(self):
        for name in ('version.py', 'LICENSE', 'THIRD_PARTY.md'):
            with self.subTest(name=name):
                path = self.source / name
                content = path.read_bytes()
                path.unlink()
                with self.assertRaisesRegex(installation.InstallError, 'missing runtime file'):
                    self.install()
                self.assertFalse(self.layout.payload.exists())
                path.write_bytes(content)

    def test_installed_version_independent_of_checkout(self):
        (self.source / 'main.py').write_text('from version import VERSION\nprint(VERSION)\n')
        self.install()
        self.source.rename(self.base / 'unavailable checkout')
        result = subprocess.run([str(self.layout.launcher)], cwd=self.base,
                                env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '1.0.0')

    def test_missing_owned_files_restored_without_duplicate_entries(self):
        self.install()
        self.layout.launcher.unlink()
        (self.layout.payload / 'engine/recording.py').unlink()
        self.install()
        self.assertTrue(self.layout.launcher.exists())
        self.assertEqual((self.layout.payload / 'engine/recording.py').read_bytes(),
                         (self.source / 'engine/recording.py').read_bytes())
        self.assertEqual(list(self.layout.desktop.parent.iterdir()), [self.layout.desktop])

    def test_missing_runtime_icon_refused_before_writes(self):
        (self.source / 'assets/screen-recorder-icon.png').unlink()
        with self.assertRaisesRegex(installation.InstallError, 'icon'):
            self.install()
        self.assertFalse(self.layout.payload.exists())

    def test_launcher_independent_of_checkout_and_path_python(self):
        (self.source / 'main.py').write_text(
            'import sys\nfrom pathlib import Path\n'
            'print(sys.executable)\nprint(Path(__file__).parent)\n')
        self.install()
        # Move source away, without deleting it or running the real GUI.
        self.source.rename(self.base / 'unavailable checkout')
        fake_bin = self.base / 'venv-bin'
        fake_bin.mkdir()
        fake_python = fake_bin / 'python3'
        fake_python.write_text('#!/bin/sh\nexit 91\n')
        fake_python.chmod(0o755)
        env = dict(self.env, PATH=str(fake_bin) + ':/usr/bin:/bin')
        result = subprocess.run([str(self.layout.launcher)], cwd=self.base,
                                env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['/usr/bin/python3', str(self.layout.payload)])

    def test_desktop_exec_round_trip_and_identity(self):
        self.install()
        text = self.layout.desktop.read_text()
        self.assertIn('StartupWMClass=io.github.screenrecorder.ScreenRecorder', text)
        self.assertIn('DBusActivatable=false', text)
        value = next(line[5:] for line in text.splitlines() if line.startswith('Exec='))
        # Desktop string unescaping precedes Exec quoting/field-code processing.
        value = self.unescape(value)
        self.assertTrue(value.startswith('/bin/sh '))
        value = value[len('/bin/sh '):]
        self.assertIn('%%f', value)
        self.assertTrue(value.startswith('"') and value.endswith('"'))
        # Exec quoting differs from shlex: it unescapes $, `, quotes and backslashes.
        argument = ''
        pos = 1
        while pos < len(value) - 1:
            if value[pos] == '\\':
                pos += 1
                self.assertIn(value[pos], '\\"`$')
            argument += value[pos]
            pos += 1
        self.assertEqual(argument.replace('%%', '%'), str(self.layout.launcher))
        icon = next(line[5:] for line in text.splitlines() if line.startswith('Icon='))
        self.assertEqual(self.unescape(icon), str(self.layout.payload / 'assets/screen-recorder-icon.png'))
        self.assertEqual(self.layout.desktop.name, 'screen-recorder.desktop')

    @unittest.skipIf(Gio is None, 'GI/Gio unavailable')
    def test_desktop_gio_percent_path(self):
        self.check_gio_desktop(self.base / 'home %f %U %%')

    @unittest.skipIf(Gio is None, 'GI/Gio unavailable')
    def test_desktop_gio_combined_punctuation_path(self):
        self.check_gio_desktop(self.base / "home space ' quote \" $money %f \\ ` end")

    def check_gio_desktop(self, home):
        home.mkdir()
        env = dict(self.env, HOME=str(home))
        output = self.base / 'gio-fixture-result.json'
        # Only this inert fixture can be launched: no real application imports.
        (self.source / 'main.py').write_text(
            'import json, os, sys\nfrom pathlib import Path\n'
            'result = {"python": sys.executable, "payload": str(Path(__file__).parent),\n'
            '          "args": sys.argv[1:], "env": dict(os.environ)}\n'
            f'Path({str(output)!r}).write_text(json.dumps(result))\n')
        with mock.patch.dict(os.environ, env, clear=True):
            layout = installation.Layout.from_environment()
            installation.install(self.source, layout)
            app = Gio.DesktopAppInfo.new_from_filename(str(layout.desktop))
            self.assertIsNotNone(app, 'Real Gio must accept the installed desktop entry')
            self.assertEqual(app.get_executable(), '/bin/sh')
            self.assertIn('%%f', app.get_commandline())
            context = Gio.AppLaunchContext()
            for name, value in env.items():
                context.setenv(name, value)
            self.assertTrue(app.launch([], context))
            deadline = time.monotonic() + 5
            while not output.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(output.exists(), 'Gio did not run the harmless fixture')
            # A newly created file may not yet have its complete JSON contents.
            while True:
                try:
                    result = json.loads(output.read_text())
                    break
                except json.JSONDecodeError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
            self.assertEqual(result['python'], '/usr/bin/python3')
            self.assertEqual(result['payload'], str(layout.payload))
            self.assertEqual(result['args'], [])
            for name, value in env.items():
                self.assertEqual(result['env'][name], value)

    @staticmethod
    def unescape(value):
        result = ''
        pos = 0
        while pos < len(value):
            if value[pos] == '\\':
                pos += 1
                result += {'s': ' ', 'n': '\n', 't': '\t', 'r': '\r', '\\': '\\'}[value[pos]]
            else:
                result += value[pos]
            pos += 1
        return result

    def test_foreign_launcher_desktop_and_payload_refused_before_writes(self):
        for target in (self.layout.launcher, self.layout.desktop, self.layout.payload):
            with self.subTest(target=target):
                target.parent.mkdir(parents=True, exist_ok=True)
                if target == self.layout.payload:
                    target.mkdir()
                else:
                    target.write_text('foreign')
                with self.assertRaises(installation.InstallError):
                    self.install()
                self.assertFalse(self.layout.manifest.exists())
                if target.is_dir():
                    target.rmdir()
                else:
                    self.assertEqual(target.read_text(), 'foreign')
                    target.unlink()

    def test_symlink_destination_and_ancestor_refused(self):
        outside = self.base / 'outside'
        outside.mkdir()
        self.layout.launcher.parent.mkdir(parents=True)
        self.layout.launcher.symlink_to(outside / 'not-created')
        with self.assertRaises(installation.InstallError):
            self.install()
        self.assertEqual(list(outside.iterdir()), [])
        self.layout.launcher.unlink()
        self.layout.payload.parent.rmdir()
        self.layout.payload.parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(installation.InstallError):
            self.install()
        self.assertEqual(list(outside.iterdir()), [])

    def test_modified_owned_file_blocks_repeat(self):
        self.install()
        self.layout.launcher.write_text('user replacement')
        before = self.layout.manifest.read_bytes()
        with self.assertRaises(installation.InstallError):
            self.install()
        self.assertEqual(self.layout.launcher.read_text(), 'user replacement')
        self.assertEqual(self.layout.manifest.read_bytes(), before)

    def test_uninstall_preserves_modified_foreign_config_recordings(self):
        self.install()
        modified = self.layout.payload / 'main.py'
        modified.write_text('my changes')
        foreign = self.layout.payload / 'user notes.txt'
        foreign.write_text('keep')
        self.layout.desktop.write_text('foreign replacement')
        config = Path(os.environ['XDG_CONFIG_HOME']) / 'screen-recorder.json'
        config.write_text('preferences')
        recording = self.home / 'recording.mp4'
        recording.write_bytes(b'keep recording')
        preserved = installation.uninstall(self.layout)
        self.assertIn(str(modified), preserved)
        for path in (modified, foreign, self.layout.desktop, config, recording):
            self.assertTrue(path.exists(), path)
        self.assertFalse(self.layout.launcher.exists())
        self.assertFalse((self.layout.payload / 'recorder.py').exists())
        # The manifest keeps only remaining owned entries for later safe retry.
        self.assertEqual(installation.uninstall(self.layout), preserved)

    def test_clean_uninstall_and_repeat_noop(self):
        self.install()
        self.assertEqual(installation.uninstall(self.layout), [])
        self.assertFalse(self.layout.payload.exists())
        self.assertFalse(self.layout.desktop.exists())
        self.assertEqual(installation.uninstall(self.layout), [])

    def test_uninstall_without_manifest_never_adopts(self):
        self.layout.launcher.parent.mkdir(parents=True)
        self.layout.launcher.write_text('foreign')
        self.assertEqual(installation.uninstall(self.layout), [])
        self.assertEqual(self.layout.launcher.read_text(), 'foreign')
        self.layout.payload.mkdir()
        with self.assertRaises(installation.InstallError):
            installation.uninstall(self.layout)

    def test_manifest_traversal_invalid_hash_and_wrong_location_refused(self):
        self.install()
        original = self.manifest()
        for mutation in ('traversal', 'hash', 'home'):
            with self.subTest(mutation=mutation):
                data = json.loads(json.dumps(original))
                if mutation == 'traversal':
                    data['files']['payload/../../victim'] = '0' * 64
                elif mutation == 'hash':
                    data['files']['launcher']['sha256'] = 'bad'
                else:
                    data['home'] = str(self.base)
                self.layout.manifest.write_text(json.dumps(data))
                with self.assertRaises(installation.InstallError):
                    installation.uninstall(self.layout)
                self.assertTrue(self.layout.launcher.exists())

    def test_relative_xdg_and_home_rejected(self):
        for variable in ('HOME', 'XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME',
                         'XDG_STATE_HOME', 'XDG_RUNTIME_DIR', 'XDG_DATA_DIRS', 'XDG_CONFIG_DIRS'):
            with self.subTest(variable=variable), mock.patch.dict(os.environ, {variable: 'relative'}):
                with self.assertRaises(installation.InstallError):
                    installation.Layout.from_environment()

    def test_new_nested_engine_file(self):
        nested = self.source / 'engine' / 'nested'
        nested.mkdir()
        (nested / 'module.py').write_text('# nested\n')
        self.install()
        self.assertTrue((self.layout.payload / 'engine/nested/module.py').exists())
        self.assertEqual(installation.uninstall(self.layout), [])
        self.assertFalse(self.layout.payload.exists())

    def test_foreign_new_file_and_directory_on_update_refused(self):
        self.install()
        (self.source / 'engine' / 'new.py').write_text('# new runtime')
        collision = self.layout.payload / 'engine' / 'new.py'
        collision.write_text('user file')
        with self.assertRaises(installation.InstallError):
            self.install()
        self.assertEqual(collision.read_text(), 'user file')
        collision.unlink()
        (self.source / 'engine' / 'new').mkdir()
        (self.source / 'engine' / 'new' / 'nested.py').write_text('# new nested')
        (self.layout.payload / 'engine' / 'new').mkdir()
        with self.assertRaises(installation.InstallError):
            self.install()
        self.assertFalse((self.layout.payload / 'engine/new/nested.py').exists())

    def test_uninstall_symlink_replacement_fails_closed(self):
        self.install()
        outside = self.base / 'outside.txt'
        outside.write_text('foreign')
        self.layout.launcher.unlink()
        self.layout.launcher.symlink_to(outside)
        with self.assertRaises(installation.InstallError):
            installation.uninstall(self.layout)
        self.assertEqual(outside.read_text(), 'foreign')
        self.assertTrue((self.layout.payload / 'main.py').exists())

    def test_mode_change_preserved_and_user_directory_never_removed(self):
        self.install()
        self.layout.launcher.chmod(0o644)
        user_dir = self.layout.payload / 'engine' / 'user-dir'
        user_dir.mkdir()
        (user_dir / 'note').write_text('keep')
        preserved = installation.uninstall(self.layout)
        self.assertEqual(preserved, [str(self.layout.launcher)])
        self.assertEqual((user_dir / 'note').read_text(), 'keep')
        self.assertTrue(self.layout.manifest.exists())

    def test_foreign_user_file_without_modifications_keeps_payload(self):
        self.install()
        user_file = self.layout.payload / 'user-file'
        user_file.write_text('keep')
        self.assertEqual(installation.uninstall(self.layout), [])
        self.assertEqual(user_file.read_text(), 'keep')
        self.assertFalse(self.layout.manifest.exists())
        # Ownership is relinquished, never implicitly regained.
        with self.assertRaises(installation.InstallError):
            self.install()

    def test_default_data_home_and_empty_xdg(self):
        with mock.patch.dict(os.environ, {'XDG_DATA_HOME': ''}):
            self.assertEqual(installation.Layout.from_environment().data,
                             self.home / '.local/share')

    def test_external_marker_required_even_if_manifest_hash_matches(self):
        self.install()
        self.layout.launcher.write_text('#!/bin/sh\n# foreign launcher\n')
        data = self.manifest()
        data['files']['launcher'] = installation.file_record(self.layout.launcher.read_bytes(), 0o755)
        self.layout.manifest.write_text(json.dumps(data))
        with self.assertRaises(installation.InstallError):
            self.install()
        self.assertEqual(installation.uninstall(self.layout), [str(self.layout.launcher)])
        self.assertIn('foreign launcher', self.layout.launcher.read_text())

    def test_duplicate_and_malformed_manifest_refused(self):
        self.install()
        for content in ('{"owner": "a", "owner": "b"}', 'not json', '[]'):
            with self.subTest(content=content):
                self.layout.manifest.write_text(content)
                with self.assertRaises(installation.InstallError):
                    installation.uninstall(self.layout)
                self.assertTrue(self.layout.launcher.exists())

    def test_symlink_source_refused(self):
        target = self.source / 'helpers' / 'extra.py'
        target.symlink_to(self.source / 'main.py')
        with self.assertRaises(installation.InstallError):
            self.install()
        self.assertFalse(self.layout.payload.exists())

    def test_missing_dependency_leaves_no_install(self):
        with mock.patch.object(installation, 'check_dependencies',
                               side_effect=installation.InstallError('Missing dependencies: slop')):
            with self.assertRaisesRegex(installation.InstallError, 'slop'):
                self.install()
        self.assertFalse(self.layout.payload.exists())

    def test_dependency_probe_inert_and_system_python(self):
        self.dependencies.stop()
        with mock.patch.object(installation.shutil, 'which', return_value='/usr/bin/tool'), \
             mock.patch.object(installation.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, '', '')
            installation.check_dependencies()
            command = run.call_args.args[0]
            self.assertEqual(command[:3], ['/usr/bin/python3', '-I', '-B'])
            code = command[-1]
            self.assertIn('require_version', code)
            self.assertIn('cairo', code)
            for forbidden in ('Gtk.init', 'Gtk.Application', 'Gtk.main', 'pactl', 'ffmpeg'):
                self.assertNotIn(forbidden, code)
        with mock.patch.object(installation.shutil, 'which', return_value=None), \
             mock.patch.object(installation.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 1, '', 'No module named gi')
            with self.assertRaisesRegex(installation.InstallError, 'ffmpeg.*xrandr.*slop.*pactl'):
                installation.check_dependencies()

    def test_shell_wrappers_outside_cwd_and_installed_uninstaller(self):
        self.install()
        result = subprocess.run(['/bin/sh', str(self.layout.payload / 'uninstall.sh')],
                                cwd=self.base, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.layout.payload.exists())
        # Invalid XDG is rejected by the real root installer before dependency probing.
        env = dict(self.env, XDG_DATA_HOME='relative')
        result = subprocess.run(['/bin/sh', str(ROOT / 'install.sh')],
                                cwd=self.base, env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('absolute', result.stderr)


if __name__ == '__main__':
    unittest.main()
