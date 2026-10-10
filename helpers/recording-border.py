#!/usr/bin/env python3

import sys
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

x, y, width, height = map(int, sys.argv[1:5])

BORDER = 4

class RecordingBorder(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.POPUP)

        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()

        if visual:
            self.set_visual(visual)

        self.set_default_size(width + BORDER * 2, height + BORDER * 2)
        self.move(x - BORDER, y - BORDER)

        self.connect("draw", self.draw_border)

        self.show_all()

        # Permitir clics a través del indicador.
        window = self.get_window()
        if window:
            window.input_shape_combine_region(
                cairo_region_empty(), 0, 0
            )

    def draw_border(self, widget, cr):
        cr.set_source_rgba(1, 0.15, 0.15, 1)
        cr.set_line_width(BORDER)

        cr.rectangle(
            BORDER / 2,
            BORDER / 2,
            width + BORDER,
            height + BORDER,
        )

        cr.stroke()
        return False


def cairo_region_empty():
    import cairo
    return cairo.Region()


RecordingBorder()
Gtk.main()
