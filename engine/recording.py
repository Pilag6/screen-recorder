#!/usr/bin/env python3

import os
import re
import signal
import subprocess
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


class RecordingEngine:
    def __init__(self):
        self.process = None
        self.output_file = None

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
                r"\+(\d+)\+(\d+)",
                parts[2],
            )

            if not match:
                raise ValueError("Invalid monitor geometry")

            width, height, x, y = map(int, match.groups())

            return x, y, width, height

        raise ValueError(
            f"Monitor not found: {monitor_name}"
        )

    def select_region(self):
        result = subprocess.run(
            ["slop", "-f", "%x %y %w %h"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return None

        values = result.stdout.strip().split()

        if len(values) != 4:
            raise ValueError("Invalid region selection")

        x, y, width, height = map(int, values)

        if width < 2 or height < 2:
            raise ValueError("Region is too small")

        return x, y, width, height

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
    ):
        if self.is_recording():
            raise RuntimeError("Already recording")

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

        width = width // 2 * 2
        height = height // 2 * 2

        if width < 2 or height < 2:
            raise ValueError("Region is too small")

        audio_args = self.build_audio_arguments(audio)

        OUTPUT_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        filename = datetime.now().strftime(
            "Recording-%Y-%m-%d_%H-%M-%S.mkv"
        )

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

        self.process = subprocess.Popen(command)

        return self.output_file

    def stop(self):
        if not self.is_recording():
            return None

        self.process.send_signal(signal.SIGINT)

        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()

            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

        self.process = None

        return self.output_file

    def is_recording(self):
        return (
            self.process is not None
            and self.process.poll() is None
        )
