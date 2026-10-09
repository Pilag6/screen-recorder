#!/usr/bin/env python3

from dataclasses import dataclass


VALID_AUDIO = {"none", "system", "mic", "both"}
VALID_FPS = {30, 60}
VALID_QUALITY = {"normal", "high"}


@dataclass(frozen=True)
class RecordingOptions:
    source: str
    audio: str
    fps: int
    quality: str

    def validate(self):
        if not self.source:
            raise ValueError("No screen source selected")

        if self.audio not in VALID_AUDIO:
            raise ValueError("Invalid audio source")

        if self.fps not in VALID_FPS:
            raise ValueError("Invalid frame rate")

        if self.quality not in VALID_QUALITY:
            raise ValueError("Invalid video quality")

    def to_arguments(self):
        self.validate()

        return [
            "--source", self.source,
            "--audio", self.audio,
            "--fps", str(self.fps),
            "--quality", self.quality,
        ]
