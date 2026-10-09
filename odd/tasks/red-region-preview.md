# Red region preview

## Objective
Show a red outline while selecting a region and throughout countdown, preserving capture safety and session ownership.

## Constraints
No real recordings, commits, external helper/stable Bash/PipeWire edits. Only necessary slop argv change in recording.py. Preserve existing UI/recording behavior and current pycache changes.

## Tasks
- [x] T1 — red selection argv and optional owned region-only countdown border, removed/reaped before FFmpeg starts; test-first edge cases.
- [x] T2 — Independently verify tests, syntax, whitespace and ordering/safety; report manual limits.

## Acceptance
Red slop color supported by installed v7.6 --help. Countdown uses existing red border helper under distinct ownership; preview termination/reaping must finish before engine.start. Cancellation/close/startup failures clean it up; failed reaping prevents start. Missing/spawn-failed preview is optional. Monitor capture has no preview. Recording border remains post-start.

## Evidence
Read-only inspection of border helper found outside-region stroke, click-through and persistent GTK loop. No readiness acknowledgement; actual compositor rendering unverified. slop --help confirmed RGB/RGBA --color option. Tests must use mocks, never actual selection or capture.

## Next step
Implementation and independent verification complete. Writer observed RED (11 failures/1 error), GREEN 75 tests, four-file AST and git diff --check pass. No real captures or helper launches. Commits intentionally prohibited by user.

## Final evidence and limits
Independent verifier observed all 75 tests passing, 13 project Python AST parses and git diff --check passing. Parent inspected minimal behavior diff (14 added/changed source lines) and independently ran diff --check. Tests confirm preview spawn/terminate/wait precedes FFmpeg and recording border follows startup, cancel/close/countdown errors/authorization races and unreapable ownership. Native preflight reached untracked selection; review not run (previous reviewer configuration missing); assessment unavailable due untracked declaration, independent conservative high-risk verification performed. No recordings, real selection/helper execution or commits. Existing bytecode left untouched. Native compositor rendering/removal and continuously visible countdown border remain manual checks; preview optional when helper unavailable and has no readiness handshake.

## Next action
User can inspect UI; actual recording validation requires explicit permission. No source follow-up needed from automated verification. Native review/manual desktop checks pending.
