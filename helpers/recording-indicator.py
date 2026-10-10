#!/usr/bin/env python3

import sys
import time
import signal
import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk, Gdk, GLib


class RecordingIndicator(Gtk.Window):
    def __init__(self, capture=None):
        super().__init__(type=Gtk.WindowType.POPUP)

        self.start_time = time.monotonic()
        self.capture = capture

        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)

        self.set_border_width(10)

        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8
        )

        self.add(box)

        dot = Gtk.Label(label="●")
        dot.set_name("recording-dot")
        box.pack_start(dot, False, False, 0)

        rec = Gtk.Label(label="REC")
        box.pack_start(rec, False, False, 0)

        self.timer = Gtk.Label(label="00:00:00")
        box.pack_start(self.timer, False, False, 0)

        css = Gtk.CssProvider()
        css.load_from_data(b"""
            window {
                background: #202329;
                border-radius: 8px;
            }

            label {
                color: white;
                font-weight: bold;
                font-size: 13px;
            }

            #recording-dot {
                color: #ff4040;
                font-size: 17px;
            }
        """)

        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.show_all()

        GLib.idle_add(self.position_indicator)
        GLib.timeout_add(250, self.update_timer)

    def position_indicator(self):
        screen = Gdk.Screen.get_default()
        width, height = self.get_size()

        margin = 20
        candidates = []

        # Buscar una posición en los monitores disponibles.
        for i in range(screen.get_n_monitors()):
            g = screen.get_monitor_geometry(i)

            candidates.extend([
                (g.x + g.width - width - margin, g.y + margin),
                (g.x + margin, g.y + margin),
                (g.x + g.width - width - margin,
                 g.y + g.height - height - margin),
            ])

        # Elegir una ubicación sin superposición.
        for x, y in candidates:
            if not self.overlaps_capture(x, y, width, height):
                self.move(x, y)
                return False

        # Si no hay espacio fuera, usar monitor principal.
        primary = screen.get_primary_monitor()
        g = screen.get_monitor_geometry(primary)

        self.move(
            g.x + g.width - width - margin,
            g.y + margin
        )

        return False

    def overlaps_capture(self, x, y, width, height):
        if self.capture is None:
            return False

        cx, cy, cw, ch = self.capture

        return (
            x < cx + cw
            and x + width > cx
            and y < cy + ch
            and y + height > cy
        )

    def update_timer(self):
        elapsed = int(time.monotonic() - self.start_time)

        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)

        self.timer.set_text(
            f"{hours:02}:{minutes:02}:{seconds:02}"
        )

        return True


def stop(*args):
    Gtk.main_quit()


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

# Coordenadas opcionales de la región grabada.
capture = None

if len(sys.argv) == 5:
    capture = tuple(map(int, sys.argv[1:5]))

RecordingIndicator(capture)
Gtk.main()
