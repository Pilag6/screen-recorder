"""Preferences storage tests use only temporary configuration directories."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from preferences import Preferences, load_preferences, save_preferences, settings_path


class PreferencesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / 'screen-recorder' / 'settings.json'

    def write_document(self, document):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(document), encoding='utf-8')

    def test_absolute_xdg_root_and_home_fallback(self):
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.root)}):
            self.assertEqual(settings_path(), self.path)
        for xdg in ('', 'relative/config', '~/config'):
            with self.subTest(xdg=xdg), \
                 patch.dict(os.environ, {'XDG_CONFIG_HOME': xdg}), \
                 patch('preferences.Path.home', return_value=self.root):
                self.assertEqual(settings_path(),
                                 self.root / '.config/screen-recorder/settings.json')
        with patch.dict(os.environ, {}, clear=True), \
             patch('preferences.Path.home', return_value=self.root):
            self.assertEqual(settings_path(),
                             self.root / '.config/screen-recorder/settings.json')

    def test_missing_load_returns_defaults_without_creating_directories(self):
        self.assertEqual(load_preferences(self.path), Preferences())
        self.assertFalse(self.path.parent.exists())

    def test_roundtrip_creates_directory_and_uses_integer_fps(self):
        expected = Preferences(source='DP-1', audio='mic', fps=60, quality='normal')
        self.assertTrue(save_preferences(expected, self.path))
        self.assertEqual(load_preferences(self.path), expected)
        document = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(document, {'version': 1, 'source': 'DP-1',
                                    'audio': 'mic', 'fps': 60, 'quality': 'normal',
                                    'output_dir': expected.output_dir})
        self.assertIs(type(document['fps']), int)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_atomic_replace_failure_keeps_old_settings_and_cleans_temporary_file(self):
        self.assertTrue(save_preferences(Preferences(), self.path))
        original = self.path.read_bytes()
        with patch('preferences.os.replace', side_effect=OSError('denied')):
            self.assertFalse(save_preferences(Preferences(audio='none'), self.path))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_directory_and_write_errors_are_nonfatal(self):
        with patch('preferences.Path.mkdir', side_effect=OSError('denied')):
            self.assertFalse(save_preferences(Preferences(), self.path))
        with patch('preferences.tempfile.NamedTemporaryFile', side_effect=OSError('full')):
            self.assertFalse(save_preferences(Preferences(), self.path))
        with patch('preferences.Path.open', side_effect=OSError('unreadable')):
            self.assertEqual(load_preferences(self.path), Preferences())

    def test_malformed_encoding_and_json_are_nonfatal(self):
        self.path.parent.mkdir()
        for contents in (b'{', b'\xff', b'null', b'[]', b'"settings"'):
            with self.subTest(contents=contents):
                self.path.write_bytes(contents)
                self.assertEqual(load_preferences(self.path), Preferences())

    def test_missing_old_future_and_wrong_type_versions_ignore_document(self):
        for version in (None, 0, 2, '1', True, 1.0):
            with self.subTest(version=version):
                document = {'source': 'DP-1', 'audio': 'none', 'fps': 60,
                            'quality': 'normal'}
                if version is not None:
                    document['version'] = version
                self.write_document(document)
                self.assertEqual(load_preferences(self.path), Preferences())

    def test_invalid_fields_default_independently(self):
        valid = {'version': 1, 'source': 'DP-1', 'audio': 'system',
                 'fps': 60, 'quality': 'normal', 'unknown': 'ignored'}
        invalid = {'source': (None, '', 7, [], {}),
                   'audio': (None, 'invalid', True, [], {}),
                   'fps': (None, True, False, '60', 60.0, 24, [], {}),
                   'quality': (None, 'invalid', True, [], {})}
        defaults = Preferences()
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.write_document({**valid, field: value})
                    expected = {key: valid[key] for key in invalid}
                    expected[field] = getattr(defaults, field)
                    self.assertEqual(load_preferences(self.path), Preferences(**expected))

    def test_v1_missing_output_folder_defaults_without_creating_it(self):
        self.write_document({'version': 1, 'audio': 'mic'})
        with patch('pathlib.Path.mkdir') as mkdir:
            restored = load_preferences(self.path)
        self.assertEqual(restored.output_dir, str(Path.home() / 'Videos/Recordings'))
        self.assertEqual(restored.audio, 'mic')
        mkdir.assert_not_called()

    def test_custom_output_roundtrip_and_expansion_are_side_effect_free(self):
        folder = self.root / 'Clips con espacios' / '日本語'
        expected = Preferences(output_dir=str(folder), fps=60)
        self.assertTrue(save_preferences(expected, self.path))
        self.assertEqual(load_preferences(self.path), expected)
        self.assertFalse(folder.exists())
        self.write_document({'version': 1, 'output_dir': '~/Custom clips'})
        self.assertEqual(load_preferences(self.path).output_dir,
                         str(Path.home() / 'Custom clips'))

    def test_invalid_output_fields_default_independently(self):
        for value in (None, '', ' ', True, 7, [], {}, 'relative', '/bad\x00path', '~no-such-recorder-user/folder'):
            with self.subTest(value=value):
                self.write_document({'version': 1, 'output_dir': value, 'fps': 60})
                restored = load_preferences(self.path)
                self.assertEqual(restored.output_dir, Preferences().output_dir)
                self.assertEqual(restored.fps, 60)

    def test_default_api_uses_only_temporary_xdg_config(self):
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': str(self.root)}):
            self.assertEqual(load_preferences(), Preferences())
            self.assertFalse(self.path.parent.exists())
            self.assertTrue(save_preferences(Preferences(audio='system')))
            self.assertEqual(load_preferences(), Preferences(audio='system'))

    def test_home_resolution_errors_are_nonfatal(self):
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': ''}), \
             patch('preferences.Path.home', side_effect=RuntimeError('no home')):
            self.assertEqual(load_preferences(), Preferences())
            self.assertFalse(save_preferences(Preferences()))

    def test_serialization_and_flush_errors_preserve_existing_settings(self):
        self.assertTrue(save_preferences(Preferences(), self.path))
        original = self.path.read_bytes()
        for target in ('preferences.json.dump', 'preferences.os.fsync'):
            with self.subTest(target=target), \
                 patch(target, side_effect=OSError('write failed')):
                self.assertFalse(save_preferences(Preferences(audio='mic'), self.path))
            self.assertEqual(self.path.read_bytes(), original)
            self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_every_supported_audio_and_quality_value_restores(self):
        for audio in ('none', 'system', 'mic', 'both'):
            for quality in ('normal', 'high'):
                with self.subTest(audio=audio, quality=quality):
                    expected = Preferences(audio=audio, quality=quality)
                    self.assertTrue(save_preferences(expected, self.path))
                    self.assertEqual(load_preferences(self.path), expected)


if __name__ == '__main__':
    unittest.main()
