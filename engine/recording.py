#!/usr/bin/env python3

import os
import re
import signal
import subprocess
import uuid

from engine.lifecycle import OwnedProcesses, check_cancel
from datetime import datetime
from pathlib import Path


OUTPUT_DIR = Path.home() / "Videos" / "Recordings"

QUALITY_PRESETS = {
    "normal": 28,
    "high": 23,
}

VALID_AUDIO = {
    "none",
    "system",
    "mic",
    "both",
}


def normalize_geometry(geometry):
    """One capture rectangle for FFmpeg, border, and indicator policy."""
    if len(geometry) != 4 or any(type(value) is not int for value in geometry):
        raise ValueError("Invalid capture geometry")
    x, y, width, height = geometry
    width = width // 2 * 2
    height = height // 2 * 2
    if width < 2 or height < 2:
        raise ValueError("Region is too small")
    return x, y, width, height


class RecordingEngine:
    def __init__(self):
        self.process = None
        self.output_file = None
        self.owner = None

    def get_monitor_geometry(self, monitor_name):
        result = subprocess.run(
            ["xrandr", "--listmonitors"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )

        for line in result.stdout.splitlines()[1:]:
            parts = line.split()

            if len(parts) < 4 or parts[-1] != monitor_name:
                continue

            match = re.fullmatch(
                r"(\d+)(?:/\d+)?x(\d+)(?:/\d+)?"
                r"([+-]\d+)([+-]\d+)",
                parts[2],
            )

            if not match:
                raise ValueError("Invalid monitor geometry")

            width, height, x, y = map(int, match.groups())

            return x, y, width, height

        raise ValueError(
            f"Monitor not found: {monitor_name}"
        )

    def select_region(self, cancel=None, owner=None):
        own_registry = owner is None
        owner = owner if owner is not None else OwnedProcesses()
        check_cancel(cancel)
        child = owner.spawn(
            'selection', ["slop", "-f", "%x %y %w %h"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            while True:
                check_cancel(cancel)
                try:
                    stdout, _ = child.communicate(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
            code = child.returncode
            owner.reap('selection')
            check_cancel(cancel)
            if code != 0:
                return None
            values = stdout.strip().split()
            if len(values) != 4:
                raise ValueError("Invalid region selection")
            return normalize_geometry(tuple(map(int, values)))
        finally:
            if own_registry:
                owner.cleanup()

    def get_default_audio_devices(self):
        sink = subprocess.run(
            ["pactl", "get-default-sink"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()

        source = subprocess.run(
            ["pactl", "get-default-source"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()

        if not sink or not source:
            raise RuntimeError(
                "Could not detect audio devices"
            )

        return f"{sink}.monitor", source

    def build_audio_arguments(self, audio):
        if audio not in VALID_AUDIO:
            raise ValueError("Invalid audio mode")

        if audio == "none":
            return ["-map", "0:v", "-an"]

        monitor, microphone = self.get_default_audio_devices()

        if audio == "system":
            return [
                "-f", "pulse",
                "-i", monitor,
                "-map", "0:v",
                "-map", "1:a",
                "-c:a", "aac",
                "-b:a", "192k",
            ]

        if audio == "mic":
            return [
                "-f", "pulse",
                "-i", microphone,
                "-map", "0:v",
                "-map", "1:a",
                "-c:a", "aac",
                "-b:a", "192k",
            ]

        return [
            "-f", "pulse",
            "-i", monitor,
            "-f", "pulse",
            "-i", microphone,
            "-filter_complex",
            "[1:a][2:a]amix=inputs=2:"
            "duration=longest:dropout_transition=0[a]",
            "-map", "0:v",
            "-map", "[a]",
            "-c:a", "aac",
            "-b:a", "192k",
        ]

    def start(
        self,
        monitor=None,
        region=None,
        fps=30,
        quality="high",
        audio="none",
        cancel=None,
        owner=None,
    ):
        check_cancel(cancel)
        if self.is_recording():
            raise RuntimeError("Already recording")
        if self.process is not None:
            if self.owner is not None and 'ffmpeg' not in self.owner.children:
                self.process = None  # Session cleanup already reaped it.
                self.owner = None
            else:
                self.stop()

        if fps not in (30, 60):
            raise ValueError("Invalid frame rate")

        if quality not in QUALITY_PRESETS:
            raise ValueError("Invalid quality")

        if audio not in VALID_AUDIO:
            raise ValueError("Invalid audio mode")

        if region is not None:
            x, y, width, height = region
        elif monitor is not None:
            x, y, width, height = (
                self.get_monitor_geometry(monitor)
            )
        else:
            raise ValueError("No recording source selected")

        x, y, width, height = normalize_geometry((x, y, width, height))
        check_cancel(cancel)
        audio_args = self.build_audio_arguments(audio)
        check_cancel(cancel)

        OUTPUT_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        filename = datetime.now().strftime("Recording-%Y-%m-%d_%H-%M-%S")
        filename += f'-{uuid.uuid4().hex[:8]}.mkv'  # Never overwrite a rapid restart.

        self.output_file = OUTPUT_DIR / filename

        command = [
            "ffmpeg",
            "-nostdin",
            "-loglevel", "error",
            "-f", "x11grab",
            "-framerate", str(fps),
            "-video_size", f"{width}x{height}",
            "-i", f"{os.environ.get('DISPLAY', ':0')}+{x},{y}",
            *audio_args,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", str(QUALITY_PRESETS[quality]),
            "-pix_fmt", "yuv420p",
            str(self.output_file),
        ]

        check_cancel(cancel)
        self.owner = owner if owner is not None else OwnedProcesses()
        self.process = self.owner.spawn('ffmpeg', command)
        return self.output_file

    def stop(self):
        if self.process is None:
            return None
        owner = self.owner if self.owner is not None else OwnedProcesses()
        if 'ffmpeg' not in owner.children:
            owner.add('ffmpeg', self.process)
        code = owner.reap('ffmpeg', signal.SIGINT)
        self.process = None
        self.owner = None
        if code not in (0, 255) or 'ffmpeg' in owner.escalated:
            raise RuntimeError(f'FFmpeg exited ({code}) or required forced shutdown; '
                               f'output may be incomplete: {self.output_file}')
        if (self.output_file is None or not self.output_file.is_file()
                or self.output_file.stat().st_size == 0):
            raise RuntimeError('FFmpeg did not save a nonempty recording')
        return self.output_file

    def is_recording(self):
        return (
            self.process is not None
            and self.process.poll() is None
        )
