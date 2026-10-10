# Custom monitor names

## Objective
Universal dynamic xrandr discovery with persistent user-owned names, independent of capture identity.

## Scope and constraints
main.py, preferences.py, focused tests, and minimal engine/recording.py + engine/lifecycle.py identity handling. Capture commands/behavior, PipeWire, helpers and Cinnamon unchanged. No real recordings, commits, merges, push or branch changes. Requested personal names initialized only in local preferences, never universal defaults. Default labels are Display N (real monitor ID). Alias keys use real IDs. Reserved region/monitor: source tokens escape reversibly and decode only at geometry resolution.

## Tasks
- [x] T1: Implement validated alias preferences, generic labels and idle-only GTK rename/reset; detection, naming, persistence, hotplug and identity regression tests.
- [x] T2: Initialize local preferences with the three requested aliases without overwriting other settings, with backup and atomic replacement.
- [x] T3: Run all tests, syntax checks, git diff --check and independent verification.
- [ ] T4 (blocked): Complete optional enabled native review; missing model configuration for review-risk prevents any reviewer launch. No native approval claimed.

## Acceptance
xrandr --listmonitors detection; logical names provide unique identity for all output counts. Normal connector=logical-name preferences remain compatible. Existing saved connector IDs differing from custom logical names require reselection; connector fallback intentionally avoided because it can capture the wrong display. Rename button/dialog is disabled and guarded outside idle, including after modal nested events. Blank alias resets default. Save failure preserves UI/preferences. Disconnected aliases and preferred source persist; visible selection falls back to Select region and restores when reconnected.

## Verification evidence
- Test-first RED observed by writer: initial 15 failures/8 errors; logical rows 4 failures/3 errors; namespace fixes included wrong-geometry and region-sentinel failures, final canonical IDs 7 failures/2 errors.
- Final writer and independent GREEN: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v, 158 tests passed.
- Independent syntax: all 16 working-tree Python files compiled in memory, .git excluded, no bytecode written by correct invocation.
- git diff --check passed (writer, verifier, parent spot check).
- Independent read-only review found no introduced defects after fixes. Real GTK interaction and physical hotplug not exercised; headless stubs/simulated xrandr used. No actual recording.
- Local settings: ~/.config/screen-recorder/settings.json contains eDP=Acer, DVI-I-3-2=Samsung arriba, DVI-I-2-1=LG derecha. Original backed up to settings.json.before-monitor-names.bak. Atomic initialization and JSON readback passed.
- Later external source changed eDP -> DVI-I-3-2. Read-only incident diagnosis found UI saves mocked and storage tests isolated; attribution unresolved, no external value restored. Aliases remain intact.
- Worker once mistyped bytecode suppression env variable; ignored .pyc observed, not deleted because preexisting caches existed.
- Native review started lineage review-a4035fc012736073 for an earlier candidate, zero reviewer outputs submitted; stopped on pi-host-relay-transport-failure (review-risk has no model). No retries, config changes or authority recovery. That lineage is not approval for final updated candidate. ASSESS unavailable due untracked declaration; high-risk fallback independent verification completed.
- No work-unit commits: explicitly forbidden by user.

## Next step
Manually verify Rename display dialog and physical connect/disconnect without recording. Native review remains pending until human configures review agent routing; inspect authority afresh before any continuation for current candidate.
