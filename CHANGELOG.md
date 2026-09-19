# Changelog

## 4.3.0 batchflow.4

- Recover missing native PostToolUse acknowledgements from exact function-call/output pairs in a host-observed local transcript. Bind the call ID, original input hash, root session, turn when present, transcript identity and current ticket; assistant prose and generic error text cannot authorize another model.
- Expose root-only crew-reconcile and same-ticket crew-retry. Only the exact observed V1 pre-start capacity rejection can authorize a deliberate retry after its cause is addressed. Unknown/running calls and missing receipts remain protected; no timeout-based respawn.
- Match opaque V2 messages through unique currently emitted routing intents, not plaintext ticket searches inside encrypted fields. Retain native identity/actual-Luna join, model override, phase, scope and report guards. Recognize dotted multi_agent_v1/v2 tool namespaces.
- Separate bounded automatic workspace previews from complete streaming contract/certification scans. Remove the old per-file/aggregate byte caps from full scans and review fingerprints, preserve incomplete/read-error rejection, detect additions/removals/late changes and deduplicate overlapping dependency hashes.
- Preserve byte checks before compute, after compute and at verified ingest; remove the redundant verifier/ingest input pass and output pass. Validate parsed result bytes against the checked output, retaining rejection of verifier mutations and failed checks.
- Reuse no persistent stat-only content cache. Directory/read errors and late file mutations invalidate proof rather than generating partial success. Review snapshots retain an explicit one-million-entry memory guard.
- Use CRLF-aware Git attributes and canonicalize CMD bytes when building both archives; reject noncanonical launchers during archive verification. Keep the input checkout unchanged during packaging.
- Allow up to 300 seconds for terminal Stop/SubagentStop byte certification; ordinary tool hooks retain 10 seconds and Interrupt retains 3. Larger/unstable/network trees may still exceed host or resource limits and are not promised unlimited capacity.
- Remove the unused hook code-map path, preserve the fixed one-root/six-child roster, and retain account/model settings, unrelated hooks, original v3/v4 state and normal host permission review.

These are software changes. Transcript recovery requires the host to supply a readable, matching transcript with supported records. The opaque-message path validates routing, not encrypted message semantics. Live Desktop/IDE, actual model behavior, subscription usage and comparative output quality are not certified by fixture tests. See [correction details](docs/RELEASE_4.3.0.md).

## 4.3.0 batchflow.3

- Skip operational hooks for native read/search and other unhandled tools, both at matcher and early parsed-event boundaries. Model authorization remains unchanged.
- Share one thread-local SQLite connection per synchronous hook/controller operation, preserving transaction boundaries and nested rollback. Static schema setup no longer commits an outer transaction.
- Reconcile only the current session's recorded synchronous edit leases at Stop; missing Post is UNKNOWN, never PASS. Native calls without acknowledgements remain protected from duplicate spawning.
- Compact fixed-seven startup instructions and restore only a bounded, scoped recovery kernel plus saved member/phase pointers. Full notes/contracts remain available through context --recover without an unnecessary code-map scan. Legacy roles keep their original protocol.
- Require fixed-crew root shell work to use its own helper for registered checks/research. Structured edit tools enforce output scope. Apply the same worker shell restriction to direct-function aliases. Native host filesystem permissions remain essential; registered argv is not sandboxed by this project.
- Active local queue jobs wake the scheduler on completed futures instead of sleeping for one second after every wave. Idle queues retain bounded low-frequency polling; model-facing batch wake policy is unchanged.
- Hash readers check the opened file identity and change metadata, including pathname replacement and same-size/restored-mtime races on platforms exposing change time.
- No new CMD, model agent, service, runtime dependency, account-setting write, or destructive migration.

Limits: no live Windows/Desktop model run was performed as part of these local software changes. A missing native spawn acknowledgement is not safely inferable from a timeout; no automatic replacement is claimed. Whole-workspace scan budgets and explicit incomplete-coverage rejection remain. Unknown/MCP tools and registered shell programs are subject to host controls, not an OS sandbox implemented by hooks.

## 4.2.0 batchflow.2

- Correct V2 task-name grammar and require declared total capacity for the fixed roster, without changing Codex settings. Capacity includes the root; it is not a statement that all retained identities are simultaneously active.
- Reject incomplete before/after workspace observations for whole-change certification. Keep successful scoped test results as evidence, not falsely COMPLETE.
- Compare enqueue-time input/executable/environment bytes before starting a compute process; retain post-execution/verifier checks.
- Safely recover positively exited research controllers. Preserve live/unknown processes, interrupted results and pending jobs; never replay an interrupted job automatically.
- Require exact current full-report retrieval before issue/truncated-report decisions. Bound collective retrieval, invalidate receipts on report changes, and expose READ_REPORTS as the next action.
- Correct current-version publishing instructions. Existing fixed-seven, model isolation, batch notifications, protected data and host permission contracts remain.

## 4.2.0 batchflow.1

- Batch local research notifications with persistent delivery cursors; old errors/revision-only changes do not repeatedly wake the model.
- Replace job-pair output conflict checks with a path trie and iterative dependency traversal; use indexed ready selection, SQL counts and bounded status receipts.
- Share one byte-backed input fingerprint per identical enqueue input set; retain post-compute/verify/ingest actual-byte checks.
- Remove per-prompt and read-only-crew duplicate workspace scans and automatic maps; retain root final observation and writer baselines.
- New fixed-seven runs use short-context assignments with first-member actual-model handshake; legacy crews retain full context.
- Add V1/V2 spawn/reuse/wait/status/identity adapters and stale observation protection without fabricated runtime IDs.
- Return compact finding digests with explicit full-read paths; preserve all source-linked reports and semantic review.
- Require a fresh trusted current-turn scope in conditional prompt lifetime text.
- See docs/V4_2_PERFORMANCE.md for limits and migration; software tests do not certify live model speed or quality.

## 4.1.0 model-scope.1

- Scope every newly injected protocol to its observed Luna activation, turn and role; place the inactive-on-model-change/unregister rule before any crew obligation.
- Use one stdlib-only parsed-model gate before task imports and inside hooks. Non-Luna, missing, malformed and unknown models produce inert output.
- Treat bare `gpt-reserve` as UNKNOWN: the current evidence does not prove a Luna-only host discriminator. Explicit `gpt-<version>-luna...` variants remain supported. This supersedes older Reserve-admission entries below.
- Provide explicitly armed, time/count-bounded model-gate traces with per-capture hashed session identities and no prompt, command, file-content or credential capture.
- Distinguish owned hook registration, accepted events, emitted kernel and last-recorded crew state from actual host/model compliance.
- Expose an optional isolated installation target; do not launch/reroute Desktop/IDE or copy account/config files.
- Warn that unregister disables future owned injections but cannot retract old conversation context. Preserve v3/v4 state, unrelated hooks, releases, jobs and all fixed-seven/stateflow behavior.
- Add model/no-op/lifetime/diagnostic/installer lifecycle regressions. Actual Desktop/IDE switching remains a separate manual acceptance, not a claim from synthetic tests.

## 4.0.0 stateflow.1

- Add preflight resource roles and expected workspace validation before native dispatch.
- Unify path identities used by output coverage, evidence and Stop guards.
- Stage large literal JSON automatically as owner-bound content-addressed blobs.
- Add bounded streaming line/byte reads and distinct source diagnostics.
- Batch native waits with safe singleton fallback on ambiguous host identity.
- Add crew-step with current reports and legal state routing, without semantic auto-approval.
- Reassess dependency-stale blocked reports through the same completed native member and ticket.
- Separate blocker domains and preserve old report history; stale is not success.
- Reuse opt-in deterministic execution receipts only under unchanged semantic/source/environment identity.
- Reuse matching final review/completion; catch uncovered changed paths before certification.
- Add explicit persistent local research queue, verifier records, pause/drain and checkpoint resumption.
- Preserve 3.x state and refuse upgrades/removal while recorded work is unresolved.
- Add stateflow/security/local subprocess regressions and documented live-host limitations.

## 3.2.0 fixed-seven-flow.1

- Repair premature parent Stop and worker-specific report recovery.
- Drive native waits and same-member recovery without replacing the six IDs.
- Bind native wait observations to the current round and dispatch attempt.
- Preserve accounts, model settings, original evidence and interrupted work.
- See [continuation repair](docs/FLOW_FIX.md) for behavior and verification limits.

## 3.2.0 fixed-seven-stability.2

- Preserve automatic Luna activation and one lead plus six persistent workers.
- Canonicalize merge-lock identity before acquiring a filesystem lock.
- Reject symlink roots before resolving their spelling.
- Normalize test-process temporary roots while retaining symlink rejection.
- Pin Git newline semantics inside inherited-filter test fixtures.
- Exclude obsolete staging patch/workflow files from the distribution.
- Close SQLite connections on setup failures as well as body failures.
- Keep live Codex connectivity and model quality separate from software tests.

## 3.2.0 fixed-seven-publication.1

- Correct inactive inherited-filter handling without running active checkout filters.
- Normalize snapshot and worker alias paths; retain symlink and ownership guards.
- Make zero-time indexing deterministic and test-child cleanup wait for real exit.
- Exercise Windows launchers and permission changes instead of skipping them.
- Include checksum-pinned 420px artwork and clarify observed activation.
- Gate maintainer-requested preview releases on the complete hosted CI matrix.

## 3.2.0 fixed-seven

- Add a seven-session contract: one root and six persistent native Luna children, reused across plan, execution and final review.
- Require actual native identities and send acknowledgements; refuse replacement or nested workers.
- Preserve two non-implementing reviewers and require six source-linked final reports.
- Bind completion to current acceptance checks, locked requirements and artifact/input bytes.
- Preserve previous assignment evidence, make repeated joins idempotent and keep active jobs.
- Add phase-specific edit routing, same-ID repair and bounded Windows JSON staging.
- Retain old dynamic sessions and original safety tests as migration coverage.
- Add installed shell/CLI, actual Git integration, retry, corruption, capacity and stale-evidence regressions.
- Keep software-test success separate from live host execution and Astra Max quality comparisons.

## 3.2.0 installation compatibility

- Remove the PATH CLI version cutoff; CLI provenance is diagnostic, not active-host identity.
- Treat direct root feature settings as advisory because profiles and policy can differ.
- Check the installed helper before changing hooks; preserve the prior installation on startup failure.
- Separate installation integrity from current-payload hook observations with a read-only doctor.
- Exclude prior payload observations and refresh instructions on same-version updates.
- Match observation pairs by turn and call identity; never store raw prompts or shell commands in connection records.
- Select a usable Windows Python interpreter before executing installation/removal once.
- Preserve normal Codex home behavior for an empty environment override and improve failure guidance.

## 3.2.0 publication maintenance

- Add CLI version diagnostics and stable-host startup-fallback regressions (the original version gate is removed by installation compatibility maintenance).
- Report unknown, old, preview and unreviewed hosts separately from installation success.
- Add explicit owned-data removal with confirmation, activity and ownership guards.
- Separate repository-source archives from manifest-bearing release archives.
- Apply public-file and credential checks during archive verification as well as building.
- Make release validation reject skipped/expected-failure tests; pin CI actions and test dependencies.
- Document process permissions, private runtime data, cleanup, first-use checks and publishing.


## 3.2.0 — 2026-09-12

### Added

- Bounded Luna worker planning with native child-agent binding and a six-worker concurrency ceiling.
- Isolated Git workspaces for implementation tasks, with checked patch integration and single-writer fallback.
- Verification records for command identity, declared inputs, environment, exit status, and logs.
- Long-check tracking, compaction recovery, pending-plan revision, bounded source reads, and deterministic source archives.
- Public evaluation tooling for stock-Luna and LunAstra comparisons.

### Fixed

- Native child sessions are bound to the parent reservation and actual spawn result instead of treating the child session as its own parent.
- `PreToolUse` rewrites include the `permissionDecision: allow` field required by Codex.
- Worker command routing follows the native `Bash` + `command` hook contract and executes approved helper commands from the assigned checkout.
- Windows helper arguments preserve literal JSON and quoting without using `Invoke-Expression` or changing execution policy.
- Host-selected Luna Reserve sessions are recognized without changing model selection.
- Compaction recovery uses supported hook events instead of unsupported `PostCompact` context output.
- Stale evidence, malformed controller state, hidden staged changes, file-mode drift, and duplicate JSON keys no longer pass verification paths.
- Installation diagnostics return nonzero status for mismatched payloads or hook definitions.

### Changed

- Public documentation and installer diagnostics are English-only.
- Release packaging uses an allowlist, deterministic timestamps, content hashes, and archive path validation.
- Non-Luna events retain the lightweight prefilter path.

## 3.1.0

- Added a lightweight installed-hook prefilter for ordinary non-Luna events.
- Retained exact model validation inside the Python helper.
- Added regression coverage for the non-Luna fast path.

## 3.0.0

- Rebuilt the project around a Luna-led transactional work plan, bounded native delegation, worktree isolation, checked integration, verification records, and source-only distribution.

## 2.x — legacy pre-public prototype line

- No authoritative detailed 2.x release notes/artifacts are retained in the current repository; earlier changes are not invented.

## 1.x — legacy pre-public prototype line

- No authoritative detailed 1.x release notes/artifacts are retained in the current repository; earlier changes are not invented.
