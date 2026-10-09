#!/usr/bin/env python3

import re
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from recorder import RecordingOptions
from engine.recording import RecordingEngine
from engine.lifecycle import RecordingLifecycle
from engine.notifications import DesktopNotifier


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
        self.notifier = DesktopNotifier()
        self._iconified_token = None
        self._notified_token = None
        self.lifecycle = RecordingLifecycle(
            self.engine, GLib.idle_add, self.on_lifecycle_state,
        )
        self._monitor_pending = False
        self._monitor_generation = 0
        self.recording_status = ''

        self.set_default_size(420, 460)
        self.set_border_width(18)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("delete-event", self.on_close)

        main = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
        )
        self.add(main)

        # Keep section headings outside the controls disabled during a session.
        source_section = self.create_section(main, "Screen source")
        self.source_container = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
        )
        source_section.pack_start(self.source_container, False, False, 0)

        self.source = {}
        self.monitors = []
        self.refresh_monitors()

        audio_section = self.create_section(main, "Audio source")
        self.audio = self.create_radio_group(
            audio_section,
            [
                ("none", "No audio"),
                ("system", "System audio"),
                ("mic", "Microphone"),
                ("both", "System + microphone"),
            ],
            default="both",
            columns=2,
        )

        settings = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=16,
            homogeneous=True,
        )
        main.pack_start(settings, False, False, 0)
        fps_box = self.create_section(settings, "Frame rate", expand=True)
        quality_box = self.create_section(settings, "Quality", expand=True)

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

        output_section = self.create_section(main, "Save to")
        folder = self.create_label("~/Videos/Recordings")
        folder.set_selectable(True)
        output_section.pack_start(folder, False, False, 0)

        # A separate footer keeps feedback next to the session action.
        footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main.pack_end(footer, False, False, 0)
        footer.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL),
            False, False, 0,
        )
        status_section = self.create_section(footer, "Status")
        self.status = self.create_label("Ready to record")
        self.status.set_line_wrap(True)
        self.status.set_max_width_chars(44)
        self.status.set_selectable(True)
        self.status.get_accessible().set_name("Recording status")
        status_section.pack_start(self.status, False, False, 0)

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

        footer.pack_start(self.start_button, False, False, 0)

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

    def create_section(self, container, title, expand=False):
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        section.get_accessible().set_name(title)
        heading = self.create_label(title)
        # Weight only: font size, colors and focus rendering belong to the theme.
        heading.set_markup(f'<b>{GLib.markup_escape_text(title)}</b>')
        section.pack_start(heading, False, False, 0)
        container.pack_start(section, expand, expand, 0)
        return section

    def create_radio_group(
        self, container, options, default, columns=2
    ):
        buttons = {}
        first = None

        grid = Gtk.Grid()
        grid.set_column_spacing(16)
        grid.set_row_spacing(6)
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
            recording_time = f'REC {hours:02}:{minutes:02}:{seconds:02}'
            self.set_title(f'{recording_time} — Screen Recorder')
            self.status.set_text(f'{recording_time} — {self.recording_status}')
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

    def notify_completion(self):
        completion = self.lifecycle.completion
        if completion is None or completion.token == self._notified_token:
            return
        # Consume once, even if the file disappeared or the desktop is unavailable.
        self._notified_token = completion.token
        try:
            exists = completion.output.is_file()
        except OSError:
            exists = False
        if exists:
            self.notifier.notify_saved(completion.output, allow_actions=not self.lifecycle.closed)

    def on_lifecycle_state(self, state, message, output=None):
        if state != self.lifecycle.state:
            return
        if state != 'recording':
            self.set_title('Screen Recorder')
        if state == 'closed':
            self.notifier.close()
            self.notify_completion()
            if 'error' in message.lower():
                print(message)
            self.get_application().quit()
            return
        if self.lifecycle.closed and state not in ('cleanup_failed', 'stopping'):
            return
        if state == 'selecting' or (self.lifecycle.closed and state == 'stopping'):
            self.hide()
        elif state != 'recording':
            self.show_all()
        if state == 'idle':
            self.notify_completion()
        self.status.set_text(message)
        self.recording_status = message
        if state == 'recording':
            if self._iconified_token != self.lifecycle.token:
                self._iconified_token = self.lifecycle.token
                self.iconify()
            self.status.set_tooltip_text(
                f'{self.lifecycle.indicator_reason}\n'
                'If the REC helper is unavailable, recording time remains in the '
                'window title (visible in window lists with titles enabled). '
                'Restore this window to Stop Recording.'
            )
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
        self.notifier.close()
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


class ScreenRecorderApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="io.github.screenrecorder.ScreenRecorder")
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = ScreenRecorder()
            self.add_window(self.window)
        # Keep the registered window alive until asynchronous cleanup completes.
        if self.window.lifecycle.closed and self.window.lifecycle.state != 'cleanup_failed':
            return
        self.window.show_all()
        self.window.deiconify()
        self.window.present()


if __name__ == "__main__":
    sys.exit(ScreenRecorderApplication().run(sys.argv))
