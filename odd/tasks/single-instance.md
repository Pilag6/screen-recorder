# Single-instance application

## Objective
Use native Gtk.Application session-bus uniqueness and restore the existing window on repeated launches without changing recording state.

## Scope and constraints
Only main.py and tests/test_main_lifecycle.py require behavior changes. Preserve asynchronous cleanup, all recording features, desktop launcher and wrapper. No actual recordings, helper/Bash/PipeWire edits, remote operations or commits. Artifacts remain English.

## Plan
- [x] T1: Implement stable application ID, lazy single-window activation and application-owned terminal shutdown; add regression tests with observed RED/GREEN.
- [x] T2: Independently verify full tests, all-file AST syntax, diff whitespace and lifecycle preservation.

## Routing and acceptance
T1 delegated: preparation for writing and two non-trivial files. T2 delegated: full-suite execution and independent verification. Repeated activation must restore/present the same window and retain engine/lifecycle identity and countdown/recording state. Close must wait for terminal cleanup, including failure handling.

## Checks
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v

All Python files parsed with ast.parse; git diff --check. No actual recordings or GUI launches. Real Cinnamon/session-bus smoke test remains manual.

## Progress
Implementation and independent verification complete; no launcher changes necessary. Stable ID io.github.screenrecorder.ScreenRecorder, lazy registration, restore-only activation, terminal application-owned quit. Activation while closing remains inert; cleanup_failed can restore recovery UI. Observed RED: five missing-application errors and two old-shutdown failures; GREEN: 80 full-suite tests passed. Independent verifier repeated 80 tests, 13 Python AST parses and git diff --check successfully. Parent spot check git diff --check passed. Diff 102 insertions/9 deletions across two source/test files. Delivery strategy ask-on-risk; no commits by explicit user instruction. RDD effective mode on; assessment unassessable/high until untracked selection. Native STATUS succeeded after sandbox approval, requesting intended-untracked selection for .codegraph/.gitignore and this task file; no review started or approval claimed. Engram mirror pending because runtime session identity is unavailable and attributed writes are forbidden.

## Next step
Resolve native review untracked-file selection. Manual Cinnamon two-process activation/focus smoke test remains pending; no GUI or recording tests were launched. No launcher/helper/Bash/PipeWire changes.
