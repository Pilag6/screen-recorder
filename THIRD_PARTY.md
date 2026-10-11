# Resource provenance and dependency notices

**Publication is blocked until distribution rights for the incorporated
resources below are confirmed and an existing repository origin is verified.**
This notice records evidence gaps; it is not a license grant or legal clearance.

## License scope

[LICENSE](LICENSE) provides the MIT license, copyright 2026 Ezequiel Gonzalez,
for original project code only. It does **not** assign MIT to the unresolved
icon or copied helpers. Unknown origin is not proof that material is third-party,
unlicensed, or infringing; it also does not establish permission to distribute it.

## Incorporated resources requiring confirmation

| Repository path | Recorded evidence | Missing evidence |
|---|---|---|
| `assets/screen-recorder-icon.png` | Existing application icon, included in the portable payload | Creator, source, applicable license or permission, and required attribution |
| `helpers/recording-border.py` | Previously copied byte-for-byte from a local helper script | Authorship/original source and applicable license or permission |
| `helpers/recording-countdown.py` | Previously copied byte-for-byte from a local helper script | Authorship/original source and applicable license or permission |
| `helpers/recording-indicator.py` | Previously copied byte-for-byte from a local helper script; runtime execution is checksum-gated | Authorship/original source and applicable license or permission |

The copying history is documented in the repository task
`odd/tasks/self-contained-helpers.md` (development documentation, not included
in the installation payload). Matching local bytes establishes fidelity, not
independent provenance or rights.
The indicator's pinned SHA-256 is
`331cef288c4168bbea54507717db68ed79a168b54f05cf407376a9b6a4a2303d`.
The icon and helper bytes remain unchanged in this release preparation.

Before publication, record verifiable authorship and distribution permission
for each resource, including any required notices. If a resource is confirmed
as original work, document that evidence; if externally sourced, preserve its
actual license and attribution. Do not infer MIT from its presence in this tree.
Replacing unresolved material requires a separately authorized change, not a
silent relicensing of these files.

## External runtime dependencies

These are installed separately; the portable payload does not bundle them.
Their licenses are independent of the project's MIT license.

| Dependency | Role |
|---|---|
| Python | Application and installer runtime |
| PyGObject, GTK3/GDK, GdkPixbuf, GLib/Gio, Pango | Desktop UI, display access and integration |
| Pycairo/Cairo | Rendering and native window shapes |
| FFmpeg | X11 capture, H.264 encoding and optional AAC audio |
| XRandR tools (`xrandr`) | Logical monitor discovery |
| `slop` | Interactive region selection |
| PulseAudio tools (`pactl`) and PulseAudio or PipeWire-Pulse | Default audio-device discovery and capture server |
| libnotify (optional) | Recording-saved notifications |

Consult the license/copyright information supplied by your distribution for
these packages. FFmpeg licensing and codec availability depend on the build;
this notice does not assert a single license for all FFmpeg builds or grant
rights to redistribute dependency binaries.

## Publication status

No configured origin or verified public project URL is currently recorded.
Do not publish a source archive or installation payload as fully MIT-licensed
while the resource rights remain unresolved. Version metadata and local release
documentation are preparation, not evidence of a published GitHub release.
