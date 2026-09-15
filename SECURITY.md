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
