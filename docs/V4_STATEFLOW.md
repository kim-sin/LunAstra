> 4.2 update: current short-context, batch-wait and V1/V2 behavior is specified in [V4_2_PERFORMANCE.md](V4_2_PERFORMANCE.md). Older full-history/V1-only descriptions below apply to preserved legacy mode, not new capsule runs. Actual host verification remains separate.

# LunAstra 4.0 stateflow.1

## Contract and scope

This is an evolution of the recovered 3.2.0 fixed-seven-flow.1 source, not a new model. One existing root and six actual native children are retained. Native fork/identity/acknowledgment, s5/s6 read-only, scoped integration, evidence identity and user permission boundaries remain. Native tools are invoked by the host/root, never by the local Python helper. A deterministic control decision is not semantic approval.

## Components

| Component | Implemented behavior | Boundary |
|---|---|---|
| paths.py | One guarded relative identity and coverage comparison, Windows casefold | POSIX case remains distinct; not an OS sandbox |
| prepare.py | Typed original-source registry and expected-workspace preflight | Hashing does not claim model source reading; no invented input contents |
| requests.py | Atomic owner-bound immutable JSON blobs with size/digest checks | No arbitrary file reference, network or command evaluation |
| transport.py | Auto stage long literal JSON; bounded continued line/byte reads | Keeps safe Windows wrapper bound and host permission gates |
| controller.py | One crew-step returning legal next action, current reports, exact native calls and local counters | It does not choose implementation semantics, auto-vote or fabricate acknowledgment |
| blockers.py | Source-bound current/stale/unknown state, history, typed failure domain | Dependency change requires new evidence, never automatic PASS |
| flow.py | Batch native waits, safe opaque-path fallback, same-ticket stale-blocker recovery | Unknown native states/dispatches remain blocked, no replacement swarm |
| evidence.py | Opt-in deterministic execution reuse across display-only task changes | Requirements, dependencies, executable and declared environment remain bound; newest relevant failure wins |
| crew.py/hooks.py | Pre-certification changed-file coverage; idempotent review/completion with current evidence | Changed artifact or acceptance invalidates previous certification |
| research.py | Persistent bounded local job queue, independent verifier argv, scores with declared units, pause/drain, checkpoint resume | No authority promotion, trading, model API or process-kill path |
| install.py/removal.py | Separate state-v4, preservation and active-work guards | Hook approval remains manual in the actual app |

## Next-action flow

`PREPARE -> same six PLAN -> EXECUTE -> current checks -> same six REVIEW -> COMPLETE`.

Use `crew-step` after a native call wave. It returns a batch of real native calls (still unexecuted), current evidence-linked reports when a judgment is due, and only the appropriate kind of next action. An investigation has no patch to integrate. Semantic transition helpers still validate the exact six reports; a report formatting fix or stale-blocker recheck does not create six fresh models. Dependencies determine concurrency; no filler reports to pretend work is parallel.

A repeated review call reuses the existing review round only when artifact and acceptance identities match. A new finding is not waived just because bytes match. Tests are not omitted just to meet a target elapsed time.

## Preparation and input transport

`crew-start` accepts the existing goal, requirements, evidence_paths and output_paths plus expected_workspace, resources and mode. resources contains required_inputs, optional_inputs, outputs, protected and working. Required files exist before dispatch; outputs may be absent. A path classified incorrectly fails with specific context; the model must correct the real contract or locate the original in its permitted scope, not manufacture an input.

Long `--input-json` is validated and staged once by PreToolUse. Subsequent native command text contains an owner-bound sha256 reference. The original request remains private local state. A malformed/oversized blob, incorrect owner, mutated content or shell operator is rejected. UTF-8 readers stream selected lines through large files; very long/binary records use bounded byte windows. Callers follow continuation/EOF and do not equate one window with a full source read.

## Blockers and correctness

Failure domains: RESULT_INVALID, VERIFICATION_INCOMPLETE, INTERNAL_RECOVERABLE, EXTERNAL_WAIT, USER_REQUIRED. They are not a red/yellow/green guarantee that the actual calculation is valid. Source-linked results and their incomplete certificates are retained independently.

A blocked report records its observed dependency snapshot. A relevant new file or modified dependency makes it STALE. The same native-completed worker rechecks the same ticket; previous evidence is retained in history. Unchanged blockers are not blindly retried. Reassessment is bounded; unknown host capacity, unobserved acknowledgments and genuine access/authority limitations require an honest incomplete result, not a forged pass. An event advances eligible work; it is not a background service reading unrelated Drive/project files.

## Receipt reuse

Only reusable=true opts a deterministic check into reuse. Actual command, executable bytes, source/test/dependency snapshot, declared environment and locked requirements must match; logs must remain intact. Display-only design/purpose corrections may reuse execution while the resulting acceptance definition remains new and subject to independent review. Adding dependencies, changing inputs/requirements, modifying test code or environment requires new evidence. Non-deterministic or externally dependent checks should not opt in. No receipt can establish that the model chose adequate tests.

## Continuous local research

Only explicit mode=research starts this path. A finite request such as finishing one Teacher without training a Student stays finite. After the initial six-member planning/execution wave, the root configures project, bounded local workers (1..6), max/min direction and unit. The local processes are computation workers, not additional Luna sessions.

Each immutable job declares its compute argv, independent verify_argv, source dependencies, fresh working outputs, result_path, score_key and relevant environment keys. A queue nonce and recorded PID/stage bind ownership. Actual process exits and before/after hashes are checked; verifier failure or changed inputs cannot promote a score. Repeated enqueue with the same ID/spec does not rerun work; a different spec needs a new ID. Existing/overlapping outputs are preserved rather than overwritten. Failed trials remain and do not block unrelated jobs; downstream failed-dependency tasks remain pending until explicitly cancelled or replanned.

Use research-wait to block locally between result revisions; do not poll with repeated LLM turns. The supervisor stays ready for a new batch. Pause stops new dispatch and drains existing processes without killing them. A changed request/contract or Interrupt pauses new dispatch; it does not guess whether a new message is only a status question. After a genuine unchanged-scope acknowledgment, the root may explicitly resume.

At a checkpoint, pause/drain; run actual combined checks; obtain six current read-only reviews; research-resume takes decision plus six next tasks and reuses the roster. To finish: cancel only unwanted unstarted jobs with a reason, pause/drain, research-finish, then the ordinary final certification. Candidate selection is historical verifier evidence, not a project authority promotion. Revalidate source and result identity before promoting a candidate.

Limitations: it does not infer a successful new research direction, grant unlimited execution after host/account cutoff, adopt unconfirmed orphan processes, or guarantee optimal CPU usage. It reports experiment counts, phase, process stages and time since the last measured improvement. Strategic decisions remain the selected model's responsibility. Explicit queued dependencies must exist at enqueue time; enqueue dependent work after its required inputs are produced.

## Migration and release

Install into a new extracted directory, preserving originals. `state-v4` does not overwrite or migrate `state-v3`. A changed payload will refuse replacement when previous delegated/controller work is recorded unresolved. Do not delete state or kill healthy processes to force installation. Close/drain work using the matching old build. Approval in `/hooks` is a host step. Installation/hash checks do not start a model and are not proof of live connection.

The build does not change model, reasoning, API account, subscriptions, arbitrary AGENTS.md, other hooks or project files. The separate publication workflow requires a maintainer-triggered release commit and is not executed by installation. No GitHub/Drive write is part of this delivery.

## Evaluation limits

Software tests cover simulated native events and actual local processes/SQLite/files/worktrees/installers. They do not measure Astra vs Luna quality, live account usage or elapsed host runtime. A shorter serialized command or fewer state calls is a concrete protocol improvement, not a guaranteed end-to-end speedup. Real browser tests need a host-provided browser and permission; synthetic DOM checks cannot replace them. Preserve original benchmark outputs/logs and do not treat a mismatched grading input as a model score.
