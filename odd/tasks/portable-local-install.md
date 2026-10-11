# Portable user-local installation

## Objective
Install the Python GTK3 Screen Recorder independently of its Git checkout on Mint Cinnamon/Ubuntu X11, preserving application identity and runtime behavior.

## Scope and constraints
- Add root install.sh/uninstall.sh, bounded installation support, tests, and documentation.
- Preserve io.github.screenrecorder.ScreenRecorder, all engine modules, helpers, and assets.
- Use system Python and dependency guidance, no virtualenv/system package installation.
- Respect absolute XDG data paths and spaces; launcher under HOME/.local/bin.
- Refuse foreign destination files; owned manifests support repeat install and safe uninstall.
- Never remove configuration or recordings, alter shortcuts/audio, or record.
- Tests use isolated temporary HOME/XDG directories only. No activation in real HOME.
- Preserve pre-existing modifications to main.py and tests/test_main_lifecycle.py.
- User explicitly prohibits commits, merges, tags, and pushes; no work-unit commits.

## Tasks
- [x] T1 (done): Implement user-local scripts, ownership safeguards, dependency detection, documentation and test-first integration coverage.
- [x] T2 (done): Independently verify full Python suite, bash syntax, Python syntax, diff whitespace and isolated install/uninstall; address confirmed defects.

## Acceptance and checks
Source-independent launcher, stable desktop/application ID and existing icon; all runtime files; space-safe destinations; repeat install without duplication; fail safely on foreign files/symlinks; uninstall only owned unmodified files and preserve user data. Check missing dependencies without installing them. Verify with unittest discovery, bash -n, Python syntax compilation without repository bytecode, and git diff --check.

## Evidence
Exploration: runtime assets/helpers already resolve relative to application sources; Gtk.Application maintains session-bus singleton identity. Existing launcher/desktop are foreign and must not be overwritten.
T1: worker observed initial RED (missing implementation), plus a RED foreign-launcher marker regression; GREEN: 25 isolated installation tests passed. bash -n install.sh uninstall.sh and compile() of new Python files passed. Changes: install.sh, uninstall.sh, installation.py, tests/test_installation.py, INSTALL.md. Hash/mode manifest ownership, passive dependency probe, nonrecursive uninstall and desktop escaping implemented. T2 independent verification initially passed 188 tests but detected Gio rejection of percent-bearing executable paths. Worker added two real Gio RED regressions, corrected Desktop Exec to /bin/sh plus escaped launcher argument (not shell -c), and passed 27 installation tests. Final independent verification: 190 tests passed, zero failures/errors/skips; both real Gio parse/spawn regressions passed using harmless fixtures; 18 Python files compiled in memory; bash -n and git diff --check passed. Parent spot check: bash -n and git diff --check passed.
Native review remains pending/unavailable: lineage review-cd30689274f8992e created through host consent; grouped forecast authorized but launch failed before any reviewer or submission because review-risk has no configured model. Fresh STATUS reoffers four slots. No authority acknowledged, no configuration changed. ASSESS unavailable (explicit untracked scope required by native assessment); conservative high-risk fallback requires independent verification, already performed. Real desktop launch, real recordings and actual installation intentionally excluded.
No commits per explicit user constraint. Multi-file operations are nontransactional; concurrent modifications unsupported. Symlinked HOME/XDG ancestry deliberately rejected. The coherent installer plus safety tests/doc exceeds the advisory task line heuristic; no engine/UI changes.

## Next step
Await explicit user approval before any real installation/activation or deliberate resolution of existing foreign launcher/desktop collisions. Native review continuation is pending a human model-routing configuration decision, then fresh bound STATUS for review-cd30689274f8992e. No commit/publish operations.
