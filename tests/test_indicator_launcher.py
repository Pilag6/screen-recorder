import unittest
from unittest.mock import patch

from engine.indicator_launcher import indicator_plan


class IndicatorTests(unittest.TestCase):
    def test_unsafe_first_show_always_falls_back_without_spawning(self):
        for capture in ((0, 0, 1920, 1080), (10, 20, 100, 98), (-1920, 0, 1920, 1080)):
            with self.subTest(capture=capture), patch('pathlib.Path.is_file', return_value=True), \
                 patch('subprocess.Popen') as spawn:
                plan = indicator_plan(capture)
                self.assertIsNone(plan.command)
                self.assertIn('before', plan.reason)
                self.assertIn('in-window', plan.reason)
                spawn.assert_not_called()

    def test_missing_indicator_uses_honest_fallback(self):
        with patch('pathlib.Path.is_file', return_value=False):
            plan = indicator_plan((0, 0, 100, 100))
        self.assertIsNone(plan.command)
        self.assertIn('missing', plan.reason)
