"""Run the known, unmodified REC helper behind a fail-closed visibility gate.

Only an unscaled X11 POPUP with native shape support is supported. An empty
bounding shape hides even a mapped window (no compositor/opacity assumption).
The final native geometry is measured before restoring any visible pixels.
Unsupported helpers/backends, uncertain placement and topology changes exit;
the session worker then keeps the in-GTK timer instead. No GI imports at import.
"""

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path


INDICATOR_SCRIPT = Path.home() / '.local/bin/recording-indicator.py'


@dataclass(frozen=True)
class IndicatorPlan:
    command: tuple | None
    reason: str


# The interception contract depends on the exact helper inspected for T1.
# A helper upgrade must be reviewed, not silently executed with weaker guards.
HELPER_SHA256 = '331cef288c4168bbea54507717db68ed79a168b54f05cf407376a9b6a4a2303d'
FALLBACK = ('using in-window elapsed timer; this GTK window/timer may be recorded '
            'if it is inside the capture')


def helper_supported():
    try:
        return hashlib.sha256(INDICATOR_SCRIPT.read_bytes()).hexdigest() == HELPER_SHA256
    except OSError:
        return False


def indicator_plan(capture):
    if not helper_supported():
        return IndicatorPlan(None, 'REC helper missing or changed; ' + FALLBACK)
    command = (sys.executable, str(Path(__file__).resolve()), *map(str, capture))
    return IndicatorPlan(command, 'External REC uses measured pre-show placement; '
                         'helper clock starts slightly after FFmpeg. GTK timer also available; '
                         'this window may be recorded if inside the capture.')


def overlaps(first, second):
    x, y, w, h = first
    cx, cy, cw, ch = second
    return x < cx + cw and x + w > cx and y < cy + ch and y + h > cy


def contains(monitor, rectangle):
    x, y, w, h = rectangle
    mx, my, mw, mh = monitor
    return w > 0 and h > 0 and mx <= x and my <= y and x + w <= mx + mw and y + h <= my + mh


def safe_position(capture, monitors, size):
    width, height = size
    if width <= 0 or height <= 0:
        return None
    for mx, my, mw, mh in monitors:
        for x, y in ((mx + mw - width - 20, my + 20), (mx + 20, my + 20),
                     (mx + mw - width - 20, my + mh - height - 20)):
            rectangle = (x, y, width, height)
            if contains((mx, my, mw, mh), rectangle) and not overlaps(rectangle, capture):
                return x, y
    return None


class PlacementGate:
    """Adapter operations are ordered: mask, measure, place, remeasure, reveal."""

    def __init__(self, window, capture, monitors):
        self.window = window
        self.capture = capture
        self.monitors = monitors
        self.topology = None
        self.failed = False

    def refresh(self):
        self.window.hide()
        if self.failed:
            return False
        try:
            topology = tuple(self.monitors())
            if not topology or (self.topology is not None and topology != self.topology):
                raise RuntimeError('Monitor topology changed or unavailable')
            self.topology = topology
            size = self.window.measure_hidden()
            position = safe_position(self.capture, topology, size)
            if position is None:
                raise RuntimeError('No safe REC position')
            actual = self.window.place_hidden(*position, *size)
            if (tuple(self.monitors()) != topology or actual != (*position, *size)
                    or overlaps(actual, self.capture)
                    or not any(contains(m, actual) for m in topology)):
                raise RuntimeError('Final REC geometry cannot be proven safe')
            self.window.reveal()
            return True
        except Exception as error:
            self.failed = True
            self.window.fail(str(error))
            return False


def guarded_window_class(Gtk, Gdk, GLib, cairo):
    """Child-only GTK adapter, factored for inert tests of the actual bootstrap."""
    original_window = Gtk.Window

    class GuardedWindow(original_window):
        def __init__(self, *args, **kwargs):
            self.gate = None
            self.refreshing = False
            self.pending = False
            self.failed = False
            self.adapter = None
            super().__init__(*args, **kwargs)

        def show_all(self):
            # The helper calls this before placement. Show children, NEVER the top.
            for child in self.get_children():
                child.show_all()

        def prepare_gate(self):
            if self.gate is None:
                self.adapter = NativePlacement(self)
                self.gate = PlacementGate(self.adapter, self.capture, self.monitor_rectangles)
                screen = self.get_screen()
                screen.connect('monitors-changed', self.topology_changed)
                screen.connect('size-changed', self.topology_changed)
                self.refreshing = True
                try:
                    self.adapter.map_masked()
                except Exception as error:
                    self.adapter.fail(str(error))
                    return False
                finally:
                    self.refreshing = False
                # Let GTK settle its mapped allocation while the shape is empty.
                self.pending = True
                GLib.idle_add(self.refresh_after_allocation)
                return False
            self.refreshing = True
            try:
                self.gate.refresh()
            finally:
                self.refreshing = False
            return False

        def monitor_rectangles(self):
            screen = self.get_screen()
            return tuple((g.x, g.y, g.width, g.height) for g in
                         (screen.get_monitor_geometry(i) for i in range(screen.get_n_monitors())))

        def topology_changed(self, *args):
            if self.adapter:
                self.adapter.hide()
                self.adapter.fail('Monitor topology changed')

        def do_size_allocate(self, allocation):
            # Mask BEFORE GTK can resize a visible native window, including text
            # and CSS changes. Never use an after-the-fact overlap detector.
            if self.adapter:
                self.adapter.hide()
            original_window.do_size_allocate(self, allocation)
            if self.gate and not self.refreshing and not self.pending and not self.failed:
                self.pending = True
                GLib.idle_add(self.refresh_after_allocation)

        def refresh_after_allocation(self):
            self.pending = False
            if not self.failed:
                self.prepare_gate()
            return False

    class NativePlacement:
        def __init__(self, window):
            self.window = window
            self.size = None

        def hide(self):
            native = self.window.get_window()
            if native is not None:
                native.shape_combine_region(cairo.Region(), 0, 0)
                self.window.get_display().sync()

        def map_masked(self):
            window = self.window
            window.realize()
            native = window.get_window()
            if (window.get_scale_factor() != 1
                    or native.get_window_type() != Gdk.WindowType.TEMP):
                raise RuntimeError('Only unscaled X11 override-redirect popups are safe')
            if not window.get_display().supports_shapes():
                raise RuntimeError('Native bounding shapes unavailable')
            self.hide()
            original_window.show_all(window)  # Mapped, but empty shape = no pixels.
            window.get_display().sync()

        def measure_hidden(self):
            window = self.window
            native = window.get_window()
            window.get_display().sync()
            _, _, width, height = native.get_geometry()
            minimum, natural = window.get_preferred_size()
            if width < natural.width or height < natural.height:
                raise RuntimeError('GTK allocation is not final')
            self.size = (width, height)
            return self.size

        def place_hidden(self, x, y, width, height):
            window = self.window
            # Update GTK's placement as well as native geometry, still masked.
            window.move(x, y)
            native = window.get_window()
            native.move_resize(x, y, width, height)
            window.get_display().sync()
            valid, rx, ry = native.get_origin()
            _, _, rw, rh = native.get_geometry()
            if not valid or window.get_size() != (rw, rh):
                raise RuntimeError('Native/GTK geometry mismatch')
            return rx, ry, rw, rh

        def reveal(self):
            # Fixed bounding shape prevents unverified growth from exposing pixels.
            region = cairo.Region(cairo.RectangleInt(0, 0, *self.size))
            self.window.get_window().shape_combine_region(region, 0, 0)
            self.window.get_display().sync()

        def fail(self, reason):
            self.hide()
            self.window.failed = True
            print('REC fallback: ' + reason, file=sys.stderr, flush=True)
            Gtk.main_quit()

    return GuardedWindow


def execute_helper(source, Gtk, Gdk, GLib, cairo):
    """Execute exact helper bytes; only child-process API interception is changed."""
    original_window, idle_add, timeout_add = Gtk.Window, GLib.idle_add, GLib.timeout_add
    guarded = guarded_window_class(Gtk, Gdk, GLib, cairo)
    windows = []

    def intercept_idle(callback, *args, **kwargs):
        if getattr(callback, '__name__', '') == 'position_indicator':
            window = callback.__self__
            windows.append(window)
            return idle_add(window.prepare_gate)
        return idle_add(callback, *args, **kwargs)

    def intercept_timer(interval, callback, *args, **kwargs):
        if getattr(callback, '__name__', '') == 'update_timer':
            window = callback.__self__
            def tick():
                if window.failed:
                    return False
                if window.adapter:
                    window.adapter.hide()
                callback()  # Text changes happen while no pixels are visible.
                if not window.pending:
                    window.pending = True
                    idle_add(window.refresh_after_allocation)
                return not window.failed
            return timeout_add(interval, tick)
        return timeout_add(interval, callback, *args, **kwargs)

    Gtk.Window, GLib.idle_add, GLib.timeout_add = guarded, intercept_idle, intercept_timer
    try:
        exec(compile(source, str(INDICATOR_SCRIPT), 'exec'),
             {'__name__': '__main__', '__file__': str(INDICATOR_SCRIPT)})
        return 2 if not windows or any(window.failed for window in windows) else 0
    finally:
        Gtk.Window, GLib.idle_add, GLib.timeout_add = original_window, idle_add, timeout_add


def main():
    try:
        if len(sys.argv) != 5:
            return 2
        tuple(map(int, sys.argv[1:]))
        source = INDICATOR_SCRIPT.read_bytes()
        if hashlib.sha256(source).hexdigest() != HELPER_SHA256:
            return 2
        import gi
        gi.require_version('Gtk', '3.0')
        gi.require_version('GdkX11', '3.0')
        from gi.repository import Gtk, Gdk, GdkX11, GLib
        import cairo
        if not isinstance(Gdk.Display.get_default(), GdkX11.X11Display):
            return 2
        return execute_helper(source, Gtk, Gdk, GLib, cairo)
    except Exception as error:
        print('REC fallback: ' + str(error), file=sys.stderr, flush=True)
        return 2


if __name__ == '__main__':
    sys.exit(main())
