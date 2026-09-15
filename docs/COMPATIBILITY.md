# Codex compatibility

LunAstra 3.2.0 is tested against the public Codex hook and multi-agent interfaces. Compatibility tests pin exact upstream schema bytes so changes in Codex can be reviewed explicitly instead of being silently accepted.

## Fixed-seven native requirements

This build requires six native child sessions in addition to the primary session, actual spawn IDs, and reusable `send_input` calls. The public V1 `send_input` input uses `target` (not `id`) and returns a `submission_id`; that acknowledgement must precede joining a new assignment. Unknown responses stay pending/unknown and do not trigger replacement spawns. Native `resume_agent` may only target an already-bound member.

The current documented `agents.max_concurrent_threads_per_session` capacity excludes the primary session. Runtime settings, account policy and availability can still differ. LunAstra does not edit that configuration; native capacity failure is reported rather than masked. Full-history forks are requested without a model or reasoning override. This does not override native `agents.default_subagent_model` or `agents.default_subagent_reasoning_effort`: the native spawn implementation applies those defaults even for a full-history fork. Review them before first use and before measuring a light-Luna run. The extension checks observed model identity but cannot certify effective effort from a hook schema that does not expose it. Existing root sessions keep their earlier mode; use a new conversation for fixed seven.

Additional primary references reviewed for the reusable-agent interface:

- [Native configuration resolution](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/handlers/multi_agents_common.rs)
- [Native send_input implementation](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/handlers/multi_agents/send_input.rs)
- [Native V1 tool specifications](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/handlers/multi_agents_spec.rs)
- [Hook support and payloads](https://learn.chatgpt.com/docs/hooks)
- [Native subagent configuration](https://learn.chatgpt.com/docs/agent-configuration/subagents)

These live references are separate from the unchanged pinned offline fixtures below. Synthetic contract coverage is not evidence of a run in the user's active native host.

## Host requirements and provenance

Installation is based on local prerequisites and file safety, not a Codex version cutoff. A CLI discovered on PATH may be unrelated to the engine used by the desktop app or IDE. The optional `--codex-bin PATH` selects a CLI for an advisory probe; it does not identify the currently running app. An older, preview, newer, missing or unqueryable CLI is reported without refusing installation.

Before changing hook definitions, the installer runs the copied helper's `help` command with the selected Python interpreter. This local startup check makes no model calls. It verifies the installed helper can import and report its identity; it does not test Codex or bypass hook trust.

Codex must deliver the lifecycle events used by the extension. Delegation also requires its native Luna V1 agent tools. Keep normal host approval controls enabled. A successful file installation does not prove those features are active. After reviewing `/hooks`, use a new Luna session and consult [SMOKE_TEST.md](SMOKE_TEST.md).

Codex 0.154.0 is an offline reference, not a minimum-version guarantee. Its child-session startup differs from newer revisions when a worker inherits history. The regression suite replays a child `UserPromptSubmit` or `PreToolUse` carrying `agent_id`, followed by the observed parent spawn result. A missing start event is not replaced with a guessed parent identity. Passing those synthetic cases is not a claim that every older host supports this contract.

Python 3.10+ is required. CI is configured for 3.10, 3.12 and 3.14; a configured job is not evidence it has run. Windows entrypoints try a usable `py -3` interpreter first and then `python` before running the requested operation once. They never retry a failed installation or removal with another interpreter.

Python 3.10 lacks the standard `tomllib` parser, so configuration inspection is labeled unavailable there. On newer Python, only root settings are read. Profiles, command-line settings and managed policy may override them. An explicit root `hooks=false` is a warning, not a reason to assume the active host is disabled. The extension does not change these settings. An empty `CODEX_HOME` uses the normal home-directory default, not the extracted source directory.

## Connection diagnostics

`CHECK.cmd` / `install.py doctor` reads the runtime database without initializing it or running task checks. Installation integrity, observed hook traffic and model-quality evaluation are separate results.

| State | Meaning |
| --- | --- |
| `WAITING_FOR_LUNA` | No runtime database has been created by Luna traffic. |
| `WAITING_FOR_CURRENT_RELEASE` | No observations match this installed payload and requested time window. |
| `EVENTS_WITHOUT_KERNEL` | Events were received, but current instructions were not observed in hook output. |
| `LUNA_EVENTS_OBSERVED` | This payload emitted its instructions in response to a Luna event. |
| `TOOL_CYCLE_OBSERVED` | This payload emitted instructions and handled matching before/after tool events in one session. |
| `HOOK_ERRORS_OBSERVED` | A hook input failed without a subsequent matched tool cycle in the same session. |
| `DIAGNOSTICS_UNREADABLE` | Runtime records could not be read safely. They are not treated as success. |

Observations are tied to the immutable installed package location. Updating within 3.2.0 refreshes instructions at the next supported event and starts a separate observation history. Previous data is retained. The latest 200 matching session records are summarized; truncation is reported. These are historical local observations, not authenticated host identity, proof that output was consumed, proof of a currently running session, or full delegation certification.

A failed hook invalidates the earlier matched-cycle flag for that session. Ordinary events do not clear the error; a new matching before/after tool cycle does. Error and capability timestamps are filtered separately, so a new heartbeat cannot make older evidence current.

For a scripted first-use check, `doctor --require-observed --since UNIX_TIMESTAMP` returns 3 until a current-payload kernel and matched tool cycle are observed after that timestamp. A normal doctor returns 2 for installation mismatches or unreadable/error observations, 1 when the diagnostic itself cannot complete, and 0 when local checks complete. Code 0 with a waiting state is not live verification.

## Upstream reference

The current compatibility review is pinned to `openai/codex` commit `4d205c7a4dc36b719679a0356a45b23133732265`.

Pinned contract files:

- `codex-rs/hooks/schema/generated/subagent-start.command.input.schema.json` — Git blob `2f6edd60387aee5af5573e3683702d94773e2dd1`
- `codex-rs/hooks/schema/generated/pre-tool-use.command.output.schema.json` — Git blob `6730b27fd4fc80f8075d64346a554a1cfc94470a`
- `codex-rs/hooks/src/engine/output_parser.rs` — semantic validation for `updatedInput` and `permissionDecision`
- `codex-rs/core/src/hook_runtime.rs` — native hook dispatch and child-session identity
- `codex-rs/core/src/tools/handlers/unified_exec/exec_command.rs` — native shell hook payload
- `codex-rs/core/src/tools/handlers/multi_agents/spawn.rs` — V1 worker spawn result
- `codex-rs/core/src/tools/handlers/multi_agents_spec.rs` — V1 multi-agent tool specification
- `codex-rs/models-manager/models.json` — GPT-5.6 Luna currently selects multi-agent V1

The generated JSON Schemas are stored under `tests/codex_contract` with their Apache-2.0 attribution. The additional `user-prompt-submit.command.input.schema.json` is pinned to stable tag `rust-v0.154.0`, Git blob `6a10a9f75c19720b0863d11d7d7d80f190e8eacd`. The contract suite also checks semantic restrictions that are enforced in the Rust parser but not expressible in those schema files.

## Assumptions

LunAstra relies on Codex exposing the lifecycle hooks and native child-agent tools used by the installed version. The extension does not enable disabled host features or bypass native permission review.

A compatible schema does not prove that a particular desktop or CLI build has the same feature flags enabled. `install.py doctor` reports installed payload and hook-definition state separately from observed runtime events.

## Updating the pin

When Codex changes relevant hook or multi-agent code:

1. Review the upstream diff for the referenced schemas and runtime paths.
2. Replace pinned schema files only when their bytes actually change.
3. Update the source revision and blob hashes in `tests/codex_contract/NOTICE.md`.
4. Add a regression for any behavior change.
5. Run the complete local suite and hosted CI before publishing a new LunAstra release.
