# Self-contained recording helpers

## Objective
Bundle the three existing recording helpers unchanged and resolve them from the repository root, independently of cwd or ~/.local/bin.

## Scope and constraints
Only helpers/recording-{border,countdown,indicator}.py, engine/lifecycle.py, engine/indicator_launcher.py, focused tests, the existing inert GTK construction fixture and this task document. Preserve UI and recording behavior, REC checksum gate, external scripts, backups, launchers, shortcuts and audio configuration. No real recordings; no commits, merges, tags or pushes (explicit user constraint overrides work-unit commits).

## Tasks
- [x] T1 (complete): Copy exact helper bytes, change path constants and add deterministic regression tests (RED before implementation, GREEN afterwards).
- [x] T2 (complete; native review unavailable and manual checks pending): Repair the baseline GTK test fixture minimally; verify full suite, Python syntax and diff whitespace; audit portability and record remaining manual checks/native review outcome.

## Acceptance and verification
Helpers resolve through Path(__file__).resolve().parents[1] / 'helpers', exist inside the repository and do not depend on HOME/cwd. Copied bytes match external originals and indicator checksum remains unchanged. Full unittest suite, AST syntax checks for active Python files and git diff --check pass. No GUI/helper execution or recording is authorized. Launcher/shortcut end-to-end behavior remains a manual check.

## Progress
Read-only exploration complete; Git initially clean on feat/recording-lifecycle. Only three active path constants need changes. Existing desktop launcher uses user-specific paths and remains unchanged. Native review mode reports on.

T1 evidence: new regressions observed RED (5 lifecycle and 3 indicator assertion failures), then GREEN (38 lifecycle tests and 16 indicator tests). All helpers match original bytes; indicator SHA-256 pin unchanged. Syntax passed for 16 active files; diff whitespace passed. No commit by user instruction.

T2 investigation: candidate full suite 139 tests / 27 errors; archived HEAD 7fb8f33e193121d7dc3c89c4ee6463bf790ae142 full suite 133 tests / identical 27 errors. MainPreferencesTests fails in isolation because its inert Gtk.Image lacks new_from_icon_name (main.py:170); fixture also lacks IconSize.BUTTON. Both main.py and tests/test_main_lifecycle.py were unchanged. Minimal test-only fixture repair added to scope; no product behavior changes.

T2 evidence: minimal inert fixture update added Image.new_from_icon_name and IconSize.BUTTON. Existing 27 isolated errors observed RED, then all 27 isolated tests GREEN; full suite 139/139 passed. Independent verifier reran full suite (139 passed), AST syntax check (16 active files), git diff --check and byte comparisons (3/3 identical). Actual os.chdir/HOME import-and-reload checks passed 24 helper-path assertions, without GUI/subprocess execution. Parent spot check git diff --check passed.

Native review: inspect included the three new helpers and excluded this task document. START could not complete: stale_target_identity; automatic status reconciliation failed schema-incompatible (lineage_created false). ASSESS with nativeReviewOutcome unavailable was unassessable and required independent verification; that verification passed as above. No native approval is claimed. No review retry or authority maintenance performed.

Generated artifact cleanup: two tracked engine/__pycache__ files were regenerated during work despite initially clean Git. Restored their exact HEAD bytes; final status contains only five tracked source/test changes, three new helpers and this document. No backup removed and no commit made.

Portability audit: no hard-coded user/project path remains in active product helper resolution. main.before-audio.py:25 retains a backup-only external border path, untouched. External .desktop launcher pins user-specific executable/icon paths; screen-recorder-gtk assumes $HOME/work/screen-recorder and /usr/bin/python3, unchanged. Installation still requires GTK3/PyGObject, Cairo, X11, FFmpeg capture/codecs, xrandr, slop and Pulse-compatible audio/pactl. REC requires supported unscaled X11 native shape behavior. Preferences/output defaults based on HOME remain intentional.

## Next step
Manual testing with approval: python3 main.py, gtk-launch screen-recorder and Ctrl+Super+R; monitor/region capture, all four audio modes, 30/60 FPS and Normal/High quality, border/countdown, REC timer, minimization, notifications, single-instance behavior, persistence and configured output folder. No real recordings or GUI/helper launches were performed. Native review remains unavailable; investigate separately if desired. Changes are uncommitted as requested.
