"""User-local installation only; no application imports or desktop activation."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile


APP_ID = 'io.github.screenrecorder.ScreenRecorder'
MARKER = 'screen-recorder installer: ' + APP_ID + ' v1'
PYTHON = '/usr/bin/python3'
MANIFEST = '.screen-recorder-install.json'
PROBE = '''import gi
import cairo
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GdkX11", "3.0")
gi.require_foreign("cairo")
from gi.repository import Gtk, Gdk, GLib, GdkPixbuf, Pango, GdkX11
'''


class InstallError(Exception):
    pass


def absolute_path(value, label):
    path = Path(value)
    if (not value or not path.is_absolute() or '..' in path.parts
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise InstallError(label + ' must be an absolute path without traversal/control characters')
    return path


class Layout:
    def __init__(self, home, data):
        self.home = home
        self.data = data
        self.payload = data / 'screen-recorder'
        self.launcher = home / '.local/bin/screen-recorder-gtk'
        self.desktop = data / 'applications/screen-recorder.desktop'
        self.manifest = self.payload / MANIFEST

    @classmethod
    def from_environment(cls):
        home = absolute_path(os.environ.get('HOME', ''), 'HOME')
        if home == Path('/'):
            raise InstallError('HOME must not be /')
        # Validate provided XDG variables, even ones this installer never writes.
        for name in ('XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME',
                     'XDG_STATE_HOME', 'XDG_RUNTIME_DIR', 'XDG_DATA_DIRS', 'XDG_CONFIG_DIRS'):
            value = os.environ.get(name, '')
            if value:
                for component in value.split(':') if name.endswith('_DIRS') else [value]:
                    absolute_path(component, name)
        data = absolute_path(os.environ.get('XDG_DATA_HOME') or str(home / '.local/share'),
                             'XDG_DATA_HOME')
        return cls(home, data)

    def target(self, key):
        if key == 'launcher':
            return self.launcher
        if key == 'desktop':
            return self.desktop
        if key.startswith('payload/') and runtime_name(key[8:]):
            return self.payload / key[8:]
        raise InstallError('Invalid manifest file path: ' + key)


def safe_path(path):
    """Reject symlinks (including dangling ones) and non-directory ancestors."""
    for current in reversed((path, *path.parents)):
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise InstallError('Symlink refused: ' + str(current))
        if current != path and not stat.S_ISDIR(mode):
            raise InstallError('Non-directory ancestor: ' + str(current))


def runtime_name(name):
    path = PurePosixPath(name)
    if not name or str(path) != name or path.is_absolute() or '..' in path.parts:
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        return False
    if name in ('main.py', 'recorder.py', 'preferences.py', 'installation.py', 'uninstall.sh'):
        return True
    parts = path.parts
    return (len(parts) >= 2 and parts[0] == 'engine' and path.suffix == '.py'
            or len(parts) == 2 and parts[0] == 'helpers' and path.suffix == '.py'
            or len(parts) == 2 and parts[0] == 'assets')


def valid_directory(name):
    path = PurePosixPath(name)
    return (str(path) == name and not path.is_absolute() and '..' not in path.parts
            and (name in ('assets', 'helpers') or path.parts and path.parts[0] == 'engine')
            and not any(ord(c) < 32 or ord(c) == 127 for c in name))


def file_record(content, mode):
    return {'sha256': hashlib.sha256(content).hexdigest(), 'mode': mode}


def matches(path, record, key=None):
    safe_path(path)
    if not path.exists() or not path.is_file():
        return False
    content = path.read_bytes()
    if key in ('launcher', 'desktop'):
        prefix = ('#!/bin/sh\n' if key == 'launcher' else '') + '# ' + MARKER + '\n'
        if not content.startswith(prefix.encode()):
            return False
    return file_record(content, stat.S_IMODE(path.stat().st_mode)) == record


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InstallError('Duplicate manifest key')
        result[key] = value
    return result


def read_manifest(layout):
    for path in (layout.payload, layout.manifest, layout.launcher, layout.desktop):
        safe_path(path)
    if not layout.manifest.exists():
        if layout.payload.exists():
            raise InstallError('Foreign payload directory (no ownership manifest): ' + str(layout.payload))
        return None
    if not layout.manifest.is_file() or layout.manifest.stat().st_size > 1024 * 1024:
        raise InstallError('Invalid ownership manifest')
    try:
        data = json.loads(layout.manifest.read_text(), object_pairs_hook=no_duplicate_keys)
        if (set(data) != {'owner', 'home', 'data', 'files', 'directories'}
                or data['owner'] != MARKER or data['home'] != str(layout.home)
                or data['data'] != str(layout.data) or not isinstance(data['files'], dict)
                or not isinstance(data['directories'], list)):
            raise ValueError('ownership/location mismatch')
        for key, record in data['files'].items():
            layout.target(key)
            if (not isinstance(record, dict) or set(record) != {'sha256', 'mode'}
                    or not isinstance(record['sha256'], str)
                    or not re.fullmatch('[0-9a-f]{64}', record['sha256'])
                    or type(record['mode']) is not int or record['mode'] not in (0o644, 0o755)):
                raise ValueError('invalid file record')
        if len(set(data['directories'])) != len(data['directories']):
            raise ValueError('duplicate directories')
        for name in data['directories']:
            if not isinstance(name, str) or not valid_directory(name):
                raise ValueError('invalid directory')
            safe_path(layout.payload / name)
            if (layout.payload / name).exists() and not (layout.payload / name).is_dir():
                raise ValueError('directory replaced by file')
    except (ValueError, TypeError, KeyError, OSError) as error:
        raise InstallError('Invalid ownership manifest: ' + str(error)) from error
    return data


def check_dependencies():
    if sys.version_info < (3, 10) or not Path(PYTHON).is_file():
        raise InstallError('System Python 3.10+ required at ' + PYTHON + '; see INSTALL.md')
    missing = [name for name in ('ffmpeg', 'xrandr', 'slop', 'pactl') if not shutil.which(name)]
    try:
        probe = subprocess.run([PYTHON, '-I', '-B', '-c', PROBE],
                               capture_output=True, text=True, timeout=15)
        if probe.returncode:
            missing.append('Python GI/GTK3/GdkX11/Pango/Cairo: ' + probe.stderr.strip())
    except (OSError, subprocess.SubprocessError) as error:
        missing.append('Python GI/GTK3/Cairo probe: ' + str(error))
    if missing:
        raise InstallError('Missing dependencies: ' + ', '.join(missing) + '; see INSTALL.md')


def desktop_string(value):
    # Desktop Entry general string escaping comes before Exec parsing.
    return value.replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')


def desktop_argument(value):
    # Exec uses double quotes, NOT shell single quotes. %% is a literal percent.
    value = value.replace('%', '%%')
    for character in ('\\', '"', '`', '$'):
        value = value.replace(character, '\\' + character)
    return desktop_string('"' + value + '"')


def collect_payload(source):
    safe_path(source)
    names = ['main.py', 'recorder.py', 'preferences.py', 'installation.py', 'uninstall.sh']
    for directory in ('engine', 'helpers', 'assets'):
        base = source / directory
        safe_path(base)
        if not base.is_dir():
            raise InstallError('Missing runtime directory: ' + str(base))
        if directory == 'engine':
            for root, dirs, files in os.walk(base, followlinks=False):
                dirs[:] = sorted(name for name in dirs if name != '__pycache__')
                for name in dirs:
                    safe_path(Path(root) / name)
                names.extend(str((Path(root) / name).relative_to(source))
                             for name in sorted(files) if name.endswith('.py'))
        else:
            names.extend(str(path.relative_to(source)) for path in sorted(base.iterdir())
                         if directory == 'assets' or path.suffix == '.py')
    result = {}
    for name in names:
        path = source / name
        safe_path(path)
        if not runtime_name(name) or not path.is_file():
            raise InstallError('Invalid/missing runtime file: ' + str(path))
        result['payload/' + name] = (path.read_bytes(), 0o755 if name == 'uninstall.sh' else 0o644)
    if 'payload/assets/screen-recorder-icon.png' not in result:
        raise InstallError('Missing runtime icon: assets/screen-recorder-icon.png')
    return result


def write_file(path, content, mode):
    """Replace only preflighted files, never follow a destination symlink."""
    safe_path(path)
    fd, temporary = tempfile.mkstemp(prefix='.screen-recorder-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_manifest(layout, files, directories):
    data = {'owner': MARKER, 'home': str(layout.home), 'data': str(layout.data),
            'files': files, 'directories': sorted(directories)}
    write_file(layout.manifest, (json.dumps(data, sort_keys=True, indent=2) + '\n').encode(), 0o644)


def install(source, layout):
    old = read_manifest(layout)
    desired = collect_payload(source)
    launcher = ('#!/bin/sh\n# ' + MARKER + '\nexec ' + PYTHON + ' -B '
                + shlex.quote(str(layout.payload / 'main.py')) + ' "$@"\n')
    desktop = ('# ' + MARKER + '\n[Desktop Entry]\nType=Application\nName=Screen Recorder\n'
               # Gio checks the executable before expanding %% field codes. Use a
               # stable executable; the escaped launcher is a literal script argument,
               # not shell source (-c), so path punctuation cannot be evaluated.
               'Comment=Record your X11 desktop\nExec=/bin/sh ' + desktop_argument(str(layout.launcher))
               + '\nIcon=' + desktop_string(str(layout.payload / 'assets/screen-recorder-icon.png'))
               + '\nTerminal=false\nCategories=AudioVideo;Recorder;\nStartupNotify=true\n'
               'StartupWMClass=' + APP_ID + '\nDBusActivatable=false\n')
    desired.update(launcher=(launcher.encode(), 0o755), desktop=(desktop.encode(), 0o644))
    files = dict(old['files']) if old else {}
    directories = set(old['directories']) if old else set()
    # Check ALL collisions and owned hashes before creating or updating anything.
    for key in set(files) | set(desired):
        path = layout.target(key)
        safe_path(path)
        if path.exists() and (key not in files or not matches(path, files[key], key)):
            raise InstallError('Foreign or modified file refused: ' + str(path))
    needed = set()
    for key in desired:
        if key.startswith('payload/'):
            parent = PurePosixPath(key[8:]).parent
            while str(parent) != '.':
                needed.add(str(parent))
                parent = parent.parent
    for name in needed:
        path = layout.payload / name
        safe_path(path)
        if path.exists() and (name not in directories or not path.is_dir()):
            raise InstallError('Foreign directory refused: ' + str(path))
    check_dependencies()
    for path in (layout.payload, layout.launcher.parent, layout.desktop.parent):
        safe_path(path)
        path.mkdir(parents=True, exist_ok=True)
    for name in sorted(needed, key=lambda value: (value.count('/'), value)):
        (layout.payload / name).mkdir(exist_ok=True)
    directories.update(needed)
    for key, (content, mode) in desired.items():
        path = layout.target(key)
        record = file_record(content, mode)
        if not matches(path, record):
            write_file(path, content, mode)
        files[key] = record
    save_manifest(layout, files, directories)


def uninstall(layout):
    data = read_manifest(layout)
    if data is None:
        return []
    # Validate every path before deleting even one file.
    for key in data['files']:
        safe_path(layout.target(key))
    remaining = {}
    for key, record in data['files'].items():
        path = layout.target(key)
        if matches(path, record, key):
            path.unlink()
        elif path.exists():
            remaining[key] = record
    directories = []
    for name in sorted(data['directories'], key=lambda value: (value.count('/'), value), reverse=True):
        path = layout.payload / name
        if path.exists():
            if any(path.iterdir()):
                directories.append(name)
            else:
                path.rmdir()
    if remaining:
        save_manifest(layout, remaining, directories)
    else:
        layout.manifest.unlink()
        # Never recursive: user-added files/subdirectories keep the payload alive.
        if not any(layout.payload.iterdir()):
            layout.payload.rmdir()
    return sorted(str(layout.target(key)) for key in remaining)


def main():
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in ('install', 'uninstall'):
            raise InstallError('Usage: installation.py install|uninstall')
        layout = Layout.from_environment()
        if sys.argv[1] == 'install':
            install(Path(__file__).absolute().parent, layout)
            print('Installed. Launch manually: ' + shlex.quote(str(layout.launcher)))
        else:
            preserved = uninstall(layout)
            print('Uninstall finished; configuration and recordings untouched.')
            for path in preserved:
                print('Preserved modified/foreign file: ' + path)
    except (InstallError, OSError) as error:
        print('screen-recorder: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
