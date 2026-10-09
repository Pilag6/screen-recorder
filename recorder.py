#!/usr/bin/env python3

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile


DEFAULT_OUTPUT_DIR = str(Path.home() / 'Videos' / 'Recordings')


def normalize_output_directory(value):
    """Validate path syntax only; preference loading must not touch the disk."""
    if not isinstance(value, (str, Path)):
        raise ValueError('Choose a local absolute output folder')
    text = str(value)
    if not text.strip() or '\x00' in text:
        raise ValueError('Choose a nonempty output folder without NUL characters')
    try:
        path = Path(text).expanduser()
    except (ValueError, RuntimeError) as error:
        raise ValueError('Cannot expand the output folder; choose an absolute path') from error
    if not path.is_absolute():
        raise ValueError('Choose a local absolute output folder')
    return path


def prepare_output_directory(value):
    """Create parents and prove real write capability with an auto-removed probe."""
    path = normalize_output_directory(value)
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path, prefix='.recording-write-test-') as probe:
        probe.write(b'write test')
        probe.flush()
        os.fsync(probe.fileno())
    return path


VALID_AUDIO = {"none", "system", "mic", "both"}
VALID_FPS = {30, 60}
VALID_QUALITY = {"normal", "high"}


@dataclass(frozen=True)
class RecordingOptions:
    source: str
    audio: str
    fps: int
    quality: str
    output_dir: str = DEFAULT_OUTPUT_DIR

    def validate(self):
        if not self.source:
            raise ValueError("No screen source selected")

        if self.audio not in VALID_AUDIO:
            raise ValueError("Invalid audio source")

        if self.fps not in VALID_FPS:
            raise ValueError("Invalid frame rate")

        if self.quality not in VALID_QUALITY:
            raise ValueError("Invalid video quality")

        normalize_output_directory(self.output_dir)

    def to_arguments(self):
        self.validate()

        return [
            "--source", self.source,
            "--audio", self.audio,
            "--fps", str(self.fps),
            "--quality", self.quality,
        ]
