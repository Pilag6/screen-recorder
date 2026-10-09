# Persistent user preferences

## Objective and scope
Persist source connector ID, audio mode, FPS, and quality in an XDG-compatible JSON file. Restore on window construction; save on user selection, never require recording. Keep storage independent of GTK. Preserve lifecycle, overlays, notifications, single instance, launcher, Bash helpers, PipeWire and shortcuts.

## Decisions and constraints
Use $XDG_CONFIG_HOME/screen-recorder/settings.json for absolute XDG paths, otherwise ~/.config/screen-recorder/settings.json. Create directories only on save. Validate fields independently; ignore unsupported versions safely. Retain preferred monitor while showing region fallback when absent; explicit user selection replaces preference. Do not save programmatic restoration/rebuilds. No actual recordings. No commits, staging, publishing or branch changes without user approval.

## Tasks
- [x] T1 (complete): Implement isolated persistence and GTK integration with test-first loading, saving, validation, immediate-change and monitor-fallback tests.
- [x] T2 (complete): Independently run full unittest suite, Python syntax checks, git diff --check and scoped regression inspection.
- [ ] T4 (blocked): Complete native review after review-risk model routing is configured.

- [x] T3 (complete): Add GTK header with assets/screen-recorder-icon.png on left, centered title and native minimize/close buttons on right; preserve lifecycle and add headless tests.

## Added user scope
User requests header icon, centered title and right-side minimize/close buttons. Asset is pre-existing untracked user content; do not modify it. Reopen T1 for explicit already-active fallback click regression discovered by independent verification. Complete T3 before final T2 verification.

## Acceptance and checks
Missing, malformed, outdated or unreadable configuration cannot block startup; write failures cannot block controls. Restore all valid values, use region for disconnected sources. Automated checks must be isolated from real user configuration, devices and recording.

## Evidence and progress
Architecture explored read-only. Working tree initially clean. main.py radio groups currently lack selection callbacks; source groups rebuild after asynchronous xrandr detection. Test suite uses unittest and headless GTK stubs. RDD mode on. Commits explicitly forbidden by user; no work-unit commits created.

## T1 evidence
Worker observed RED (missing storage module and six GTK preference failures), then GREEN: 12 storage tests, 28 GTK/lifecycle tests, 101 full-suite tests. Regression test caught retiring-radio teardown saves; callbacks now disconnect before rebuild. Syntax compilation passed for 15 Python files; diff whitespace check passed. No recording or commits. Native ASSESS unassessable due to undeclared untracked files; independent verification required.

## Next step
Independent full verification and native review preflight. Commit remains skipped per explicit user constraint.

## T1 correction evidence
Observed regression RED (no save for explicit already-active region click) and GREEN: 31 headless GTK/lifecycle tests pass. Guarded clicked handler avoids duplicate saves and is disconnected on rebuild. Diff check passed; full suite pending after header.

## T3 evidence
Native Gtk.HeaderBar configured with centered title, left module-relative 28px PNG, :minimize,close native controls. Missing/corrupt/unreadable icon safely optional. Header tests observed RED then GREEN. Full suite 107 passed; 15 Python files compiled; diff check passed. Actual GdkPixbuf decode/scaling passed (1254px to 28px). Real display visual check unavailable (no Xvfb); no app or recordings launched.

## Final verification and blocker
Independent verifier: 107 tests pass, 15 Python sources compile in memory, git diff --check passes; parent spot-check diff check also passed. Git status listings unchanged across verification. No concrete remaining defects. Visual/native GTK display verification not run; Xvfb unavailable. No recordings or commits.
Native review lineage review-8c027710e4e7b019 created for final five-path slice. Reviewer group forecast acknowledged (4 runs), but zero reviewers prepared/submitted: pi-host-relay-transport-failure, reviewer-config-invalid, no model configured for review-risk. Fresh STATUS reconciled once and reoffers four slots; authority remains reviewing, not approved/consumed. Do not replay old bindings. Next action: configure missing reviewer model with user authorization, fresh STATUS, continue exact review; visually inspect header under Cinnamon without recording.
