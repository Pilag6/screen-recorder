# Recording lifecycle

## Objective and constraints
Integrate existing countdown and REC subprocesses into GTK without modifying ~/.local/bin helpers or stable Bash. Preserve recording modes/options/output directory. No actual recordings, GUI/helper launches, permanent PipeWire changes or echo cancellation. Workspace is not Git: no initialization or commits; commit evidence unavailable.

## Tasks
- [ ] T1 (pending, blocked by writer availability): Implement asynchronous countdown cancellation, normalized geometry, conservative REC placement/fallback, and centralized owned-child cleanup with stale callback guards. Add safe mocked tests and run test-first plus static checks.
- [ ] T2 (pending): Independently verify safe automated tests, structural integration and unchanged external helpers. Record remaining limitations.

## Acceptance and checks
Countdown success gates FFmpeg; cancel produces no output. Main loop stays responsive during startup/shutdown. Geometry identical across capture and overlays, region-only border preserved. External REC must never knowingly enter capture including initial placement; use in-window timer when helper safety cannot be established. Stop/error/close reap owned children with bounded escalation and no stale starts. Tests mock processes/GTK/device commands, never record. Static AST checks and unittest suite; actual X11 visuals and audio capture remain pending user-authorized manual checks.

## Progress / evidence
Prior read-only analysis maps main.py, recorder.py, engine/recording.py and helpers. Indicator shows its window before positioning and cannot accept explicit coordinates/start time; conservative fallback is required. No test configuration detected. Git absent; delivery remains local edits.

## Blocker
The bounded writer failed before dispatch: "Writer repository preparation was unavailable or its session/target changed." No Python implementation was performed. No native Agent or alternate configured worker is available. Do not initialize Git or bypass mandatory multi-file writer routing without resolving the environment.

## Next step
Restore an available bounded writer for this non-Git workspace, then resume T1. User may authorize Git initialization as an alternative, but none is assumed. Tests and runtime verification have not run. No commit without user request.
