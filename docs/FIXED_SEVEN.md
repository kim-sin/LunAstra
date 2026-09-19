> 4.2 update: current short-context, batch-wait and V1/V2 behavior is specified in [V4_2_PERFORMANCE.md](V4_2_PERFORMANCE.md). Older full-history/V1-only descriptions below apply to preserved legacy mode, not new capsule runs. Actual host verification remains separate.

# Fixed-seven protocol

This document describes the **fixed-seven** contract retained in LunAstra **4.3.0**. It supersedes earlier dynamic 0-6 allocation for newly observed root sessions only. The original dynamic implementation remains for pre-upgrade sessions and migration tests.

## Contract and identity

There is one native root and exactly six native children, assigned persistent slots `s1` through `s6`. The initial native `spawn_agent` result supplies each real `agent_id`; later work uses native `send_input` with `target`, `message`, and `interrupt: false`. The supported acknowledgement has a `submission_id`. The helper never creates models itself.

Full-history forks start from the parent configuration, but native `agents.default_subagent_model` and `agents.default_subagent_reasoning_effort` can override it even for a full-history fork. LunAstra refuses model, reasoning, service-tier and custom-agent-type overrides in its own dispatches; it does not control native host defaults. Before dispatching a light-Luna comparison, review the effective parent and child settings in the host. Conflicting defaults require explicit user correction, not a hidden configuration rewrite. Child model identity is checked when observed; hook payloads alone do not attest the effective reasoning effort. Six slots must be observed before an execution phase is accepted. A native capacity limit is a blocker, not permission to claim a five-child run is fixed seven. The same six sessions are retained for successive phases and tasks within that root.

Do not close a crew member to free a slot. A host-supported resume may target only an existing bound ID. An unknown dispatch retains its reservation; retrying the same acknowledged call is idempotent. A new call may not duplicate an unresolved dispatch or replace its member.

## Phases

| Phase | Model responsibilities | Local gates |
| --- | --- | --- |
| `PLAN` | Six independent lenses: map, solution, alternative, counterexample, tests, deliverable/usability | Read-only recognized edits; current contract, six reports, real handbacks and current source references |
| `EXECUTE` | Six reused bounded jobs; root synthesis and implementation; `s5`/`s6` remain read-only | Assigned paths, dependency order, safe workspaces, current worker evidence and checked integration |
| `REVIEW` | All six inspect the combined artifact; `s5`/`s6` cover every locked requirement | Current successful root checks, frozen artifact/input/check dependencies, actual file references |
| `COMPLETE` | Root delivers the artifact and specific results | Six clear reports, current tested root finish, unchanged snapshot and no active/unresolved work |

A worker saying it is done is not acceptance. A clear report is a model claim with referenced bytes, not independent proof that every assertion is correct. Real test commands and the root's judgment remain necessary.

## Local helper sequence

The hook supplies `LOCAL_HELPER_COMMAND` and a session-bound argument array. Append commands to that exact prefix. The root derives the forms from the user's actual request; users should not need to fill them out.

1. `crew-start` with a task contract, then `crew-next`.
2. Perform the returned six native spawn calls. Each worker runs `crew-join TICKET`, inspects sources, writes a `crew-report` and finishes a checked handback.
3. Inspect `crew-state`, `crew-report-read SLOT`, and referenced sources. Call `crew-execute` with the chosen method and six current jobs.
4. Run `crew-next` and its same-ID native send calls. Integrate returned implementation with `team-integrate TASK_ID`, then `team-accept TASK_ID --review TEXT`.
5. Register meaningful root acceptance checks with `begin`; execute `run-all` or `start-check` and observe `jobs`.
6. Call `crew-review`, then `crew-next` to send six read-only review jobs to the same six IDs.
7. Resolve issues with `crew-repair`, targeted jobs, current tests and a new review. Retain correct work and the fixed roster.
8. `finish` the root evidence as `tested`, then `crew-complete`. Only now is a fixed-seven completion eligible.

### Contract (`crew-start` / `crew-revise`)

```json
{
  "goal": "Create the requested checked report",
  "requirements": ["The report totals reconcile with the source records"],
  "evidence_paths": ["input.csv"],
  "output_paths": ["report.txt"]
}
```

Relative paths must be narrow and non-control paths. Outputs can be absent initially; they must be covered by root acceptance checks later. Root check requirements must exactly match the locked list. Empty output scope is not a silent exemption; a research task can have a local report as its artifact.

### Execution (`crew-execute` / `crew-repair`)

Supply `decision` and `tasks`. There must be exactly six uniquely named jobs `s1` through `s6`. Each task contains `id`, `kind` (`investigate`, `implement`, or `verify`), `description`, `paths`, `depends_on`, `done_when`, and `why_parallel`. Use distinct, useful obligations, not six copies of a guess. Slots `s5` and `s6` may never implement. Implementation paths must be inside locked output scopes. Dependent or overlapping writes wait rather than racing.

### Report (`crew-report`)

```json
{
  "verdict": "clear",
  "summary": "The inspected total agrees with the source",
  "findings": ["No discrepancy was found within the assigned check"],
  "references": [{"path": "report.txt"}],
  "covers": [0]
}
```

This is a schema example, not a completed real check. Valid verdicts are `clear`, `issues`, and `blocked`. A reference is an existing regular file within the assigned scope, or a zero-based locked requirement index. Final review needs a real file reference, not only a requirement index. Slots `s5` and `s6` must cover every requirement during final review. Current `issues` or `blocked` reports cannot be accepted as a clean final result.

### Review and completion

`crew-review` and `crew-complete` accept only a `decision` string describing the root's evidence-based synthesis. Do not include arbitrary metadata or success flags.

### Bounded JSON on Windows

Use `--input-json` **before** the subcommand for literal JSON. Version 4 stages a long argument automatically in an owner-bound sha256 blob and rewrites only the transport. Do not make the model split it. `input-append` remains a compatibility fallback (1-1000 characters per chunk, 2 MiB total) for explicit older clients, not the preferred new flow. No content is evaluated as shell text.

## Recovery and revisions

`crew-state` returns phase, roster and short report summaries. Full reports remain available on demand. `context --recover` restores phase guidance without converting reservations into observed native executions.

Each assignment has a distinct flat evidence directory keyed by the worker and ticket. Repeated joins of the same ticket preserve its baseline and finish record. A later ticket cannot inherit an earlier test pass, and active check controllers prevent switching. Old evidence and worktree records are retained.

A new user message needs an explicit root decision. A changed goal, scope or requirement invalidates the contract: settle running work and call `crew-revise`; preserve earlier state and reuse existing members. For a status question or clarification with no changed requirement, `crew-continue` accepts a `decision` explaining that assessment and retains the current tickets, members, phase and active work. It never edits the locked requirements or discards a running job. The model must interpret that distinction correctly; there is no keyword-based guess that a message is safe to ignore. Hook continuations marked `LUNASTRA_CONTINUE:` are not a new goal. Plans may not erase active native calls or checks to clear a gate.

An unverified terminal handback stays unverified and frees no extra model slot; the same member is reused for repair after active work is settled. Missing native acknowledgements remain unresolved. Final stop feedback is bounded: once the continuation has been requested, unresolved work exits as explicitly `UNVERIFIED`, not an infinite hidden retry loop or fabricated success.

## Snapshot and resource boundaries

Final snapshots include bytes, file modes, directories and absent declared paths. Symlinks, special files and escapes are refused. Full byte snapshots stream without per-file or aggregate byte caps. An explicit 1,000,000-entry guard protects review memory. Exceeding resources or finding unreadable/changing paths is an error, never partial certification. Automatic previews retain separate small budgets. Work capsules and reports have separate size bounds to avoid flooding the root context.

Model concurrency, reasoning effort, model availability and usage accounting belong to the native host. LunAstra does not raise them. Fixed seven retains six sessions but does not force six simultaneous writes or busy-wait polling. Reusing sessions preserves work, but inherited context, dispatch and review still have a usage cost.

## Evidence scope

The bundled tests simulate native model-event payloads while executing real local helper processes, Git operations, file writes, checks and installer flows. They establish the exercised software properties. Live seven-session operation, light-Luna quality, throughput, usage savings and Astra Max parity require [separate real-task evaluation](../evals/PROTOCOL.md). No model quality claim is generated from synthetic tests.


Version 4 adds preflight resources, batched `crew-step`, stale-blocker reassessment and explicit local research. Read [stateflow details](V4_STATEFLOW.md); old examples remain low-level protocol references, not a requirement to call every diagnostic manually.
