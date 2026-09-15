# LunAstra 3.2.0 release notes

LunAstra 3.2.0 consolidates the worker-orchestration, workspace-isolation, evidence, recovery, and Codex compatibility work introduced across the 3.x line.

## Fixed-seven maintenance build

The version remains 3.2.0 and the runtime build marker is `fixed-seven-stability.2`. New root sessions require one root plus six persistent native Luna children. All six contribute to PLAN, EXECUTE and REVIEW; two slots never implement. Same-ID native send acknowledgements, per-assignment evidence, source-linked reports, snapshot-bound final review, targeted repair and bounded JSON staging are added. Legacy root sessions retain their earlier dynamic contract.

The goal includes light-Luna versus Astra Max evaluation. No actual model parity or usage-saving measurement is implied by this maintenance release.

## Hosted-CI and publishing maintenance

Unused inherited Git LFS settings no longer block ordinary worktree isolation. Active index/worktree filters and repository-local executable filters still refuse implicit execution, including during integration. Equivalent path spellings are normalized before fingerprint and child-identity comparisons. A zero-second indexing budget is deterministic. Test controllers finish before temporary-file cleanup; native Windows launcher and permission checks replace platform skips.

The approved artwork is displayed at 420 pixels and is pinned by checksum in both source and installable archives. The public tagline is "A moon dreaming of the stars." Existing-chat activation is conditional on observed hook loading, not a blanket guarantee.

This remains a **preview for live-host compatibility** until native seven-session first-use checks have been recorded. Hosted software CI, even when all matrix jobs pass, is not an Astra Max performance measurement.

## Native Codex integration

- Child workers are bound using the native child session ID, the reserved task ticket, and the parent spawn result.
- `PreToolUse` input rewrites include the required `permissionDecision: allow` control field.
- Shell routing follows the Codex `Bash` hook payload and does not assume that a native `workdir` field is exposed to hooks.
- Implementation workers execute validated helper argv from their assigned checkout. Read-only workers use bounded source reads and cannot invoke the implementation execution path.
- Luna V1 agent tool names and common JSON response wrappers are normalized before state transitions.
- Host-selected Luna Reserve is recognized without selecting or forcing that model route.
- Windows helper invocation uses explicit process arguments and refuses oversized command lines.

## Orchestration and verification

- The root Luna remains accountable for planning, integration, and final verification.
- Fixed-seven roots require exactly six persistent child sessions. Earlier dynamic sessions retain optional delegation capped at six.
- Active worker tasks cannot be silently replaced. Wholly undispatched plans may be revised while preserving history and launch limits.
- Git worktree integration rejects out-of-scope changes, hidden staged files, stale original files, and file-mode drift.
- Verification records reject malformed state, changed inputs, missing logs, failed exits, stale partial handbacks, and duplicate running checks.
- Long checks are tracked without terminating unrelated processes.
- Compaction recovery defers instruction restoration to a supported context-capable event.

## Installation and distribution

The installer is additive and content-addressed. It preserves existing model settings, reasoning effort, account files, unrelated hooks, runtime records, project files, and running processes. Hook changes require normal Codex review through `/hooks`.

The repository source ZIP excludes generated manifests. The installable ZIP contains the same source plus a SHA-256 manifest. Both builds are deterministic; the installable verifier rejects unsafe archive paths, symlinks, case collisions, malformed manifests, unexpected files, credentials and version mismatches.

Publication maintenance adds advisory CLI version probes (without a minimum-version installation gate), a copied-helper startup check, current-payload hook observation diagnostics, explicit owned-data removal, stable-host fallback regressions, pinned test dependencies and a Windows/Linux/macOS CI matrix. `UNREGISTER.cmd` retains data; `PURGE.cmd` requires explicit confirmation before removing it. Native Codex execution and hosted CI remain separate from local software-test results.

See [VALIDATION.md](VALIDATION.md) for software-check scope and [COMPATIBILITY.md](COMPATIBILITY.md) for the pinned upstream Codex contract used by the compatibility tests.

Same-version maintenance refreshes instructions when the installed package location changes. Windows launchers select a working Python interpreter before executing the requested operation once. The version remains 3.2.0; release fingerprints and archive checksums distinguish distributions.
