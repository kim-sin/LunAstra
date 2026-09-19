> 4.2 update: current short-context, batch-wait and V1/V2 behavior is specified in [V4_2_PERFORMANCE.md](V4_2_PERFORMANCE.md). Older full-history/V1-only descriptions below apply to preserved legacy mode, not new capsule runs. Actual host verification remains separate.

> Current version: 4.3.0. The original components below remain; [stateflow architecture](V4_STATEFLOW.md) describes the new control, resource, blocker and research paths.

# Architecture

## Fixed-seven build

New root sessions use the phase protocol in [FIXED_SEVEN.md](FIXED_SEVEN.md): one root plus six persistent native child IDs, reused through planning, execution and six-way final review. Slots 5 and 6 never implement. Each new assignment has its own evidence directory; repeated joins cannot reset a pre-write baseline. Current reports, native handbacks, test identity and frozen output bytes all gate completion.

The legacy dynamic team API below remains the underlying task/dispatch mechanism and supports old sessions. Its optional allocation policy is not the policy for new fixed-seven roots.

## Control model

The root Luna owns task interpretation, decomposition, implementation decisions, integration, and final verification. LunAstra does not call a separate model. Native Codex creates and schedules child agents.

Local code enforces structural state: task identity, dependency order, worker reservations, returned agent identifiers, workspace ownership, changed-file scope, check results, and completion records.

Hook flow:

```text
SessionStart / SubagentStart -> session and role state
UserPromptSubmit             -> current-turn context
PreToolUse                   -> spawn/edit/command guards and routing
PostToolUse                  -> observed result binding and lease updates
Stop / SubagentStop          -> verification and outstanding-work checks
PostCompact                  -> mark restoration pending
next context-capable event   -> restore guidance once
```

## Worker lifecycle

A plan is an acyclic set of named work units. The normal lifecycle is:

```text
pending -> reserved -> running -> returned -> accepted
```

A reservation is not a launched agent, a returned result is not accepted work, and an accepted patch does not prove the combined project passes its checks.

Child sessions are identified by native Codex IDs. The parent association is established from the reserved ticket and the actual spawn result. If the child starts before the parent receives the spawn result, the ticket remains unresolved until that result is observed. Unknown spawn responses keep the reservation occupied rather than creating an automatic replacement.

The underlying scheduler permits at most six simultaneous child jobs. Fixed-seven requires six distinct observed children per root and reuses them across rounds; dependencies can serialize a wave. Legacy sessions retain their configured dynamic parallel limit. Nested worker creation is blocked on the supported interception paths.

## Workspace isolation

Implementation tasks use detached Git worktrees created from a clean repository state. Repositories with unsupported state fall back to a single writer instead of fabricating isolation.

Recognized patch inputs are rewritten to the assigned checkout with the `PreToolUse` control fields required by Codex. Native shell hooks expose a `Bash` command string rather than an `exec_command.workdir`; joined implementation workers therefore run validated LunAstra helper commands whose subprocess cwd is bound to the assigned checkout.

Read-only workers use bounded source reads. They do not receive the implementation execution path.

Integration requires a current returned worker result, matching assignment identity, covered changed files, and a valid workspace baseline. The integration path rejects out-of-scope files, later changes to the original workspace, unexpected staged files, and file-mode drift. It checks patch applicability before applying and does not use force, reset, stash, automatic commits, or automatic worktree deletion.

Git worktrees are not an OS security boundary. Effective process permissions come from the launching host; LunAstra does not add an OS sandbox.

## Verification state

A check definition records its command, declared dependencies, expected-absent paths, executable identity, relevant environment, task identity, input snapshots, exit status, and log hashes. The most recent attempt is authoritative. Changed inputs, missing logs, malformed state, running checks, or failed exits invalidate success.

Long checks can run through a detached local controller. Status is derived from recorded controller state and execution results rather than PID existence. LunAstra does not terminate or restart unrelated user processes.

Observed source changes require current verification or an explicit partial/blocked completion record. Completion correction is bounded to avoid indefinite retries.

## Local state

The installer stores immutable releases, an installation record, hook backups, and runtime state under the Codex home. Runtime state is kept outside project repositories. Authentication files are not read by the extension.

Operational traces store identifiers, hashes, tool names, and status. Task descriptions, notes, check output, and patches may contain project data and remain local; they are excluded from release packaging.

## Installation and connection boundary

The CLI version probe is advisory. A copied helper must pass a local import/identity check before hook definitions change. Actual hook observations are recorded separately, keyed by immutable installed package location and hashed session identity. They contain event types and bounded call hashes, never raw prompts or commands. Doctor reads them through a read-only SQLite connection and does not run task checks.

Observation writes are not part of the task allow/deny decision. Their database lock wait is limited to 50 ms; they do not inherit the task store's longer timeout. A diagnostic failure emits a warning without changing the original guard result. Observations are historical, unauthenticated local metadata; they cannot certify an active host, complete delegation, model quality or an OS sandbox.
