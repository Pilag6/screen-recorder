"""GTK-independent session ownership; blocking work runs on one session worker."""

import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from engine.indicator_launcher import FALLBACK, indicator_plan
from preferences import source_monitor_id


COUNTDOWN_SCRIPT = Path(__file__).resolve().parents[1] / 'helpers' / 'recording-countdown.py'
BORDER_SCRIPT = Path(__file__).resolve().parents[1] / 'helpers' / 'recording-border.py'


class Cancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled()


class OwnedProcesses:
    """Used only on the worker, including acquisition and bounded reaping."""

    def __init__(self):
        self.children = {}
        self.escalated = set()

    def add(self, name, process):
        if name in self.children:
            raise RuntimeError(f'Child already owned: {name}')
        self.children[name] = process
        return process

    def spawn(self, name, command, **kwargs):
        if name in self.children:
            raise RuntimeError(f'Child already owned: {name}')
        kwargs.setdefault('stdout', subprocess.DEVNULL)
        kwargs.setdefault('stderr', subprocess.DEVNULL)
        return self.add(name, subprocess.Popen(command, **kwargs))

    def reap(self, name, first_signal=None):
        process = self.children.get(name)
        if process is None:
            return
        if process.poll() is None:
            try:
                if first_signal is None:
                    process.terminate()
                else:
                    process.send_signal(first_signal)
            except ProcessLookupError:
                pass  # Exited between poll and signal; still wait below.
        try:
            code = process.wait(timeout=10 if name == 'ffmpeg' else 3)
        except subprocess.TimeoutExpired:
            self.escalated.add(name)
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                code = process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                code = process.wait(timeout=2)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        del self.children[name]
        return code

    def cleanup(self):
        errors = []
        for name in list(self.children):
            try:
                self.reap(name, signal.SIGINT if name == 'ffmpeg' else None)
            except Exception as error:
                errors.append(f'{name}: {error}')
        if errors:
            raise RuntimeError('Child cleanup failed: ' + '; '.join(errors))


@dataclass(frozen=True)
class SavedRecording:
    """Confirmed engine save, published only after successful ownership cleanup."""

    token: int
    output: Path


@dataclass
class Session:
    token: int
    cancel: threading.Event = field(default_factory=threading.Event)
    authorized: threading.Event = field(default_factory=threading.Event)


class RecordingLifecycle:
    """Public methods/callbacks are GTK-thread-only; workers never touch widgets.

    A successful countdown queues a GTK authorization, not an engine start. This
    makes Cancel while the UI still says countdown a strict no-output boundary.
    """

    def __init__(self, engine, dispatch, on_state):
        self.engine = engine
        self.dispatch = dispatch
        self.on_state = on_state
        self.state = 'idle'
        self.token = 0
        self.session = None
        self.worker = None
        self.closed = False
        self.started_at = None
        self.indicator_reason = ''
        self.cleanup_owner = None
        self.completion = None

    def _set_state(self, state, message, output=None):
        self.state = state
        self.on_state(state, message, output)

    def _post(self, session, action):
        def callback():
            if (self.session is session and self.token == session.token
                    and not session.cancel.is_set() and not self.closed):
                action()
            return False
        self.dispatch(callback)

    def begin(self, options):
        if self.closed or self.state != 'idle':
            return False
        options.validate()
        self.token += 1
        session = Session(self.token)
        self.session = session
        self.completion = None
        self.started_at = None
        state = 'selecting' if options.source == 'region' else 'countdown'
        self._set_state(state, 'Select a screen region...' if state == 'selecting'
                        else 'Preparing countdown...')
        self.worker = threading.Thread(target=self._run, args=(session, options))
        # Non-daemon: on close, keep GTK alive until the worker reaps its children.
        self.worker.start()
        return True

    def cancel(self):
        if self.state == 'cleanup_failed':
            self.retry_cleanup()
            return
        if self.session is None or self.closed or self.state == 'stopping':
            return
        self.token += 1
        self.session.cancel.set()
        self._set_state('stopping', 'Saving recording...' if self.started_at
                        else 'Cancelling recording...')

    def close(self):
        if self.state == 'cleanup_failed':
            self.closed = True
            self.retry_cleanup()
            return
        if self.closed:
            return
        self.closed = True
        self.token += 1
        self.state = 'closed'
        if self.session is not None:
            self.session.cancel.set()
        else:
            self._set_state('closed', 'Closed')

    def _authorize(self, session):
        if self.state == 'countdown':
            self._set_state('starting', 'Starting recording...')
            session.authorized.set()

    def _complete(self, session, owner, message, output, completion=None):
        if self.session is not session:
            return False
        self.completion = None
        self.started_at = None
        if owner.children:
            # Do NOT quit GTK or allow another recording with unreaped children.
            self.cleanup_owner = owner
            self._set_state('cleanup_failed', message + ' — retry cleanup', output)
        else:
            self.session = None
            self.cleanup_owner = None
            self.completion = completion
            self._set_state('closed' if self.closed else 'idle', message, output)
        return False

    def retry_cleanup(self):
        if self.state != 'cleanup_failed' or self.cleanup_owner is None:
            return
        session, owner = self.session, self.cleanup_owner
        self._set_state('stopping', 'Retrying child cleanup...')
        def worker():
            message = 'Recording cleanup finished; check previous error/output'
            try:
                owner.cleanup()
            except Exception as error:
                message = f'Cleanup error: {error}'
            self.dispatch(lambda: self._complete(session, owner, message, None))
        self.worker = threading.Thread(target=worker)
        self.worker.start()

    def _run(self, session, options):
        # Lazy import keeps process primitives usable by the engine without cycles.
        from engine.recording import normalize_geometry

        owner = OwnedProcesses()
        output = None
        started = False
        recording_confirmed = False
        save_requested = False
        message = 'Recording cancelled'
        try:
            check_cancel(session.cancel)
            if options.source == 'region':
                geometry = self.engine.select_region(cancel=session.cancel, owner=owner)
                if geometry is None:
                    raise Cancelled()
            else:
                # Only the selection token is escaped. The engine resolves raw
                # xrandr IDs; FFmpeg receives the resulting geometry, not names.
                geometry = self.engine.get_monitor_geometry(source_monitor_id(options.source))
            check_cancel(session.cancel)
            geometry = normalize_geometry(geometry)
            self._post(session, lambda: self._set_state('countdown', 'Countdown — cancel to abort'))
            if not COUNTDOWN_SCRIPT.is_file():
                raise FileNotFoundError(f'Countdown helper missing: {COUNTDOWN_SCRIPT}')
            check_cancel(session.cancel)
            if options.source == 'region':
                try:
                    if BORDER_SCRIPT.is_file():
                        owner.spawn('countdown_border', [sys.executable, str(BORDER_SCRIPT),
                                                         *map(str, geometry)])
                except OSError:
                    pass  # Countdown preview is optional; recording border is separate.
            check_cancel(session.cancel)
            child = owner.spawn('countdown', [sys.executable, str(COUNTDOWN_SCRIPT)])
            deadline = time.monotonic() + 15
            while child.poll() is None:
                check_cancel(session.cancel)
                if time.monotonic() >= deadline:
                    raise RuntimeError('Countdown helper timed out')
                session.cancel.wait(0.05)
            code = child.poll()
            owner.reap('countdown')
            check_cancel(session.cancel)
            if code != 0:
                raise RuntimeError(f'Countdown helper exited with status {code}')
            self._post(session, lambda: self._authorize(session))
            while not session.authorized.wait(0.05):
                check_cancel(session.cancel)
            check_cancel(session.cancel)
            # Never capture the preview: a failed reap retains ownership and aborts
            # startup, even after escalation. Cancellation can arrive during wait.
            owner.reap('countdown_border')
            check_cancel(session.cancel)
            output = self.engine.start(region=geometry, fps=options.fps,
                                       quality=options.quality, audio=options.audio,
                                       cancel=session.cancel, owner=owner,
                                       output_dir=options.output_dir)
            started = True
            began = time.monotonic()
            check_cancel(session.cancel)
            if not self.engine.is_recording():
                raise RuntimeError('Recording process ended unexpectedly during startup')
            recording_confirmed = True
            warnings = []
            if options.source == 'region':
                try:
                    if not BORDER_SCRIPT.is_file():
                        raise FileNotFoundError('helper missing')
                    owner.spawn('border', [sys.executable, str(BORDER_SCRIPT),
                                           *map(str, geometry)])
                except OSError as error:
                    warnings.append(f'Border unavailable: {error}')
            check_cancel(session.cancel)
            plan = indicator_plan(geometry)
            reason = plan.reason
            indicator = None
            if plan.command:
                try:
                    indicator = owner.spawn('indicator', plan.command)
                except OSError as error:
                    reason = f'REC launch failed: {error}; ' + FALLBACK
            status = f'Recording... Audio: {options.audio}'
            if warnings:
                status += ' — ' + '; '.join(warnings)
            def recording():
                if self.state == 'starting':
                    self.started_at = began
                    self.indicator_reason = reason
                    self._set_state('recording', status, output)
            self._post(session, recording)
            while not session.cancel.wait(0.1):
                if not self.engine.is_recording():
                    message = 'Recording process ended unexpectedly'
                    break
                if indicator is not None and indicator.poll() is not None:
                    code = indicator.poll()
                    owner.reap('indicator')
                    indicator = None
                    fallback_reason = f'REC exited ({code}); ' + FALLBACK
                    def fallback():
                        if self.state == 'recording':
                            self.indicator_reason = fallback_reason
                            self._set_state('recording', status + ' — REC fallback', output)
                    self._post(session, fallback)
                border = owner.children.get('border')
                if border is not None and border.poll() is not None:
                    owner.reap('border')
                    self._post(session, lambda: self._set_state(
                        'recording', status + ' — Border helper exited', output))
            else:
                save_requested = True
        except Cancelled:
            save_requested = recording_confirmed
        except Exception as error:
            message = f'Recording error: {error}'
        finally:
            errors = []
            saved = None
            completion = None
            if started:
                try:
                    saved = self.engine.stop()
                    if save_requested:
                        message = f'Saved: {saved.name}' if saved else 'No recording was saved'
                except Exception as error:
                    errors.append(str(error))
            try:
                owner.cleanup()
            except Exception as error:
                errors.append(str(error))
            if errors:
                message = 'Cleanup error: ' + '; '.join(errors)
            elif (save_requested and saved is not None and not owner.children
                  and 'ffmpeg' not in owner.escalated):
                # stop() validates exit status, nonempty output and no forced stop.
                # Never derive success from a display message or start()'s path.
                completion = SavedRecording(session.token, saved)
            self.dispatch(lambda: self._complete(session, owner, message, output, completion))
