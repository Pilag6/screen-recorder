# Install Screen Recorder independently of its checkout

These scripts provide a **user-local X11 installation** for Mint Cinnamon/Ubuntu.
They copy the runtime, create a launcher and menu entry, and never start the app,
install packages, configure shortcuts, change audio settings, or record anything.
No administrator privileges or virtualenv are needed.

## Future installation and manual activation

**Do not run this against an existing real installation until collisions have
been resolved deliberately.** The existing `screen-recorder-gtk` launcher and
`screen-recorder.desktop` entry are foreign unless created by this installer.
The scripts will refuse them, not adopt, overwrite, move, or delete them.

When you are ready, from the checkout:

```sh
sh ./install.sh
```

A successful install reports the launcher path. Only then, if you want to launch
it yourself (in an X11 desktop session):

```sh
"$HOME/.local/bin/screen-recorder-gtk"
```

The launcher works from any working directory, even after the checkout moves.
Adding `~/.local/bin` to PATH is optional and is **not** done by the installer.
The desktop may discover the new menu entry automatically; no menu-cache refresh,
autostart, D-Bus service registration, or desktop activation is performed here.

## Dependencies: system Python, not a venv

| Requirement | Mint/Ubuntu package guidance |
|---|---|
| `/usr/bin/python3`, Python 3.10+ | `python3` |
| PyGObject and Cairo integration | `python3-gi`, `python3-gi-cairo`, `python3-cairo` |
| GTK3/GdkX11, GdkPixbuf, Pango typelibs | `gir1.2-gtk-3.0`, `gir1.2-gdkpixbuf-2.0`, `gir1.2-pango-1.0` |
| Recording and X11 monitor/region tools | `ffmpeg`, `x11-xserver-utils` (`xrandr`), `slop` |
| PulseAudio-compatible audio discovery | `pulseaudio-utils` (`pactl`); an active PulseAudio or PipeWire-Pulse session at runtime |
| Optional desktop notifications | `gir1.2-notify-0.7` |

Arrange missing packages separately through your normal system administration
workflow. These scripts **never install them**, and a pip-only environment is not
a substitute for system GTK typelibs. Both shell scripts and the installed
launcher select `/usr/bin/python3`, regardless of a virtualenv's PATH Python.

Before any installation writes, the installer checks tool availability on PATH
without executing those tools. Its isolated system-Python probe imports GI,
GTK3/GdkX11 and Cairo bindings without initializing GTK or opening a window.
Missing requirements are reported with a nonzero exit status. Uninstall does
not need GTK or recording dependencies. This check does not prove that a display,
audio server, codecs, or permissions will be usable later. Wayland recording is
not supported by this X11 runtime.

## Locations and identity

| Item | Location |
|---|---|
| Runtime and ownership manifest | `${XDG_DATA_HOME:-$HOME/.local/share}/screen-recorder/` |
| Executable launcher | `$HOME/.local/bin/screen-recorder-gtk` |
| Desktop entry | `${XDG_DATA_HOME:-$HOME/.local/share}/applications/screen-recorder.desktop` |
| Existing icon | Payload's `assets/screen-recorder-icon.png` |
| Standalone uninstall support | Payload's `uninstall.sh` and `installation.py` |

`HOME` and supplied XDG paths must be absolute, without `..` traversal or control
characters. XDG search-directory lists must contain absolute entries. Empty
`XDG_DATA_HOME` uses the standard fallback. Use the **same HOME/XDG_DATA_HOME**
for later updates and uninstall; do not move a payload and edit its manifest.
Spaces, single/double quotes, dollars, literal percent signs and backslashes are
escaped separately for the shell launcher and Desktop Entry syntax. The desktop
`Exec` uses the stable system executable `/bin/sh` followed by the desktop-escaped
absolute launcher path as a script argument, with literal percent signs encoded
as `%%`. This avoids GLib/Gio rejecting a percent-containing executable path
before field-code expansion. There is no `sh -c` or evaluation of the path as
shell code; the launcher still selects `/usr/bin/python3`.

The payload includes `main.py`, `recorder.py`, `preferences.py`, all
`engine/**/*.py`, `helpers/*.py`, and direct asset files. Runtime files are
byte-for-byte copies, including the pinned REC helper. The installer does not
modify the application's singleton ID: `io.github.screenrecorder.ScreenRecorder`.

The compatible desktop filename remains `screen-recorder.desktop`, with
`StartupWMClass=io.github.screenrecorder.ScreenRecorder` and
`DBusActivatable=false`. There is no evidence requiring an ID-named entry here.
Creating a second ID-named entry instead would leave old launchers/menu entries
alongside it and could duplicate menu items or pinned icons. The GTK application
ID, not the desktop filename, supplies session-bus singleton behavior. Actual
Cinnamon grouping/pinning still requires a future manual desktop check.

## Repeat install and collision rules

Run `sh ./install.sh` again to update an owned installation. A matching install
is idempotent. Missing owned files can be restored; existing owned files must
still match their recorded SHA-256 **and permissions** before any update.
Launcher/desktop ownership also requires the installer marker. Previously owned
runtime files absent from a newer checkout are retained until uninstall.

- An existing payload without a valid, location-bound manifest is foreign.
- Foreign destination files and newly required foreign payload directories
  stop installation before writes. User-added unrelated files remain untouched.
- Symlinks (including dangling links and path ancestors), malformed manifests,
  traversal and modified owned files are rejected. Symlinked HOME/XDG ancestors
  are intentionally unsupported, rather than followed.
- Do not delete or edit the manifest to bypass a collision. Back up and resolve
  the specific foreign/modified items manually only when you decide to do so.

The manifest is a local ownership ledger, **not authentication against another
process running as your user**. Run only one install/uninstall at a time, with no
concurrent destination edits. Individual writes are atomic, but the multi-file
operation is not a transaction: an interruption or disk error may leave a partial
installation that requires manual inspection. Safety takes precedence over
silently adopting files during recovery.

## Safe uninstall

From the checkout:

```sh
sh ./uninstall.sh
```

Or, after the checkout is gone:

```sh
sh "${XDG_DATA_HOME:-$HOME/.local/share}/screen-recorder/uninstall.sh"
```

Only manifested files whose hashes, permissions and applicable markers still
match are removed. Modified/replaced regular files are preserved and reported;
the manifest retains their original ownership records for a later safe retry.
If the installed uninstall helper itself was preserved or removed during a partial
uninstall, use a trusted checkout's script for that retry.

Directories are removed **only when empty** and owned. No recursive deletion is
used. Untracked files/subdirectories, preferences/configuration and recordings
are never removed. Shared `bin`/`applications` directories are left in place.
A symlink or malformed manifest stops uninstall before any removal. An absent
installation is a no-op; a foreign payload directory is an error. If only user
files remain, the manifest is removed and the leftover payload becomes foreign;
subsequent install/uninstall will refuse to adopt it.

## Verification boundary

`tests/test_installation.py` uses temporary HOME and all XDG directories, passive
dependency doubles, and a harmless launcher fixture, never the recording GUI.
It covers repeat installation, payload fidelity, source-independent execution,
escaping, ownership collisions, traversal/symlink refusal and preservation during
uninstall. When GI/Gio is available, real `Gio.DesktopAppInfo` tests parse percent
and combined-punctuation paths and launch only an inert Python fixture, checking
its payload path, arguments and isolated HOME/XDG environment. These regressions
are skipped only when GI/Gio is unavailable; the custom escaping decoder alone
is not evidence of desktop compatibility. Shell syntax and Python syntax checks
do not activate the app.
Real installation, GUI grouping, audio operation and recording are intentionally
outside this verification and remain future, explicit user actions.
