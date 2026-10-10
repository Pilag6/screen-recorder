import hashlib
import os
import runpy
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from engine.indicator_launcher import (
    HELPER_SHA256, INDICATOR_SCRIPT, helper_supported,
    indicator_plan, safe_position, PlacementGate, guarded_window_class, execute_helper,
)
from types import SimpleNamespace


class IndicatorTests(unittest.TestCase):
    def test_repository_helper_bytes_satisfy_pinned_hash(self):
        helper = Path(__file__).resolve().parents[1] / 'helpers/recording-indicator.py'
        self.assertEqual(INDICATOR_SCRIPT, helper)
        self.assertTrue(helper.is_file())
        self.assertEqual(hashlib.sha256(helper.read_bytes()).hexdigest(), HELPER_SHA256)
        self.assertTrue(helper_supported())

    def test_helper_and_bootstrap_paths_ignore_home_and_cwd(self):
        root = Path(__file__).resolve().parents[1]
        bootstrap = root / 'engine/indicator_launcher.py'
        for home, cwd in (('/nonexistent/recorder-home', '/'),
                          ('/another/nonexistent-home', '/tmp')):
            with self.subTest(home=home, cwd=cwd), \
                 patch.dict(os.environ, {'HOME': home}), \
                 patch('os.getcwd', return_value=cwd):
                module = runpy.run_path(str(bootstrap))
                self.assertEqual(module['INDICATOR_SCRIPT'],
                                 root / 'helpers/recording-indicator.py')
                plan = module['indicator_plan']((-12, 0, 100, 98))
                self.assertIsNotNone(plan.command)
                self.assertEqual(plan.command[1], str(bootstrap))
                self.assertEqual(plan.command[-4:], ('-12', '0', '100', '98'))

    def test_actual_checksum_gate_rejects_changed_or_missing_bytes(self):
        for failure in ('changed', 'missing'):
            with self.subTest(failure=failure), \
                 patch.object(Path, 'read_bytes', return_value=b'changed helper',
                              side_effect=FileNotFoundError() if failure == 'missing' else None):
                self.assertFalse(helper_supported())
                self.assertIsNone(indicator_plan((0, 0, 100, 100)).command)

    def test_verified_helper_uses_project_bootstrap_not_direct_launch(self):
        with patch('engine.indicator_launcher.helper_supported', return_value=True):
            plan = indicator_plan((-12, 0, 100, 98))
        self.assertIsNotNone(plan.command)
        self.assertIn('indicator_launcher.py', plan.command[1])
        self.assertEqual(plan.command[-4:], ('-12', '0', '100', '98'))

    def test_missing_or_changed_helper_falls_back(self):
        with patch('engine.indicator_launcher.helper_supported', return_value=False):
            plan = indicator_plan((0, 0, 100, 100))
        self.assertIsNone(plan.command)
        self.assertIn('in-window', plan.reason)

    def test_candidates_contained_and_disjoint_using_measured_dimensions(self):
        monitors = ((-1920, 0, 1920, 1080), (0, 0, 1920, 1080))
        position = safe_position((0, 0, 1920, 1080), monitors, (201, 47))
        self.assertEqual(position, (-221, 20))
        self.assertIsNone(safe_position((0, 0, 1920, 1080), monitors[1:], (201, 47)))
        self.assertIsNone(safe_position((0, 0, 2, 2), ((0, 0, 50, 50),), (201, 47)))

    def gate(self, capture, actual=None):
        window = Mock()
        window.measure_hidden.return_value = (201, 47)
        window.place_hidden.return_value = actual or (179, 20, 201, 47)
        monitors = lambda: ((0, 0, 400, 200),)
        return PlacementGate(window, capture, monitors), window

    def test_no_visibility_until_final_native_geometry_is_safe(self):
        gate, window = self.gate((0, 100, 400, 100))
        self.assertTrue(gate.refresh())
        self.assertEqual([call[0] for call in window.method_calls],
                         ['hide', 'measure_hidden', 'place_hidden', 'reveal'])

    def test_final_geometry_overlap_fails_closed_before_reveal(self):
        gate, window = self.gate((0, 100, 400, 100), (179, 99, 201, 47))
        self.assertFalse(gate.refresh())
        window.reveal.assert_not_called()
        window.fail.assert_called_once()

    def test_full_capture_and_topology_change_fail_closed(self):
        gate, window = self.gate((0, 0, 400, 200))
        self.assertFalse(gate.refresh())
        window.reveal.assert_not_called()
        gate, window = self.gate((0, 100, 400, 100))
        self.assertTrue(gate.refresh())
        window.reset_mock()
        gate.monitors = lambda: ((0, 0, 800, 200),)
        self.assertFalse(gate.refresh())
        window.hide.assert_called_once()
        window.reveal.assert_not_called()
        window.fail.assert_called_once()

    def test_changed_topology_between_measure_and_reveal_is_invisible(self):
        gate, window = self.gate((0, 100, 400, 100))
        gate.monitors = Mock(side_effect=[((0, 0, 400, 200),), ((0, 0, 800, 200),)])
        self.assertFalse(gate.refresh())
        window.reveal.assert_not_called()

    def test_negative_offsets_and_boundary_touch_are_disjoint(self):
        self.assertEqual(safe_position((0, 0, 400, 200), ((-400, 0, 400, 200),), (201, 47)),
                         (-221, 20))
        self.assertIsNotNone(safe_position((0, 67, 400, 133), ((0, 0, 400, 200),), (201, 47)))

    def test_measurement_failure_is_invisible_fallback(self):
        gate, window = self.gate((0, 100, 400, 100))
        window.measure_hidden.side_effect = RuntimeError('no native geometry')
        self.assertFalse(gate.refresh())
        window.reveal.assert_not_called()
        window.fail.assert_called_once()


class InertToolkit:
    """A memory-only GTK/XShape adapter, not a GI import or helper launch."""
    def __init__(self):
        self.events = []
        self.idles = []
        self.timers = []
        toolkit = self

        class Native:
            def __init__(self):
                self.shape = False
                self.geometry = (0, 0, 201, 47)

            def shape_combine_region(self, region, x, y):
                self.shape = bool(region)
                toolkit.events.append(('shape', self.shape))

            def get_window_type(self):
                return 'TEMP'

            def get_geometry(self):
                return self.geometry

            def get_origin(self):
                return 1, *self.geometry[:2]

            def move_resize(self, x, y, w, h):
                toolkit.events.append(('move', self.shape))
                self.geometry = (x, y, w, h)

        class Window:
            def __init__(self, **kwargs):
                self.native = None
                self.child = Mock()
                self.screen = Mock()
                self.screen.get_n_monitors.return_value = 1
                self.screen.get_monitor_geometry.return_value = SimpleNamespace(
                    x=0, y=0, width=400, height=200)
                self.display = Mock()
                self.display.supports_shapes.return_value = True

            def get_children(self):
                return [self.child]

            def get_screen(self):
                return self.screen

            def get_display(self):
                return self.display

            def realize(self):
                if self.native is None:
                    self.native = Native()

            def get_window(self):
                return self.native

            def get_scale_factor(self):
                return 1

            def get_preferred_size(self):
                return None, SimpleNamespace(width=201, height=47)

            def get_size(self):
                return self.native.geometry[2:]

            def show_all(self):
                toolkit.events.append(('map', self.native.shape))
                if self.native.shape:
                    raise AssertionError('Mapped before empty bounding shape')

            def move(self, x, y):
                toolkit.events.append(('gtk-move', self.native.shape))

            def do_size_allocate(self, allocation):
                toolkit.events.append(('allocate', self.native.shape if self.native else False))

        self.Gtk = SimpleNamespace(Window=Window, main_quit=Mock())
        self.Gdk = SimpleNamespace(WindowType=SimpleNamespace(TEMP='TEMP'))
        self.GLib = SimpleNamespace(
            idle_add=lambda callback, *args: self.idles.append(lambda: callback(*args)),
            timeout_add=lambda interval, callback: self.timers.append(callback))
        self.cairo = SimpleNamespace(Region=lambda rect=None: rect,
                                     RectangleInt=lambda *values: values)

    def drain(self):
        for _ in range(20):
            if not self.idles:
                return
            self.idles.pop(0)()
        raise AssertionError('Idle allocation loop')

    def window(self):
        cls = guarded_window_class(self.Gtk, self.Gdk, self.GLib, self.cairo)
        window = cls()
        window.capture = (0, 100, 400, 100)
        return window


class BootstrapTests(unittest.TestCase):
    def test_initial_show_deferred_and_native_measurement_precedes_visibility(self):
        toolkit = InertToolkit()
        window = toolkit.window()
        window.show_all()
        self.assertFalse(toolkit.events)
        self.assertIsNone(window.native)
        window.prepare_gate()
        toolkit.drain()
        self.assertIn(('map', False), toolkit.events)
        self.assertIn(('move', False), toolkit.events)
        self.assertEqual(toolkit.events[-1], ('shape', True))
        self.assertEqual(window.native.geometry, (179, 20, 201, 47))

    def test_resize_masks_before_gtk_allocation_and_topology_masks_before_quit(self):
        toolkit = InertToolkit()
        window = toolkit.window()
        window.prepare_gate()
        toolkit.drain()
        window.do_size_allocate(None)
        self.assertIn(('allocate', False), toolkit.events)
        toolkit.drain()
        self.assertTrue(window.native.shape)
        window.topology_changed()
        self.assertFalse(window.native.shape)
        toolkit.Gtk.main_quit.assert_called_once()

    def test_scale_or_native_query_uncertainty_never_reveals(self):
        for mode in ('scale', 'shape', 'origin', 'allocation'):
            with self.subTest(mode=mode):
                toolkit = InertToolkit()
                window = toolkit.window()
                window.realize()
                if mode == 'scale':
                    window.get_scale_factor = lambda: 2
                if mode == 'shape':
                    window.display.supports_shapes.return_value = False
                if mode == 'origin':
                    window.native.get_origin = lambda: (0, 0, 0)
                if mode == 'allocation':
                    window.get_preferred_size = lambda: (None, SimpleNamespace(width=900, height=47))
                window.prepare_gate()
                toolkit.drain()
                self.assertNotIn(('shape', True), toolkit.events)
                toolkit.Gtk.main_quit.assert_called_once()

    def test_bootstrap_intercepts_position_and_timer_without_source_rewrite(self):
        import sys
        from types import ModuleType
        toolkit = InertToolkit()
        def main():
            toolkit.drain()
            toolkit.timers[0]()
            toolkit.drain()
        toolkit.Gtk.main = main
        repository = ModuleType('gi.repository')
        repository.Gtk, repository.GLib = toolkit.Gtk, toolkit.GLib
        # A synthetic API-contract fixture, NOT the installed helper.
        source = b'''from gi.repository import Gtk, GLib
class Indicator(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.capture = (0, 100, 400, 100)
        self.show_all()
        GLib.idle_add(self.position_indicator)
        GLib.timeout_add(250, self.update_timer)
    def position_indicator(self):
        raise AssertionError("unsafe original placement must be intercepted")
    def update_timer(self):
        assert not self.get_window().shape, "timer must change while masked"
        return True
Indicator()
Gtk.main()
'''
        original = toolkit.Gtk.Window
        with patch.dict(sys.modules, {'gi': ModuleType('gi'), 'gi.repository': repository}):
            self.assertEqual(execute_helper(source, toolkit.Gtk, toolkit.Gdk,
                                            toolkit.GLib, toolkit.cairo), 0)
        self.assertIs(toolkit.Gtk.Window, original)
        self.assertEqual(sum(event == ('shape', True) for event in toolkit.events), 2)
