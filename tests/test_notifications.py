import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from engine.notifications import DesktopNotifier


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.backend.init.return_value = True
        self.backend.get_server_caps.return_value = ['actions', 'body-markup']
        self.notice = self.backend.Notification.new.return_value
        self.gio = Mock()
        self.gio.File.new_for_path.return_value.get_uri.return_value = 'file:///recordings'
        self.notifier = DesktopNotifier(backend=(self.backend, self.gio))

    def test_markup_filename_and_gio_folder_action(self):
        self.assertTrue(self.notifier.notify_saved(Path('/recordings/a<&.mkv')))
        self.backend.Notification.new.assert_called_once_with(
            'Recording saved', 'a&lt;&amp;.mkv', 'media-record')
        action = self.notice.add_action.call_args.args
        self.assertEqual(action[:2], ('open-folder', 'Open folder'))
        action[2](self.notice, 'open-folder', action[3])
        self.gio.File.new_for_path.assert_called_once_with('/recordings')
        self.gio.AppInfo.launch_default_for_uri.assert_called_once_with('file:///recordings', None)
        self.notice.show.assert_called_once()

    def test_plain_backend_and_no_actions_on_close(self):
        self.backend.get_server_caps.return_value = []
        self.assertTrue(self.notifier.notify_saved(Path('a<&.mkv')))
        self.backend.Notification.new.assert_called_with('Recording saved', 'a<&.mkv', 'media-record')
        self.notice.add_action.assert_not_called()
        self.backend.get_server_caps.return_value = ['actions']
        self.assertTrue(self.notifier.notify_saved(Path('close.mkv'), allow_actions=False))
        self.notice.add_action.assert_not_called()

    def test_shutdown_closes_actionable_notifications_and_disarms_callbacks(self):
        self.notifier.notify_saved(Path('/recordings/a.mkv'))
        action = self.notice.add_action.call_args.args
        self.notifier.close()
        self.notice.close.assert_called_once()
        action[2](self.notice, 'open-folder', action[3])
        self.gio.AppInfo.launch_default_for_uri.assert_not_called()
        self.notifier.notify_saved(Path('close.mkv'), allow_actions=False)
        self.assertEqual(self.notice.show.call_count, 2)

    def test_missing_backend_and_backend_failures_are_optional(self):
        with patch('engine.notifications._load_backend', return_value=None):
            self.assertFalse(DesktopNotifier().notify_saved(Path('a.mkv')))
        for method in (self.backend.init, self.backend.get_server_caps,
                       self.backend.Notification.new, self.notice.show):
            with self.subTest(method=method):
                method.side_effect = RuntimeError('unavailable')
                notifier = DesktopNotifier(backend=(self.backend, self.gio))
                self.assertFalse(notifier.notify_saved(Path('a.mkv')))
                method.side_effect = None

    def test_action_and_close_failures_do_not_escape(self):
        self.notifier.notify_saved(Path('a.mkv'))
        action = self.notice.add_action.call_args.args
        self.gio.AppInfo.launch_default_for_uri.side_effect = RuntimeError('no file manager')
        action[2](self.notice, 'open-folder', action[3])
        self.notice.close.side_effect = RuntimeError('server gone')
        self.notifier.close()

    def test_action_registration_failure_still_shows_plain_notification(self):
        self.notice.add_action.side_effect = RuntimeError('actions unsupported')
        self.assertTrue(self.notifier.notify_saved(Path('a.mkv')))
        self.notice.show.assert_called_once()
