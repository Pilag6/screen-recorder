"""Release metadata must be usable without GTK or the recording application."""
import builtins
import importlib.util
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


class VersionTests(unittest.TestCase):
    def test_release_version_without_application_imports(self):
        path = ROOT / 'version.py'
        self.assertTrue(path.is_file(), 'Central version.py is missing')
        original_import = builtins.__import__

        def independent_import(name, *args, **kwargs):
            if name.split('.')[0] in ('gi', 'cairo', 'main', 'recorder', 'preferences', 'engine'):
                raise AssertionError('Version metadata imports application code: ' + name)
            return original_import(name, *args, **kwargs)

        spec = importlib.util.spec_from_file_location('release_version', path)
        module = importlib.util.module_from_spec(spec)
        with mock.patch('builtins.__import__', side_effect=independent_import):
            spec.loader.exec_module(module)
        self.assertEqual(module.VERSION, '1.0.0')


if __name__ == '__main__':
    unittest.main()
