# Configurable recording output folder

## Objective
Add a Change button beside the output path, SELECT_FOLDER Gtk.FileChooserDialog, persisted directory and engine/session propagation. Default ~/Videos/Recordings. Notifications and Open folder must follow actual confirmed output file parent.

## Scope and constraints
Preserve lifecycle, single-instance, audio/source/FPS/quality, countdown/overlays/notifications. No stable Bash helpers, PipeWire, shortcuts or launcher changes. No actual recordings, commits, staging, branch changes or publication. Preserve baseline preferences/header. Preference load must not create directories. Missing output field in schema v1 retains backward-compatible default. Validate path types, directory/create permission and actual writability; errors nonfatal. Only accept changes when lifecycle is idle and not closed; disabled otherwise. Snapshot directory in immutable RecordingOptions and forward to engine; revalidate before spawning FFmpeg. Cancellation must keep no-spawn/no-directory early boundary.

## Tasks
- [x] T1 (complete): Add persisted output folder, chooser and idle sensitivity, options and engine propagation, graceful validation; test-first coverage across storage/UI/engine/lifecycle/notifications.
- [ ] T2 (pending; final checks skipped by latest user instruction): Independent full suite, in-memory syntax checks, git diff --check, scoped regression inspection and native review preflight.

## Acceptance and checks
Chooser cancel/destroy and acceptance errors retain old folder. Restore path and label from saved preferences. Engine filenames reside under selected directory; notification action uses actual saved directory even if preference differs. Tests use tempdirs, mock GTK/processes/devices; never start real recording or change home config. Full unittest suite and compile all Python sources; whitespace diff check. Real GTK display behavior checked only if safe available environment, otherwise explicitly pending.

## Evidence
Architecture explored read-only. Initial working tree clean. Engine currently hardcodes OUTPUT_DIR; lifecycle doesn't forward folder. Notification already follows stop's confirmed output path parent. Existing preferences schema v1 and radio/header baseline committed outside this turn. RDD enabled; previous native review blocked on missing reviewer model, don't mutate routing or recover authority automatically. No commits authorized.

## T1 evidence
Writer added shared syntax-only normalization and temporary write-probe preparation in recorder.py, output_dir to preferences/options, idle-only chooser with nested-loop guards and rollback on save failure, selected-path engine/lifecycle handoff. Notifications production code unchanged: actual saved-file parent already correct. 22 new tests; observed RED for missing preference support and close-state guard, then GREEN: 129 full tests. Focused counts preferences 15/UI 43/engine 16/lifecycle 35/notifications 7. All 15 Python sources compile in memory; diff check passes. No recordings or commits. Native ASSESS unassessable due undeclared untracked doc; requires independent verification.

## Next step
Independent verifier full checks and native review preflight. Real GTK chooser appearance remains unverified.

## Independent verification and correction
Verifier observed 129 passing tests, 15 syntax compilations and clean diff whitespace. Reopen T1 for chooser construction-time RuntimeError currently outside catch, and cleanup-error handling. Three tracked .pyc changed after initial baseline but before verifier; cause unproven. Parent inspected status/timestamps and .gitignore (ignores bytecode but files already tracked). Preserve these ambient binaries untouched; no restoration/deletion authorized. They are not source edits of this feature; native review candidate may include tracked ambient changes and must not be silently claimed source-only.

## Final user-requested small UI adjustment
Chooser construction/cleanup fixes observed RED then GREEN (47 focused, 133 full tests; 15 syntax compilations and whitespace checks passed before this adjustment). User then explicitly requested only Change button UI polish and pointer cursor, with no tests afterward. Parent changed main.py only: themed folder-open-symbolic icon, tooltip, existing pointer enter/leave handlers. No tests or syntax/diff checks run after this adjustment. Final independent verification/native review remains pending, not claimed complete. Three ambient tracked bytecode files preserved. Worker reported external index change; no git staging/commits issued by parent or worker. Next step only if user authorizes: final checks and review.
