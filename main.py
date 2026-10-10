#!/usr/bin/env python3

from dataclasses import replace
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, Pango

from recorder import RecordingOptions, prepare_output_directory
from preferences import (load_preferences, save_preferences,
                         monitor_source_token, source_monitor_id)
from engine.recording import RecordingEngine, monitor_identity
from engine.lifecycle import RecordingLifecycle
from engine.notifications import DesktopNotifier


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

    for index, line in enumerate(result.stdout.splitlines()[1:], start=1):
        parts = line.split()

        if len(parts) < 3:
            continue

        match = re.fullmatch(
            r"(\d+)(?:/\d+)?x(\d+)(?:/\d+)?"
            r"([+-]\d+)([+-]\d+)",
            parts[2],
        )

        if not match:
            continue

        width, height, x, y = map(int, match.groups())
        name = monitor_identity(parts)

        monitors.append({
            "id": name,
            "label": f"Display {index} ({name})",
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
        self.preferences = load_preferences()

        self.set_default_size(420, 460)
        self.set_border_width(18)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.connect("delete-event", self.on_close)
        self.set_titlebar(self.create_header_bar())

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
        self.rename_monitor_button = Gtk.Button(label='Rename display')
        self.rename_monitor_button.set_halign(Gtk.Align.START)
        self.rename_monitor_button.set_tooltip_text('Rename the selected display; blank resets its name')
        self.rename_monitor_button.connect('clicked', self.on_rename_monitor_clicked)
        source_section.pack_start(self.rename_monitor_button, False, False, 0)
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
            default=self.preferences.audio,
            columns=2,
            preference_key='audio',
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
            default=str(self.preferences.fps),
            columns=1,
            preference_key='fps',
        )

        self.quality = self.create_radio_group(
            quality_box,
            [
                ("normal", "Normal"),
                ("high", "High"),
            ],
            default=self.preferences.quality,
            columns=1,
            preference_key='quality',
        )

        output_section = self.create_section(main, "Save to")
        output_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        output_section.pack_start(output_row, False, False, 0)
        self.output_label = self.create_label('')
        self.output_label.set_selectable(True)
        self.output_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.output_label.set_max_width_chars(32)
        output_row.pack_start(self.output_label, True, True, 0)
        self.update_output_label()
        self.change_output_button = Gtk.Button(label=' Change')
        self.change_output_button.set_image(
            Gtk.Image.new_from_icon_name('folder-open-symbolic', Gtk.IconSize.BUTTON)
        )
        self.change_output_button.set_always_show_image(True)
        self.change_output_button.set_tooltip_text('Choose where recordings are saved')
        self.change_output_button.add_events(
            Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
        )
        self.change_output_button.connect('enter-notify-event', self.on_button_enter)
        self.change_output_button.connect('leave-notify-event', self.on_button_leave)
        self.change_output_button.connect('clicked', self.on_change_output_clicked)
        output_row.pack_start(self.change_output_button, False, False, 0)

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

    def create_header_bar(self):
        header = Gtk.HeaderBar()
        header.set_title('Screen Recorder')
        header.set_show_close_button(True)
        header.set_decoration_layout(':minimize,close')
        icon_path = Path(__file__).resolve().parent / 'assets/screen-recorder-icon.png'
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                str(icon_path), 28, 28, True,
            )
        except (GLib.Error, OSError):
            # Branding is optional; native window controls remain available.
            pass
        else:
            header.pack_start(Gtk.Image.new_from_pixbuf(pixbuf))
        return header

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
        self, container, options, default, columns=2, preference_key=None
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

        # GTK activates the first radio implicitly. Connect only after the
        # whole group and its restored selection exist, including on rebuilds.
        if preference_key is not None:
            for value, button in buttons.items():
                button.connect('toggled', self.on_preference_toggled,
                               preference_key, value)
                if preference_key == 'source':
                    button.connect('clicked', self.on_source_clicked, value)

        return buttons

    def on_preference_toggled(self, button, key, value):
        if not button.get_active():
            return
        if key == 'fps':
            value = int(value)
        self.preferences = replace(self.preferences, **{key: value})
        save_preferences(self.preferences)
        if key == 'source':
            self.update_rename_monitor_button()

    def selected_connected_monitor(self):
        selected = source_monitor_id(self.get_selected(self.source))
        return next((monitor for monitor in self.monitors
                     if monitor['id'] == selected), None)

    def update_rename_monitor_button(self):
        self.rename_monitor_button.set_sensitive(
            not self.lifecycle.closed and self.lifecycle.state == 'idle'
            and self.selected_connected_monitor() is not None
        )

    def on_rename_monitor_clicked(self, button):
        if self.lifecycle.closed or self.lifecycle.state != 'idle':
            return
        monitor = self.selected_connected_monitor()
        if monitor is None:
            return
        monitor_id, token = monitor['id'], self.lifecycle.token
        dialog = None
        try:
            dialog = Gtk.Dialog(title='Rename display', transient_for=self, modal=True)
            dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL,
                               'Save', Gtk.ResponseType.ACCEPT)
            dialog.set_default_response(Gtk.ResponseType.ACCEPT)
            content = dialog.get_content_area()
            content.set_border_width(12)
            content.set_spacing(8)
            content.pack_start(self.create_label(monitor['label']), False, False, 0)
            entry = Gtk.Entry()
            entry.set_text(self.preferences.monitor_names.get(monitor_id, ''))
            entry.set_placeholder_text('Blank restores the default display name')
            entry.set_activates_default(True)
            content.pack_start(entry, False, False, 0)
            dialog.show_all()
            response = dialog.run()
            # Nested modal events can start/finish a session, close the window,
            # change the selection or remove the captured real identifier.
            current = self.selected_connected_monitor()
            if (response != Gtk.ResponseType.ACCEPT or self.lifecycle.closed
                    or self.lifecycle.state != 'idle' or self.lifecycle.token != token
                    or current is None or current['id'] != monitor_id):
                return
            name = entry.get_text().strip()
            if '\x00' in name:
                raise ValueError('Display names cannot contain NUL characters')
            names = dict(self.preferences.monitor_names)
            if name:
                names[monitor_id] = name
            else:
                names.pop(monitor_id, None)
            candidate = replace(self.preferences, monitor_names=names)
            if not save_preferences(candidate):
                self.status.set_text('Display name unchanged: could not save settings. '
                                     'Check configuration folder permissions and free space, then retry.')
                return
            self.preferences = candidate
            self.refresh_monitors()
            self.status.set_text('Display name updated. Ready to record.')
        except (OSError, ValueError, RuntimeError, GLib.Error) as error:
            self.status.set_text(f'Display name unchanged: {error}. Try renaming again.')
        finally:
            if dialog is not None:
                try:
                    dialog.destroy()
                except (OSError, RuntimeError, GLib.Error) as error:
                    self.status.set_text(f'Could not close rename dialog: {error}. '
                                         'Try closing the dialog or restarting the application.')

    def update_output_label(self):
        self.output_label.set_text(self.preferences.output_dir)
        self.output_label.set_tooltip_text(self.preferences.output_dir)

    def on_change_output_clicked(self, button):
        if self.lifecycle.closed or self.lifecycle.state != 'idle':
            return
        dialog = None
        try:
            dialog = Gtk.FileChooserDialog(
                title='Choose recording output folder', transient_for=self, modal=True,
                action=Gtk.FileChooserAction.SELECT_FOLDER,
            )
            dialog.add_buttons('Cancel', Gtk.ResponseType.CANCEL,
                               'Select', Gtk.ResponseType.ACCEPT)
            dialog.set_local_only(True)
            dialog.set_current_folder(self.preferences.output_dir)
            response = dialog.run()
            # run() enters a nested GTK loop: a session/close may have begun.
            if (response != Gtk.ResponseType.ACCEPT or self.lifecycle.closed
                    or self.lifecycle.state != 'idle'):
                return
            directory = prepare_output_directory(dialog.get_filename())
            candidate = replace(self.preferences, output_dir=str(directory))
            if not save_preferences(candidate):
                self.status.set_text('Output folder unchanged: could not save settings. '
                                     'Check configuration folder permissions and free space, then retry.')
                return
            self.preferences = candidate
            self.update_output_label()
            self.status.set_text('Output folder updated. Ready to record.')
        except (OSError, ValueError, RuntimeError, GLib.Error) as error:
            self.status.set_text(f'Output folder unchanged: {error}. '
                                 'Choose a writable local folder and check permissions/free space.')
        finally:
            if dialog is not None:
                try:
                    dialog.destroy()
                except (OSError, RuntimeError, GLib.Error) as error:
                    self.status.set_text(f'Could not close output folder chooser: {error}. '
                                         'Try closing the chooser or restarting the application.')

    def on_source_clicked(self, button, value):
        # Clicking an already-active region fallback emits no toggled signal.
        # A normal selection was already saved by toggled; do not save twice.
        if button.get_active() and self.preferences.source != value:
            self.on_preference_toggled(button, 'source', value)

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

        # The visible fallback is not the user's preference: retain an absent
        # connector through startup detection, unplugging and other changes.
        preferences = getattr(self, 'preferences', None)
        selected = (preferences.source if preferences is not None
                    else self.get_selected(self.source) or 'region')

        # Retiring a radio group can activate another old member. Disconnect
        # its selection handlers before removal so teardown cannot save.
        if preferences is not None:
            for button in self.source.values():
                button.disconnect_by_func(self.on_preference_toggled)
                button.disconnect_by_func(self.on_source_clicked)

        for child in self.source_container.get_children():
            self.source_container.remove(child)

        options = [("region", "Select region")]

        for monitor in monitors:
            options.append((
                monitor_source_token(monitor['id']),
                (preferences.monitor_names.get(monitor['id'], monitor['label'])
                 if preferences is not None else monitor['label']),
            ))

        available = {value for value, _ in options}

        if selected not in available:
            selected = "region"

        self.source = self.create_radio_group(
            self.source_container,
            options,
            default=selected,
            columns=2,
            preference_key='source' if preferences is not None else None,
        )

        self.source_container.set_sensitive(self.lifecycle.state == 'idle')

        self.source_container.show_all()
        self.monitors = monitors
        self.update_rename_monitor_button()

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
        self.update_rename_monitor_button()
        self.change_output_button.set_sensitive(enabled and not self.lifecycle.closed)
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
            output_dir=self.preferences.output_dir,
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
            self.rename_monitor_button.set_sensitive(False)
            self.change_output_button.set_sensitive(False)
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
        self.rename_monitor_button.set_sensitive(False)
        self.change_output_button.set_sensitive(False)
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
