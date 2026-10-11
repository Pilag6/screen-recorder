# Screen Recorder v1.0.0

Final release preparation for the existing X11 recorder. **Not yet published:**
resource distribution rights and an existing repository origin must be confirmed
before publication. No public release URL is currently verified.

## Highlights

- GTK3 interface for region or single-monitor capture on Linux Mint Cinnamon/X11.
- Four audio modes: None, System, Microphone and Both.
- 30/60 FPS and Normal/High H.264 quality; Matroska (`.mkv`) output with optional
  AAC audio and a configurable local output folder.
- Persistent recording preferences and display aliases without changing system
  monitor names.
- Countdown, red capture border, guarded external REC timer with window/title
  fallback, and optional saved-file notifications.
- Session-owned recording/helper cleanup and a single application window per
  desktop session.
- User-local installation independent of the checkout, hash/mode ownership checks,
  and uninstall that preserves preferences, recordings and modified files.
- Central GTK-independent version metadata in `version.py`, included with the
  license and provenance notice in the portable installation payload.

These describe existing capabilities. Release preparation does not add recording
features, change the UI, or modify the bundled helper/icon bytes.

## Requirements and installation

Target: Linux Mint Cinnamon in an **X11 session**, with system Python 3.10+ at
`/usr/bin/python3`, PyGObject, GTK3/GdkX11, GdkPixbuf, Pango and Cairo. Required
commands: `ffmpeg`, `xrandr`, `slop`, `pactl`. FFmpeg needs X11 capture and libx264;
audio additionally needs Pulse input, AAC and an active PulseAudio or PipeWire-Pulse
session. libnotify support is optional.

From a trusted checkout, after arranging dependencies separately:

```sh
sh ./install.sh
"$HOME/.local/bin/screen-recorder-gtk"
```

The second command starts the application manually; installation never does so.
Do not use `sudo`. Read [README.md](README.md) for package guidance and recording
controls, and [INSTALL.md](INSTALL.md) for collision checks, paths, updates and
safe uninstall. Rerun the installer from the newer checkout to update an owned,
unmodified installation, with the same HOME/XDG_DATA_HOME.

## Limitations and verification boundary

- Wayland is unsupported; this is an X11 runtime.
- **Manual installation on a second computer remains unverified.** Isolated
  temporary-HOME/XDG tests are not evidence of a real second-computer install.
- **Cinnamon window grouping and pinning remain unverified.** The compatible
  desktop identity is retained, not asserted to have passed a manual desktop check.
- Automated preparation does not validate live display/audio operation, FFmpeg
  codecs or permissions. No real installation, recording or uninstall was
  performed for this release preparation.
- External REC visibility depends on unscaled X11 native shapes and available
  space outside capture. The fallback window/timer may be captured when restored
  inside the recording rectangle.
- Audio uses existing defaults, with no per-device selector or routing changes;
  all audio-enabled modes query both the default sink and source.
- No built-in pause, video editor, format selector, shortcut setup or autostart.
- Installer writes are individually atomic, not transactional across the payload.
  Concurrent maintenance and interrupted operations require care; modified or
  foreign files are refused/preserved rather than silently adopted.
- Forced process termination or storage/encoding errors can leave incomplete
  recordings. Wait for a confirmed saved-file status.

## Licensing and publication prerequisites

[LICENSE](LICENSE): MIT, copyright 2026 Ezequiel Gonzalez, **original project code
only**. The existing icon and three copied helpers are excluded from that grant
pending provenance and distribution-rights confirmation; unknown origin is not
proof that they are third-party. External dependencies keep their own licenses.

[THIRD_PARTY.md](THIRD_PARTY.md) lists the exact unresolved paths. Publication is
blocked until those rights are verified and an existing repository origin is
confirmed. Local v1.0.0 metadata does not establish publication or license clearance.
