"""Optional libnotify adapter. All calls and action callbacks run on the GTK thread."""

from html import escape
from pathlib import Path


def _load_backend():
    try:
        import gi
        gi.require_version('Notify', '0.7')
        from gi.repository import Notify, Gio
        return Notify, Gio
    except Exception:
        # Neither the typelib nor a desktop notification server is required.
        return None


class DesktopNotifier:
    def __init__(self, backend=None):
        self.backend = backend if backend is not None else _load_backend()
        self._active = []
        self._accept_actions = True

    def _forget(self, notice):
        if notice in self._active:
            self._active.remove(notice)

    def _open_folder(self, notice, action, folder):
        if not self._accept_actions or self.backend is None:
            return
        try:
            _, gio = self.backend
            uri = gio.File.new_for_path(str(folder)).get_uri()
            gio.AppInfo.launch_default_for_uri(uri, None)
        except Exception:
            pass  # No file manager or URI handler must not disrupt the recorder.

    def notify_saved(self, output, *, allow_actions=True):
        if self.backend is None:
            return False
        notice = None
        try:
            notify, _ = self.backend
            if not notify.init('Screen Recorder'):
                return False
            caps = notify.get_server_caps() or []
            output = Path(output)
            filename = escape(output.name, quote=False) if 'body-markup' in caps else output.name
            notice = notify.Notification.new('Recording saved', filename, 'media-record')
            if allow_actions and self._accept_actions and 'actions' in caps:
                try:
                    notice.add_action('open-folder', 'Open folder', self._open_folder,
                                      output.absolute().parent)
                    notice.connect('closed', self._forget)
                    self._active.append(notice)  # Keep callbacks alive while GTK runs.
                except Exception:
                    notice.clear_actions()
            shown = bool(notice.show())
            if not shown:
                self._forget(notice)
            return shown
        except Exception:
            if notice is not None:
                self._forget(notice)
            return False

    def close(self):
        """Revoke live actions before GTK quits; close-time notices are text-only.

        libnotify actions require this process's main loop. Previously actionable
        notifications are closed, not left with a dead Open folder button. Even
        if the server is gone, late callbacks are disarmed locally.
        """
        self._accept_actions = False
        active, self._active = self._active, []
        for notice in active:
            try:
                notice.close()
            except Exception:
                pass
