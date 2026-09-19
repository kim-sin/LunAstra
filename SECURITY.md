# Security

## Execution boundary

LunAstra installs local Codex lifecycle hooks. Review their commands in Codex before trusting them. Hook commands run with the privileges and execution context provided by the host. LunAstra does not create an OS sandbox or independently approve commands.

The Python helper also launches local subprocesses for Git workspaces, explicitly supplied verification commands and worker execution. A process inherits the permissions of the process that starts it. Do not assume that every subprocess receives a separate Codex approval prompt. Keep native Codex sandbox and approval controls enabled and review unfamiliar repositories before running their tests.

Worktrees separate repository changes; they do not prevent a command from accessing absolute paths or making network requests allowed by the host. Read-only worker restrictions cover recognized helper/tool paths, not every possible host capability or a hostile local process.

## Data and credentials

The extension does not contain a model API client, telemetry uploader or automatic repository publisher. Its own orchestration code makes no network requests. User-supplied commands and Git filters may have their own network behavior; the workspace preparation path refuses configured checkout filters.

Installation does not modify `config.toml`, `auth.json`, `AGENTS.md`, model selection, reasoning settings or unrelated hook handlers. It backs up the hook definitions it changes. Installation records contain local paths. Connection diagnostics record package location, hashed session/call identity, model, event categories and times; they omit raw prompts, command text and transcript paths. These observations are not authenticated host attestations. Runtime databases, notes, task descriptions, verification logs, patches and worktree copies can contain private project data.

`unregister` disables owned hooks but retains data. Explicit `purge` removes owned local data only after confirmation and an idle-state check. See [REMOVAL.md](docs/REMOVAL.md). External project files, downloaded archives, OS backups and external Git administrative records are not erased by purge.

## Release hygiene

The build and archive verifier both enforce a public file allowlist and scan common credential formats. Source archives exclude runtime state and generated manifests. A checksum detects accidental content changes; it does not authenticate the publisher. Review the source and the release origin. No finite scanner detects all possible secrets.

## Reporting

Use a minimal synthetic reproduction. Do not post credentials, private source, user paths, transcripts or runtime databases. When the repository owner enables GitHub private vulnerability reporting, use that channel for sensitive reports. Otherwise request a private contact without disclosing the vulnerability publicly.

## Fixed-seven state

Crew contracts, per-round decisions, reports, staged JSON inputs, artifact fingerprints and archived handbacks are stored locally and may contain private project data. A file hash is an identity check, not a guarantee that a model interpretation is correct. Earlier evidence contexts are retained when a native worker is reused; active or unresolved checks cannot be discarded through a phase transition.

Exactly seven sessions refers to the supported native protocol, not an OS security guarantee against malicious tools, a compromised process or an unsupported model host. Keep the host's approvals and sandbox protections enabled.


## Version 4 local research and request state

Large requests are private owner-scoped immutable JSON blobs, never eval/Invoke-Expression. Research argv are explicit local commands still subject to host/OS permissions; declaring output paths is cooperative ownership, not a sandbox against malicious scripts. Use trusted compute/verifier code and complete dependency/environment declarations. Research stores local logs, scores and hashes; neither snapshots nor a verifier's exit code are semantic proof. No network/model client is added by the queue. Do not expose the state directory as public evidence. Active/unknown worker records block replacement/removal rather than trigger a kill or fabricated completion.


## 4.1 model-gate diagnostics

The normal non-Luna event path is inert and creates no task state. A wrapper substring filter is a performance filter only; its false positives must still be rejected by the parsed-model gate. The hook interpreter avoids package bytecode writes on its early no-op path. Normal fast-path wrapper/interpreter reads are not a filesystem/security sandbox.

Only an operator's explicit `gate-trace` (or `doctor --trace-model-gate`) arms diagnostic writes. Captures live under the selected home's `luna-astra/model-gate-trace`, not its task state. Default bounds are 300 seconds and 128 events; hard bounds are 900 seconds and 512 events. Expiry/count is enforced transactionally before each record, and active capture markers are removed on the next observation after expiry. No background timer or server is started. A corrupt/locked diagnostic cannot change a task permission decision or activate another model.

Allowlisted fields are timestamps, supported event names, bounded model strings, per-capture HMAC session/agent hashes, role, classification, emitted-context/kernel/state flags, handler failure and build identity. No raw prompt, shell command, user file, token, credential or transcript path is copied. Exported report payloads omit filesystem paths; the local CLI displays the report path. Captures persist after stop/unregister and are not automatically exported or uploaded. They are local observations, not authenticated host attestations or proof that a model obeyed an expiration guard.

An applicability guard cannot retract an old developer-context injection. Pre-4.1 conversations require a clean new conversation for dependable non-Luna isolation. Do not fix this by deleting state, killing jobs, bypassing trust or changing models. See [model scope](docs/MODEL_SCOPE.md).

Operational hook scope (batchflow.3): only explicitly recognized edit, shell and native coordination tools are intercepted. Pure read/search and unrecognized/MCP tools are not claimed to be restricted by this package. Root shell is routed through registered checks/research and worker shell through its own joined helper, but registration is not sandboxing: arbitrary programs may access any path the native host permits. Keep host approvals and filesystem restrictions. Missing native acknowledgements are retained as unknown instead of blindly replaying a call.


Batchflow.4 native receipt recovery reads only an observed host transcript path and stores compact matching metadata/hashes. Host transcript integrity depends on the host and local filesystem; it is not a defense against an actor who can rewrite the user's session files. Exact input/call/session/file checks prevent accidental cross-session or stale acknowledgement reuse. Encrypted V2 routing checks do not decrypt or attest message semantics. Unknown calls never authorize replacement. Full certification streams bytes, rejects incomplete evidence, and still depends on a stable readable filesystem and host execution limits.
