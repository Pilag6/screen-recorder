#!/usr/bin/env python3

import re
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from recorder import RecordingOptions
from engine.recording import RecordingEngine
from engine.lifecycle import RecordingLifecycle


MONITOR_NAMES = {
    "eDP": "Acer",
    "DVI-I-3-2": "LG derecha",
    "DVI-I-2-1": "Samsung arriba",
}

def get_connected_monitors():
    try:
        result = subprocess.run(
            ["xrandr", "--listmonitors"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError) as error:
        print(f"Monitor detection failed: {error}")
        return []

    monitors = []

    for line in result.stdout.splitlines()[1:]:
        parts = line.split()

        if len(parts) < 4:
            continue

        match = re.fullmatch(
            r"(\d+)(?:/\d+)?x(\d+)(?:/\d+)?"
            r"([+-]\d+)([+-]\d+)",
            parts[2],
        )

        if not match:
            continue

        width, height, x, y = map(int, match.groups())
        name = parts[-1]

        monitors.append({
            "id": name,
            "label": MONITOR_NAMES.get(name, name),
            "x": x,
            "y": y,
            "width": width,
            "height": height,
        })

    return monitors


class ScreenRecorder(Gtk.Window):
    def __init__(self):
        super().__init__(title="Screen Recorder")

        self.engine = RecordingEngine()
        self.lifecycle = RecordingLifecycle(
            self.engine, GLib.idle_add, self.on_lifecycle_state,
        )
        self._monitor_pending = False
        self._monitor_generation = 0
        self.recording_status = ''

        self.set_default_size(440, 420)
        self.set_border_width(24)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("delete-event", self.on_close)

        main = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
        )
        self.add(main)

        # Screen source
        main.pack_start(
            self.create_label("SCREEN SOURCE"),
            False, False, 0,
        )

        self.source_container = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
        )
        main.pack_start(
            self.source_container,
            False, False, 0,
        )

        self.source = {}
        self.monitors = []
        self.refresh_monitors()

        # Audio source
        main.pack_start(
            self.create_label("AUDIO SOURCE"),
            False, False, 0,
        )

        self.audio = self.create_radio_group(
            main,
            [
                ("none", "No audio"),
                ("system", "System audio"),
                ("mic", "Microphone"),
                ("both", "System + microphone"),
            ],
            default="both",
            columns=2,
        )

        # Video settings
        main.pack_start(
            self.create_label("VIDEO SETTINGS"),
            False, False, 0,
        )

        settings = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=40,
        )
        main.pack_start(settings, False, False, 0)

        fps_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=5,
        )

        quality_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=5,
        )

        settings.pack_start(fps_box, True, True, 0)
        settings.pack_start(quality_box, True, True, 0)

        fps_box.pack_start(
            self.create_label("Frame rate"),
            False, False, 0,
        )

        quality_box.pack_start(
            self.create_label("Quality"),
            False, False, 0,
        )

        self.fps = self.create_radio_group(
            fps_box,
            [
                ("30", "30 FPS"),
                ("60", "60 FPS"),
            ],
            default="30",
            columns=1,
        )

        self.quality = self.create_radio_group(
            quality_box,
            [
                ("normal", "Normal"),
                ("high", "High"),
            ],
            default="high",
            columns=1,
        )

        # Output folder
        main.pack_start(
            self.create_label("OUTPUT FOLDER"),
            False, False, 0,
        )

        folder = Gtk.Label(
            label="~/Videos/Recordings"
        )
        folder.set_xalign(0)
        main.pack_start(folder, False, False, 0)

        # Status
        self.status = Gtk.Label(label="Ready to record")
        self.status.set_xalign(0)
        self.status.set_line_wrap(True)
        main.pack_start(self.status, False, False, 0)

        # Recording button
        self.start_button = Gtk.Button(
            label="Start Recording"
        )
        self.start_button.connect(
            "clicked",
            self.on_record_clicked,
        )

        self.start_button.add_events(
            Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
        )

        self.start_button.connect(
            "enter-notify-event",
            self.on_button_enter,
        )
        self.start_button.connect(
            "leave-notify-event",
            self.on_button_leave,
        )

        main.pack_end(
            self.start_button,
            False, False, 0,
        )

        self.update_button()

        GLib.idle_add(self.check_monitor_changes)
        GLib.timeout_add_seconds(
            3,
            self.check_monitor_changes,
        )

        GLib.timeout_add_seconds(
            1,
            self.check_recording_status,
        )

    def create_label(self, text):
        label = Gtk.Label(label=text)
        label.set_xalign(0)
        return label

    def create_radio_group(
        self, container, options, default, columns=2
    ):
        buttons = {}
        first = None

        grid = Gtk.Grid()
        grid.set_column_spacing(24)
        grid.set_row_spacing(8)
        grid.set_column_homogeneous(True)

        container.pack_start(grid, False, False, 0)

        for index, (value, text) in enumerate(options):
            if first is None:
                button = Gtk.RadioButton.new_with_label(
                    None, text
                )
                first = button
            else:
                button = Gtk.RadioButton.new_with_label_from_widget(
                    first, text
                )

            buttons[value] = button

            row = index // columns
            column = index % columns

            grid.attach(button, column, row, 1, 1)

            if value == default:
                button.set_active(True)

        return buttons

    def on_button_enter(self, widget, event):
        window = widget.get_window()

        if window and widget.get_sensitive():
            cursor = Gdk.Cursor.new_from_name(
                window.get_display(),
                "pointer",
            )
            window.set_cursor(cursor)

        return False

    def on_button_leave(self, widget, event):
        window = widget.get_window()

        if window:
            window.set_cursor(None)

        return False

    def get_selected(self, buttons):
        for value, button in buttons.items():
            if button.get_active():
                return value

        return None

    def refresh_monitors(self, monitors=None):
        if monitors is None:
            monitors = self.monitors

        selected = self.get_selected(self.source) or "region"

        for child in self.source_container.get_children():
            self.source_container.remove(child)

        options = [("region", "Select region")]

        for monitor in monitors:
            options.append((
                monitor["id"],
                monitor["label"],
            ))

        available = {value for value, _ in options}

        if selected not in available:
            selected = "region"

        self.source = self.create_radio_group(
            self.source_container,
            options,
            default=selected,
            columns=2,
        )

        self.source_container.set_sensitive(self.lifecycle.state == 'idle')

        self.source_container.show_all()
        self.monitors = monitors

    def check_monitor_changes(self):
        if self.lifecycle.closed:
            return False
        if self.lifecycle.state != 'idle' or self._monitor_pending:
            return True
        self._monitor_pending = True
        self._monitor_generation += 1
        generation = self._monitor_generation
        token = self.lifecycle.token

        def worker():
            monitors = get_connected_monitors()
            GLib.idle_add(self.finish_monitor_refresh, generation, monitors, token)

        # subprocess.run has a 5s timeout and reaps xrandr. A non-daemon
        # refresh worker cannot be abandoned during interpreter shutdown.
        threading.Thread(target=worker).start()
        return True

    def finish_monitor_refresh(self, generation, monitors, token=None):
        if generation != self._monitor_generation:
            return False
        self._monitor_pending = False
        if (not self.lifecycle.closed and self.lifecycle.state == 'idle'
                and (token is None or self.lifecycle.token == token)
                and monitors != self.monitors):
            self.refresh_monitors(monitors)
        return False

    def check_recording_status(self):
        if self.lifecycle.closed:
            return False
        if self.lifecycle.state == 'recording' and self.lifecycle.started_at is not None:
            elapsed = max(0, int(time.monotonic() - self.lifecycle.started_at))
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            self.status.set_text(
                f'REC {hours:02}:{minutes:02}:{seconds:02} — {self.recording_status}'
            )
        return True

    def set_controls_enabled(self, enabled):
        self.source_container.set_sensitive(enabled)
        for group in (self.audio, self.fps, self.quality):
            for button in group.values():
                button.set_sensitive(enabled)

    def update_button(self):
        state = self.lifecycle.state
        style = self.start_button.get_style_context()
        active = state != 'idle'
        labels = {
            'idle': 'Start Recording',
            'recording': 'Stop Recording',
            'stopping': 'Please wait...',
            'closed': 'Closing...',
            'cleanup_failed': 'Retry cleanup',
        }
        self.start_button.set_label(labels.get(state, 'Cancel Recording'))
        style.remove_class('suggested-action' if active else 'destructive-action')
        style.add_class('destructive-action' if active else 'suggested-action')
        self.start_button.set_sensitive(state not in ('stopping', 'closed'))
        self.set_controls_enabled(not active)

    def on_record_clicked(self, button):
        if self.lifecycle.state == 'idle':
            self.start_recording()
        else:
            self.lifecycle.cancel()

    def get_options(self):
        options = RecordingOptions(
            source=self.get_selected(self.source),
            audio=self.get_selected(self.audio),
            fps=int(self.get_selected(self.fps)),
            quality=self.get_selected(self.quality),
        )
        options.validate()
        return options

    def start_recording(self):
        try:
            self.lifecycle.begin(self.get_options())
        except Exception as error:
            self.status.set_text(f'Recording error: {error}')

    def on_lifecycle_state(self, state, message, output=None):
        if state == 'closed':
            if 'error' in message.lower():
                print(message)
            Gtk.main_quit()
            return
        if self.lifecycle.closed and state not in ('cleanup_failed', 'stopping'):
            return
        if state == 'selecting' or (self.lifecycle.closed and state == 'stopping'):
            self.hide()
        else:
            self.show_all()
        self.status.set_text(message)
        self.recording_status = message
        if state == 'recording':
            self.status.set_tooltip_text(self.lifecycle.indicator_reason)
            print(self.lifecycle.indicator_reason)
            print(f'Recording started: {output}')
            self.check_recording_status()
        else:
            self.status.set_tooltip_text(None)
        self.update_button()

    def stop_recording(self):
        self.lifecycle.cancel()

    def on_close(self, widget, event):
        # Keep the GTK loop alive while the session worker cleans up. No waits here.
        self.hide()
        self.lifecycle.close()
        return True

    def show_message(self, title, message, message_type):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=message_type,
            buttons=Gtk.ButtonsType.OK,
            text=title,
        )

        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()


if __name__ == "__main__":
    window = ScreenRecorder()
    window.show_all()
    Gtk.main()
