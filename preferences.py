"""Small, GTK-independent storage for versioned user preferences."""
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import tempfile

from recorder import DEFAULT_OUTPUT_DIR, normalize_output_directory


@dataclass(frozen=True)
class Preferences:
    source: str = 'region'
    audio: str = 'both'
    fps: int = 30
    quality: str = 'high'
    output_dir: str = DEFAULT_OUTPUT_DIR


def settings_path():
    root = Path(os.environ.get('XDG_CONFIG_HOME', ''))
    if not root.is_absolute():
        root = Path.home() / '.config'
    return root / 'screen-recorder' / 'settings.json'


def load_preferences(path=None):
    """Load valid fields independently, without creating any directories."""
    defaults = Preferences()
    try:
        path = settings_path() if path is None else Path(path)
        with path.open(encoding='utf-8') as stream:
            document = json.load(stream)
    except (OSError, ValueError, RuntimeError):
        return defaults

    if (not isinstance(document, dict)
            or type(document.get('version')) is not int
            or document['version'] != 1):
        return defaults

    source = document.get('source')
    audio = document.get('audio')
    fps = document.get('fps')
    quality = document.get('quality')
    output_dir = defaults.output_dir
    if isinstance(document.get('output_dir'), str):
        try:
            output_dir = str(normalize_output_directory(document['output_dir']))
        except ValueError:
            pass
    return Preferences(
        source=source if isinstance(source, str) and source else defaults.source,
        audio=audio if audio in ('none', 'system', 'mic', 'both') else defaults.audio,
        fps=fps if type(fps) is int and fps in (30, 60) else defaults.fps,
        quality=quality if quality in ('normal', 'high') else defaults.quality,
        output_dir=output_dir,
    )


def save_preferences(preferences, path=None):
    """Atomically replace settings; return False on a nonfatal storage failure."""
    temporary = None
    try:
        path = settings_path() if path is None else Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # The temporary file must share the destination filesystem for replace.
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', dir=path.parent,
            prefix='.settings-', suffix='.tmp', delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump({'version': 1, **asdict(preferences)}, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return True
    except (OSError, ValueError, RuntimeError):
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
