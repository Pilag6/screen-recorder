# Screen Recorder

A focused GTK3 screen recorder for **Linux Mint Cinnamon on X11**. Capture a
selected region or one monitor, with optional system audio and microphone input,
and save H.264 video in Matroska (`.mkv`) files.

**v1.0.0 release preparation:** publication is pending confirmation of icon/helper
distribution rights and a verified existing repository origin. No public download
or issue-tracker URL is currently verified. See [resource notices](THIRD_PARTY.md)
and [release notes](RELEASE_NOTES.md).

## Install and start

Use a trusted local checkout containing the application, `engine/`, `helpers/`,
`assets/`, and release metadata. Run in an X11 desktop session, not Wayland.
Python 3.10+ at `/usr/bin/python3` and system GTK bindings are required; a pip-only
virtual environment is not enough.

| Requirement | Mint/Ubuntu packages |
|---|---|
| Python and GTK/Cairo bindings | `python3`, `python3-gi`, `python3-gi-cairo`, `python3-cairo` |
| GTK3, GdkPixbuf and Pango typelibs | `gir1.2-gtk-3.0`, `gir1.2-gdkpixbuf-2.0`, `gir1.2-pango-1.0` |
| Capture and screen selection | `ffmpeg`, `x11-xserver-utils`, `slop` |
| Audio discovery | `pulseaudio-utils` |
| Optional saved-file notifications | `gir1.2-notify-0.7` |

Arrange missing packages through your normal package-management workflow. FFmpeg
must support `x11grab`, `libx264` and, for audio, Pulse input and AAC encoding.
Audio capture needs an active PulseAudio or PipeWire-Pulse session.

From the checkout:

```sh
sh ./install.sh
```

This creates a **user-local** runtime copy, launcher and menu entry. It does not
install dependencies, start the application, configure shortcuts or change audio
settings. Do not use `sudo`. Existing foreign launchers, modified installed files
and symlinked destinations are refused, not overwritten; see
[INSTALL.md](INSTALL.md) before resolving any collision.

After a successful installation, start manually:

```sh
"$HOME/.local/bin/screen-recorder-gtk"
```

The installed launcher works from any directory without the original checkout.
You can also use the desktop's Screen Recorder menu entry if discovered. Adding
`~/.local/bin` to PATH is optional. To run directly from the checkout instead:

```sh
/usr/bin/python3 -B main.py
```

Launching again in the same desktop session presents the existing window rather
than creating a second recorder. No global keyboard shortcut is installed.

## Make a recording

1. Choose **Select region** or a connected display under **Screen source**.
2. Choose audio, frame rate, quality and the **Save to** folder.
3. Click **Start Recording**. For a region, drag the selection rectangle; a
   countdown follows before capture begins. Preparation can be cancelled.
4. The window minimizes when recording starts. Restore it and click
   **Stop Recording**; wait for the saved-file status before using the output.

For region capture, a red border marks the selected area when the helper is
available. The external REC timer is shown only when its guarded placement can
be proven outside the capture. Otherwise, elapsed time
remains in the application window/title; restore the window to stop recording.
Saved-file notifications are optional; an **Open folder** action depends on
notification-server support and the application remaining open.

### Audio

| Mode | UI label | Captured audio |
|---|---|---|
| None | No audio | Video only; no audio-device discovery |
| System | System audio | Monitor of the default output sink |
| Microphone | Microphone | Default input source |
| Both | System + microphone | Mix of the default sink monitor and input source |

The application uses your existing audio defaults; it does not configure devices.
Microphone mode captures the default source, which may not be a physical mic.
All audio-enabled modes currently query both the default sink and source; missing
or unusable defaults can prevent recording even when only one is needed.

### Frame rate, quality and files

- **30 or 60 FPS**; 60 FPS increases processing and storage demands.
- **Normal or High** quality: H.264 CRF 28 or 23, respectively, with the
  `ultrafast` encoding preset. High usually produces larger files.
- **Save to → Change** selects a writable local folder. The default is
  `~/Videos/Recordings`; missing parent folders are created when preparing output.
- Files use `Recording-<date>_<time>-<unique suffix>.mkv`. Audio, when enabled,
  is AAC at 192 kb/s. Capture dimensions are rounded down to even pixels for
  encoding. There is no built-in pause, editor or alternate-format selector.

### Display aliases and preferences

Select a display and use **Rename display** to set a friendly name; saving a blank
name restores its default label. Aliases do not change system display names or
capture geometry. Monitor detection refreshes while idle. If a remembered display
is disconnected, the visible selection falls back to region without discarding
the remembered display.

Source, audio, FPS, quality, output folder and display aliases are saved in
`${XDG_CONFIG_HOME:-$HOME/.config}/screen-recorder/settings.json` (a non-absolute
`XDG_CONFIG_HOME` falls back to `~/.config` for preferences). Invalid or missing
settings fall back to safe defaults. Fresh defaults are region, Both audio,
30 FPS and High quality. Preferences and recordings survive updates/uninstall.

## Update or uninstall

Close the application before maintenance. To update an owned installation, run
`sh ./install.sh` from the newer trusted checkout with the same HOME and
XDG_DATA_HOME. Unmodified files are tracked by hashes and permissions; matching
reinstalls are idempotent. Do not edit the ownership manifest to bypass refusal.

To uninstall from the checkout:

```sh
sh ./uninstall.sh
```

Or, without the checkout:

```sh
sh "${XDG_DATA_HOME:-$HOME/.local/share}/screen-recorder/uninstall.sh"
```

Only matching installer-owned files are removed. Modified files and user-added
files are preserved; preferences and recordings are untouched. See
[INSTALL.md](INSTALL.md) for paths, recovery boundaries and collision rules.

## Limitations and issue reports

- X11 only; Wayland capture is unsupported. Mint Cinnamon is the target desktop,
  not a claim of certification across distributions or display configurations.
- Manual installation on a second computer and Cinnamon window grouping/pinning
  are **unverified**. Automated isolated tests do not establish either.
- The external REC helper requires supported unscaled X11 native window shapes
  and space outside the capture. The fallback recorder window/timer can appear
  in the video if placed inside the captured area.
- Installer checks do not validate a live display, audio devices, codecs or
  permissions. No shortcut, autostart or audio-routing configuration is provided.
- Installation uses atomic individual writes, not a multi-file transaction. Do
  not run concurrent install/uninstall operations. Interruptions require inspection.
- Forced shutdown, disk exhaustion or FFmpeg errors can leave incomplete output;
  an output filename alone is not proof of a successful save.

For an issue report, include application version (`1.0.0`, centrally defined in
`version.py`), Mint/Cinnamon and Python/FFmpeg versions, X11 session details,
selected options, steps to reproduce, and the exact status/error. Remove personal
paths and private audio/device details. Submit through the maintainer's confirmed
support channel when available; no GitHub URL is invented here.

## License

Original project code is licensed under [MIT](LICENSE), copyright 2026 Ezequiel
Gonzalez. The existing icon and copied helpers have unresolved provenance and
are **not covered by that grant**. [THIRD_PARTY.md](THIRD_PARTY.md) records those
gaps and the external dependencies; publication remains blocked until rights
and an existing origin are confirmed.
