#!/usr/bin/env python3

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk, Gdk, GLib


class Countdown(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.POPUP)

        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        self.set_skip_taskbar_hint(True)

        self.number = 3

        self.label = Gtk.Label(label="3")
        self.add(self.label)

        css = Gtk.CssProvider()
        css.load_from_data(b"""
            window {
                background: #202329;
                border-radius: 16px;
            }

            label {
                color: white;
                font-size: 72px;
                font-weight: bold;
                padding: 24px 48px;
            }
        """)

        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self.show_all()

        screen = Gdk.Screen.get_default()
        monitor = screen.get_primary_monitor()
        geometry = screen.get_monitor_geometry(monitor)

        width, height = self.get_size()

        self.move(
            geometry.x + (geometry.width - width) // 2,
            geometry.y + (geometry.height - height) // 2
        )

        GLib.timeout_add_seconds(1, self.tick)

    def tick(self):
        self.number -= 1

        if self.number == 0:
            Gtk.main_quit()
            return False

        self.label.set_text(str(self.number))
        return True


Countdown()
Gtk.main()
