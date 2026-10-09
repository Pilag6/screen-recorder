# Recording UI and UX

## Objective
Improve the GTK3 recorder presentation, success notifications and accessible recording minimization without changing process ownership.

## Constraints
Linux Mint Cinnamon X11; theme/accessibility; no heavy dependencies; preserve options, source refresh, countdown cancellation, REC/border safety, asynchronous stop/cleanup. No real recordings, external helper edits, PipeWire changes, engine/recording.py changes, or commits (explicit user instruction).

## Tasks
- [x] T1 — Refresh compact themed GTK layout and recording status.
- [x] T2 — Add explicit finalized-success metadata, native notification/folder action and once-per-session iconification, with test-first deterministic coverage.
- [x] T3 — Independently verify all tests, syntax, diff whitespace and edge cases; report runtime limitations.

## Acceptance and checks
All existing tests plus new notification/iconify and lifecycle success tests. Run python3 -m unittest discover -s tests -v, Python syntax checks and git diff --check. No real captures. Native desktop visuals/actions/WM behavior need manual validation; only safe non-recording UI checks if available.

## Progress
Exploration complete. main.py owns UI, engine/lifecycle.py owns final cleanup; output alone is not save success. Native notification backend optional and must never disrupt cleanup. Review switch reads on; inspect after implementation.

## Next step
T3 independent verification. T2 evidence: observed RED missing APIs/UI assertions, GREEN 63 tests; six-file AST and diff --check pass. Explicit immutable completion metadata; optional libnotify, escaped filename, capability-gated Gio folder action; close notification text-only; one iconify per session. T1 evidence: 48 tests pass, AST syntax and native GTK construction (420×473), defaults/source refresh/state controls passed without recording. Visual/large-text/screen-reader checks pending. Commit evidence: intentionally absent, user prohibits automatic commits.

## Final verification
Writer and independent verifier: 66 tests pass; parent spot check: 14 UI tests pass. AST syntax: all 13 project files pass (final recursive check also parsed 13 native frozen snapshots). git diff --check passes. Safe GTK no-capture construction: 420×473, defaults/options/source refresh and state controls pass. Test-first behavior observed by writer; layout has no meaningful RED.

## Refinement and limitations
Independent verification found minimized UI hides helper-failure REC fallback. Added elapsed REC window title and restore-to-stop tooltip; tests cover resets/stale and repeated callbacks. Title visibility is Cinnamon/window-list dependent; not continuously visible with all panel configurations. Native notification delivery/folder action, minimize/restore, visual/large-text/screen-reader validation remain manual. Optional Notify typelib/server absence safely omits notifications. Close-time notifications omit folder actions because callbacks require the live GTK loop.

## Review status
Native inspect/start selected six code/test files (task document excluded). Lineage review-0a0c5b3bacf78a71 is reviewing and unapproved: reviewer group launch blocked because review-risk has no configured model; zero reviewers submitted. Fresh STATUS reoffers results. Assessment unavailable due intended-untracked declaration; conservative high-risk independent verification performed. No configuration change or authority reset attempted.

## Outcome and next step
Implementation and automated verification complete; all requested edge cases covered with mocks, no actual captures. Pending: user-authorized native desktop/manual capture checks and reviewer configuration/review continuation. No commits or publishing. engine/recording.py, indicator launcher, external helper scripts and PipeWire unchanged.
