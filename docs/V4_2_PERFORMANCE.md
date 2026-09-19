# LunAstra 4.2.0 / batchflow.3

> Historical 4.2 performance design record. The promoted public release is LunAstra 4.3.0 batchflow.3.

## Scope and defaults

4.2 retains the same root plus six native workers, source-linked reports, current-byte acceptance, no silent worker replacement and the 4.1 Luna-only gate. It changes notification, context and native wire handling, not account/model/reasoning settings. No external model API, telemetry uploader or project-specific S/G exception is added.

### Research batching

`research-wait --timeout 300` waits inside the local process. A successful individual job, revision or heartbeat is not itself a model wake. Default `wake_policy` is `{ "completed": 10, "min_interval": 30, "queue_low_water": 0, "improvement_absolute": null }`. The first wait counts terminal work since study creation; later waits use the previous delivery cursor. Ten new terminal jobs, a new failure, queue drain/dependency blockage, pause/finish, coalesced low queue or timeout returns control. Old failures do not continuously retrigger. Significant improvement wakes only when an explicit positive absolute threshold in the declared metric unit is set, after the coalescing interval. A timeout/empty queue is NOT successful project completion.

Use `research-policy` with literal input JSON to change only notification policy, not running process lifetime. `research-read JOB` retrieves the full stored job/receipt. `research-status` and wait results return counts and at most eight compact recent records, not every input context or log. Local jobs continue while the model handles a batch; pause drains without killing them.

The queue uses an indexed dependency relation, SQL counts/ready-job selection and a component trie plus iterative dependency traversal. It no longer performs all job-pair output comparisons or decodes every job for each claim/status poll. SQL aggregate counts still scale with queue size; this is not a claim of constant-time scheduling. The existing limit is 10,000 jobs and 256 additions per enqueue.

Equal input/executable/environment sets within an enqueue batch share one exact fingerprint record. It is NOT an immutable filesystem snapshot. Mutable files remain mutable, and real byte checks before calculation, after calculation, independent verification and result ingestion remain mandatory. Same size/mtime cannot certify unchanged input. Old queued jobs without shared fingerprints retain fresh pre-execution hashing. Nothing promotes best_verified_candidate to project authority automatically.

### Deferred observations and explicit maps

The root retains its last checked content baseline instead of scanning again at each prompt. New prompts never erase an unverified earlier change. Fixed read-only worker joins/handbacks use scope/review identities rather than each scanning the whole workspace. These observations explicitly say incomplete; source references and final review snapshots still verify bytes. Isolated writers retain their own baseline. Unreported/external edits must still be caught, so the root's final bounded observation and exact declared dependency checks remain. This is a safe reduction of repeated scans, NOT a stat-only cache or a complete filesystem sandbox.

Code maps are built through explicit `context`/`risk`, not automatically for every coding prompt or edit. Change-path hints are hints only, not proof that nothing else changed.

### Low-context Fixed Seven

New `crew-start` uses `native.context="capsule"` by default. V1 emits `fork_context:false`; V2 emits `fork_turns:"none"`. A short one-use assignment reference points to `crew-join`, which returns the full locked goal, requirements, decision, actual workspace, source/protection scopes and job. The root must capture all relevant user requirements; removing history must not omit a constraint. The same six remain independent; s5/s6 stay non-writing acceptance reviewers.

The first member of those SAME six is an identity handshake, not an extra probe. It must have an actual accepted Luna hook and join before the other five launch. A placeholder inferred from root defaults is insufficient. If the first member is non-Luna, has unknown identity or has an unresolved spawn receipt, stop extra dispatch and preserve its state. Do not spawn a replacement or force a different model/effort. Child reasoning effort is NOT independently measured when the host omits it. For an explicit compatibility reason, new runs can request `native.context="full"`; unprofiled 4.1 saved crews retain their old full-context behavior. Switching a setting cannot remove history already present in an existing worker.

`crew-step` returns bounded finding digests first, plus each complete report's hash and `crew-report-read SLOT`. Truncated or issue reports are flagged `detail_required_before_decision`; inspect the full report/source before deciding. `crew-step --details` returns a bounded batch of full original reports. Repeat that same command while `remaining_required_reports` is nonempty, or use `crew-report-read SLOT`. A receipt binds the exact report hash, round and plan; only full-content retrieval counts. A changed report invalidates the receipt. Receipts prove local retrieval/delivery, not model comprehension or downstream UI rendering. Digest text is not test evidence and does not automatically approve any transition. Native call payloads are returned once instead of being duplicated in dispatch metadata.

### V1/V2 native adapter

Choose `native.protocol` in `crew-start` from the CURRENT EXPOSED TOOL SCHEMA. Do not infer it from a model label, the default branch of an upstream repository or a different CLI found on PATH. Default v1 preserves earlier hosts. Never change the protocol of an existing bound roster to try to bypass an error.

| Boundary | V1 | V2 |
|---|---|---|
| First call | spawn_agent(message, fork_context) | spawn_agent(task_name, message, fork_turns) |
| Spawn result | observed agent_id | canonical task_name (not a UUID) |
| Reuse | send_input(target, message, interrupt=false) | followup_task(target, message) |
| Reuse acknowledgement | submission_id | successful empty native body |
| Wait | targets plus timeout_ms | timeout_ms only; mailbox result |
| Status | current wait status map | list_agents canonical names and statuses |
| Completion | report + checked handback + current root proof | same checks, not mailbox wake |

V2 uses the actual spawn-name acknowledgement plus a current assignment capability and a trusted actual SubagentStart hook to bind the observed worker runtime ID. It never derives a UUID from a path, nickname or successful prose. A host that exposes no required worker identity remains unsupported/pending, not fake-compatible. This correlation is an extension-level capability check, NOT cryptographic attestation of a host. Current-plan/dispatch-epoch checks reject stale observations. Unknown/error/changed duplicate receipts never create successful work. The V2 send_message mailbox tool is not substituted for a followup that must start a turn; interrupt/extra-worker commands stay blocked.

Reviewed primary reference blobs in openai/codex (not a statement about the user's installed Desktop):
- `codex-rs/core/src/tools/handlers/multi_agents_v2/spawn.rs`: `d7899c7a81a24b878158c5d2481a52b284ea2e89`
- `codex-rs/core/src/tools/handlers/multi_agents_v2/wait.rs`: `d2f92feb8d011bb468dcc1f81b0efc20e756179e`
- `codex-rs/core/src/tools/handlers/multi_agents_v2/message_tool.rs`: `e319a2018328ca20ff00e5d97a24cef782a91208`
- `codex-rs/core/src/tools/handlers/multi_agents_v2/list_agents.rs`: `669a994589d1e7de3dc65760536ddc662c37db94`
- ListedAgent at commit `fd346b8dbaa24573a0244bc917811849d27c4cf4` exposes name/status, not runtime UUID.

## Luna-only current-turn lease

Every injected protocol begins with the common applicability guard. Without a fresh trusted `LUNASTRA_TURN_SCOPE` in the current turn, past obligations are inactive. Quoted old markers are not activation. The extension's model gate still checks parsed event.model only; non-Luna/unknown/reserve inputs cannot activate task state. This text does not erase old context or prove a model will comply. Same-conversation switch/unregister behavior still needs a real host test.

## Migration and installation

Uses the existing `state-v4` directory with additive queue/native observation tables. `state-v3` and all old records remain. Existing queued work and old full-context crews are not relabeled as new short-context runs. Finish/drain active old work through its own build before updating; never kill or delete state to satisfy the installer. Do not mix extracted source versions.

Use the existing `INSTALL.cmd` after active work is settled, approve changed hooks in the actual host, and use a new Luna conversation. `CHECK.cmd` is a read-only installation/observation report. No new pile of mandatory CMD steps is added. Optional diagnostics and separate-home commands retain their 4.1 limitations. A separate home does not automatically route Desktop/IDE or copy account settings.

## What automated success does not prove

Local tests exercise real Python subprocesses/SQLite/files/installers and synthetic native hook payloads. They do not call Luna or Astra or operate the user's Windows Codex. No live task-speed/token-cost/quality/parity number is claimed. Preserve original settings when comparing 4.1/4.2; use identical input bytes, correctly bound workspaces and the same independent grader. Do not rank quality from test count or self-reported completion.

## batchflow.2 failure boundaries

**V2 capacity:** `native.capacity_total` is the observed-and-declared total limit of the actual host, including its root. The local contract requires at least 7 for the fixed roster. This is NOT a newly invented hook payload field, a setting setter or an independently authenticated host measurement. Do not derive it from a separate PATH CLI or assume repository defaults equal the running Desktop. Unknown/insufficient capacity stops before new dispatch with a concrete error. V1 does not require this field. The code does not evict native agents, silently use fewer than six or change concurrency settings. Upstream may unload idle V2 residents separately from active-turn limits, so “default 4 means only 4 identities can ever exist” is not a valid inference. This package conservatively requires declared capacity rather than relying on unverified eviction behavior. Fresh V2 names use ASCII lowercase, digits and underscores; returned canonical paths must match the current assignment.

**Whole-change coverage:** root REVIEW/COMPLETE and TESTED handbacks require both the retained baseline and the current bounded observation to be complete. Exceeding file/byte/time bounds, omitted large files or unreadable paths is an explicit `WORKSPACE_OBSERVATION_INCOMPLETE`, not success. No budget is silently enlarged. Preserve existing check receipts and the original baseline; do not delete files, suppress coverage or reset the baseline to hide unknown edits. A large workspace may require a genuinely isolated, explicitly authorized task workspace and new baseline; do not change the user's scope merely to obtain PASS. Read-only crew handbacks continue to use their assigned sources/final snapshots rather than claiming a full workspace scan.

**Controller recovery:** `research-start` and `research-pause` first inspect recovery eligibility; `research-recover` performs that step alone. Only a positively exited original controller, with no live or ambiguously launched direct job process, may be recovered to PAUSED. Age/heartbeat alone is never proof of death. Process creation identity distinguishes PID reuse where supported; permission/observation failures and malformed or cross-platform creation identities remain UNKNOWN. Interrupted jobs become preserved ERROR records, never verified results or automatic retries. Dependent jobs remain blocked; independently approved pending jobs can run after restart. Logs, outputs, old nonce and recovery evidence are retained. No process is killed. A launch with missing PID in its launch-intent window remains `ORPHAN_JOB_UNRESOLVED`; it needs inspection, not a duplicate launch. A process query is not a census of descendants and does not prove useful progress.

**Report decisions:** issue or truncated reports require full original retrieval before EXECUTE, REPAIR, final acceptance or fixed-crew integration/acceptance. Short complete clear digests do not force extra retrieval. The transition checks the current report bytes again inside its state transaction; old receipts cannot authorize changed reports. READ_REPORTS is a retrieval step, not another model crew or test rerun. A blocked report remains blocked even after it is read.

Software regression and local subprocess tests do not certify live Windows hooks, actual model effort, host capacity, model-switch compliance or end-to-end performance.

For an already-created V2 roster, `crew-capacity` accepts only `capacity_total` plus a concise `evidence` description of the actual host limit. It updates a local declared observation without changing protocol, phase, model settings, existing identities or active work. A lower observed capacity blocks further dispatch; it does not evict workers. This observation is not independent attestation. Never invent it to clear a guard.

Repeated waits do not immediately re-emit the same dead-controller notification for the same nonce. Explicit recovery remains available. Invalid/null new input-snapshot IDs are errors, not a reason to fall back to legacy unsnapshotted execution. If a progress record fails after Popen, the owning local thread still waits for that process rather than abandoning or terminating it.

## batchflow.3 runtime changes

Read/search events no longer enter the operational hooks. Supported edits, shell and native coordination tools still do; a classifier and normalized tool names share one small module. A single synchronous operation reuses its SQLite connection but never caches row values or shares the connection between threads. Connection disposal, outer rollback and nested savepoints are tested separately.

Active compute futures notify the controller immediately. The unchanged one-second idle poll is only for cross-process enqueue/pause/heartbeat observation, not a mandatory pause after a completed job. The ten-result model batch policy is unchanged.

Cold root instructions retain the full workflow in less text. Compaction uses a bounded recovery kernel and a short observed-six/phase summary; it does not resend a long goal or working note. Full stored context is recoverable on demand without automatically rebuilding a source map. A hook byte budget is not a guarantee about an unknown host tokenizer or lower configured context limit.

These are local control-path changes. End-to-end Luna/Astra quality, token use and real Windows process-start latency require an actual host run; local unit counts do not establish those properties.
