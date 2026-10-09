#!/usr/bin/env python3

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

            if not parts or parts[-1] != monitor_name:
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
        """Let the user select a screen region with slop."""

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

    def start(
        self,
        monitor=None,
        region=None,
        fps=30,
        quality="high",
    ):
        if self.is_recording():
            raise RuntimeError("Already recording")

        if fps not in (30, 60):
            raise ValueError("Invalid frame rate")

        if quality not in QUALITY_PRESETS:
            raise ValueError("Invalid quality")

        if region is not None:
            x, y, width, height = region
        elif monitor is not None:
            x, y, width, height = self.get_monitor_geometry(
                monitor
            )
        else:
            raise ValueError("No recording source selected")

        # H.264 works best with even dimensions.
        width = width // 2 * 2
        height = height // 2 * 2

        if width < 2 or height < 2:
            raise ValueError("Region is too small")

        OUTPUT_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        filename = datetime.now().strftime(
            "Recording-%Y-%m-%d_%H-%M-%S.mkv"
        )

        self.output_file = OUTPUT_DIR / filename

        crf = QUALITY_PRESETS[quality]

        command = [
            "ffmpeg",
            "-nostdin",
            "-loglevel", "error",
            "-f", "x11grab",
            "-framerate", str(fps),
            "-video_size", f"{width}x{height}",
            "-i", f"{subprocess.os.environ.get('DISPLAY', ':0')}+{x},{y}",
            "-map", "0:v",
            "-an",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", str(crf),
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
            self.process.wait(timeout=5)

        self.process = None

        return self.output_file

    def is_recording(self):
        return (
            self.process is not None
            and self.process.poll() is None
        )
