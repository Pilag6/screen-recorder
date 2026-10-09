# Recording lifecycle

## Objective and constraints
Integrate existing countdown and REC subprocesses into GTK without modifying ~/.local/bin helpers or stable Bash. Preserve recording modes/options/output directory. No actual recordings, GUI/helper launches, permanent PipeWire changes or echo cancellation. User initialized Git and created baseline e30d859. Work on feat/recording-lifecycle; no commits without explicit user request.

## Tasks
- [x] T1 (verified, uncommitted): Implement asynchronous countdown cancellation, normalized geometry, conservative REC placement/fallback, and centralized owned-child cleanup with stale callback guards. Add safe mocked tests and run test-first plus static checks.
- [x] T2 (safe automated verification complete; native review unavailable): Independently verify safe automated tests, structural integration and unchanged external helpers. Record remaining limitations.

## Acceptance and checks
Countdown success gates FFmpeg; cancel produces no output. Main loop stays responsive during startup/shutdown. Geometry identical across capture and overlays, region-only border preserved. External REC must never knowingly enter capture including initial placement; use in-window timer when helper safety cannot be established. Stop/error/close reap owned children with bounded escalation and no stale starts. Tests mock processes/GTK/device commands, never record. Static AST checks and unittest suite; actual X11 visuals and audio capture remain pending user-authorized manual checks.

## Progress / evidence
Prior read-only analysis maps main.py, recorder.py, engine/recording.py and helpers. Indicator shows its window before positioning and cannot accept explicit coordinates/start time; conservative fallback is required. No test configuration detected. Git now available with baseline e30d859; delivery remains uncommitted local edits.

## Resolved blocker
Previous writer attempts did not dispatch. User initialized Git and created baseline e30d859; retry bounded writer now.

## Historical interruption and RED evidence
Writer mv0qfpxn-1-jeyz stopped after detecting concurrent edits in main.py and engine/recording.py. It added/updated tests/test_indicator_launcher.py and tests/test_main_lifecycle.py. RED: 21 tests, 3 errors (missing safe_position, missing finish_monitor_refresh, mock bookkeeping error). GREEN and static checks were pending at that interruption; current results below supersede this. Existing modifications were preserved; no overwrite or reset. Other PI processes exist but writer identity is unconfirmed.

## Ownership resolution
User explicitly confirmed nobody else is working on the project. Resume one writer from current snapshot, preserving existing work.

## Verified current snapshot
Safe independent verification: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v => 48 tests OK (0.461s); git diff --check => passed; AST parsing => 9 Python files passed. No recording/GUI/device commands executed. Indicator helper SHA256 matches pinned 331cef288c4168bbea54507717db68ed79a168b54f05cf407376a9b6a4a2303d. External REC executes unchanged helper via masked native-window measured placement; unsupported backend/scale/topology/helper changes fail closed to GTK timer. In-window timer may itself be recorded if GTK is inside capture. Native review started as review-f7aeebb6cbacc95d, but reviewer transport is unavailable because review-risk has no configured model; zero reviewers submitted, no approval/acknowledgement. STATUS still requires reviewer results. ASSESS unavailable due untracked-declaration handling, conservative high-risk fallback independent verifier already satisfied. Updating this progress document changes the live candidate; retained lineage remains bound to its frozen snapshot, not this final documentation. Existing backups and helper/Bash files untouched by this session. Historical RED21/3errors; cancelled continuation left current GREEN48; exact intermediate history unavailable. Scope includes main.py, engine/recording.py, new engine/lifecycle.py and engine/indicator_launcher.py plus mocked tests. No commit made (not requested).

## Final evidence and next step
Parent spot-check: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q => 48 tests OK (0.458s). Independent verifier found no severe observed blockers; 9 AST parses and diff check passed. Native review unavailable/not approved; do not claim closure. Real X11/GTK visual placement, FFmpeg/audio capture and media integrity remain untested by user constraint. Local implementation ready for authorized manual validation; no commits/push/publication. If native review is resumed, reconcile the current candidate/document change through fresh native authority inspection, not assumed reuse.
