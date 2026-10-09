#!/usr/bin/env python3

import re
import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from recorder import RecordingOptions
from engine.recording import RecordingEngine


MONITOR_NAMES = {
    "eDP": "Acer",
    "DVI-I-3-2": "LG derecha",
    "DVI-I-2-1": "Samsung arriba",
}

BORDER_SCRIPT = (
    Path.home() / ".local/bin/recording-border.py"
)


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
            r"\+(\d+)\+(\d+)",
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
        self.recording = False
        self.selecting = False
        self.border_process = None

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
            monitors = get_connected_monitors()

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

        self.source_container.set_sensitive(
            not self.recording and not self.selecting
        )

        self.source_container.show_all()
        self.monitors = monitors

    def check_monitor_changes(self):
        if not self.recording and not self.selecting:
            monitors = get_connected_monitors()

            if monitors != self.monitors:
                self.refresh_monitors(monitors)

        return True

    def check_recording_status(self):
        if self.recording and not self.engine.is_recording():
            self.recording = False
            self.stop_border()

            self.status.set_text(
                "Recording process ended unexpectedly"
            )
            self.update_button()

        return True

    def set_controls_enabled(self, enabled):
        self.source_container.set_sensitive(enabled)

        for group in (
            self.audio,
            self.fps,
            self.quality,
        ):
            for button in group.values():
                button.set_sensitive(enabled)

    def update_button(self):
        style = self.start_button.get_style_context()

        if self.recording:
            self.start_button.set_label("Stop Recording")
            style.remove_class("suggested-action")
            style.add_class("destructive-action")
        else:
            self.start_button.set_label("Start Recording")
            style.remove_class("destructive-action")
            style.add_class("suggested-action")

        self.start_button.set_sensitive(not self.selecting)
        self.set_controls_enabled(
            not self.recording and not self.selecting
        )

    def on_record_clicked(self, button):
        if self.recording:
            self.stop_recording()
        elif not self.selecting:
            self.start_recording()

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
            options = self.get_options()

            if options.source == "region":
                self.begin_region_selection(options)
            else:
                self.launch_recording(
                    options,
                    monitor=options.source,
                )

        except Exception as error:
            self.show_message(
                "Recording error",
                str(error),
                Gtk.MessageType.ERROR,
            )

    def begin_region_selection(self, options):
        self.selecting = True
        self.status.set_text("Select a screen region...")
        self.update_button()

        self.hide()

        GLib.timeout_add(
            300,
            self.run_region_selection,
            options,
        )

    def run_region_selection(self, options):
        def worker():
            try:
                region = self.engine.select_region()
                error = None
            except Exception as exc:
                region = None
                error = str(exc)

            GLib.idle_add(
                self.finish_region_selection,
                options,
                region,
                error,
            )

        threading.Thread(
            target=worker,
            daemon=True,
        ).start()

        return False

    def finish_region_selection(
        self, options, region, error
    ):
        self.selecting = False
        self.show_all()

        if error:
            self.status.set_text("Region selection failed")
            self.show_message(
                "Region error",
                error,
                Gtk.MessageType.ERROR,
            )
        elif region is None:
            self.status.set_text("Region selection cancelled")
        else:
            self.launch_recording(
                options,
                region=region,
            )

        self.update_button()
        return False

    def start_border(self, region):
        if not BORDER_SCRIPT.is_file():
            print("Recording border script not found")
            return

        self.stop_border()

        self.border_process = subprocess.Popen(
            [
                sys.executable,
                str(BORDER_SCRIPT),
                *[str(value) for value in region],
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop_border(self):
        if self.border_process is None:
            return

        if self.border_process.poll() is None:
            self.border_process.terminate()

        self.border_process = None

    def launch_recording(
        self, options, monitor=None, region=None
    ):
        try:
            output = self.engine.start(
                monitor=monitor,
                region=region,
                fps=options.fps,
                quality=options.quality,
                audio=options.audio,
            )

            self.recording = True

            if region is not None:
                try:
                    self.start_border(region)
                except OSError as error:
                    print(f"Could not show border: {error}")

            self.status.set_text(
                f"Recording... Audio: {options.audio}"
            )
            self.update_button()

            print(f"Recording started: {output}")

        except Exception as error:
            self.stop_border()
            self.recording = self.engine.is_recording()
            self.update_button()

            self.show_message(
                "Recording error",
                str(error),
                Gtk.MessageType.ERROR,
            )

    def stop_recording(self):
        self.start_button.set_sensitive(False)
        self.status.set_text("Saving recording...")

        try:
            output = self.engine.stop()

            self.status.set_text(
                f"Saved: {output.name}"
                if output else "Recording stopped"
            )

        except Exception as error:
            self.show_message(
                "Stop error",
                str(error),
                Gtk.MessageType.ERROR,
            )

        finally:
            self.stop_border()
            self.recording = self.engine.is_recording()
            self.start_button.set_sensitive(True)
            self.update_button()

    def on_close(self, widget, event):
        if self.engine.is_recording():
            try:
                self.engine.stop()
            except Exception as error:
                print(f"Stop error: {error}")

        self.stop_border()
        Gtk.main_quit()

        return False

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
