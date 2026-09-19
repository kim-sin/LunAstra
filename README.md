# LunAstra

<p align="center">
  <img src="docs/assets/lunastra-hero.webp" width="420" alt="LunAstra: a robot and a cat watching the moon together" />
</p>

## Version history

**Latest: LunAstra 4.3.0 — batchflow.3**

| Version | Main changes |
|---|---|
| **4.3.0 — batchflow.3** | Removes unnecessary read/search hook work, reuses SQLite connections inside one control operation, shortens recovery context, removes fixed 1-second active-queue waits, strengthens file-identity/change detection, and keeps the fixed seven-member roster unchanged. |
| **4.2.0 — batchflow.2** | Fixes V2 task-name/capacity handling, incomplete workspace-scan certification, stale-input execution, dead research-controller recovery, required full-report reads, and release-version publishing instructions. |
| **4.2.0 — batchflow.1** | Adds batched research notifications, cheaper dependency/output indexing, shared input fingerprints, fewer duplicate workspace scans, short-context fixed-seven assignments, V1/V2 native adapters, compact report digests, and stricter current-turn scope checks. |
| **4.1.0 — model-scope.1** | Makes LunAstra activation explicitly Luna-only and turn/role scoped, centralizes model gating, keeps unknown/non-Luna models inert, adds bounded model-gate diagnostics, isolated-home helpers, and clearer unregister/context-lifetime rules. |
| **4.0.0 — stateflow.1** | Rebuilds orchestration around preflight resource validation, canonical path identity, staged large requests, bounded reads, batched native waits, crew-step, stale-blocker reassessment, safe receipt/review reuse, persistent local research queues, and v3/v4 state separation. |
| **3.2.0 — fixed-seven line** | Establishes one root + six persistent Luna children, same-ID reuse across planning/execution/review, two independent reviewers, source-linked reports, snapshot-bound completion, safer worktree integration, installation/compatibility hardening, and flow/stability/publication fixes. |
| **3.1.0** | Adds the lightweight installed-hook prefilter for ordinary non-Luna events while retaining exact model validation in Python. |
| **3.0.0** | Rebuilds the project around a Luna-led transactional work plan, bounded native delegation, worktree isolation, checked integration, verification records, and source-only distribution. |
| **2.x** | Legacy pre-public prototype line. No authoritative 2.x release notes/artifacts are retained in the current repository, so details are not reconstructed. |
| **1.x** | Legacy pre-public prototype line. No authoritative 1.x release notes/artifacts are retained in the current repository, so details are not reconstructed. |

**Full chronological details:** [CHANGELOG.md](CHANGELOG.md) · **Current release notes:** [LunAstra 4.3.0](docs/RELEASE_4.3.0.md)


## 4.3: less orchestration overhead, same seven members

Batchflow.3 removes unnecessary read/search hook work, reuses SQLite connections within one synchronous control operation, trims recovery context, wakes active research queues from completed work instead of a fixed one-second delay, and strengthens file-identity checks. The fixed roster remains one root Luna plus the same six persistent Luna children.

No model/reasoning setting is changed. Existing v3/v4 runtime data and unrelated hooks remain protected. See [4.3 release notes](docs/RELEASE_4.3.0.md), the full [changelog](CHANGELOG.md), and the historical [4.2 performance notes](docs/V4_2_PERFORMANCE.md). Real Windows speed, subscription usage and output quality remain live-host measurements rather than release claims.

## Model isolation retained from 4.1

Newly injected instructions are conditional, Luna-only and scoped to an activation/turn/role. A prior Luna protocol is inactive for non-Luna or unknown-model turns and when hooks are disabled/unregistered. The extension never changes the selected model to satisfy fixed-seven. **This does not delete instructions already present in an old conversation.** Pre-4.1 injected text cannot be patched retroactively; use a new conversation for clean non-Luna work.

Parsed `event.model` is the only activation input. Text mentioning Luna, UI labels, config guesses and stored prior model names cannot authorize it. Bare `gpt-reserve` is UNKNOWN and inactive in this release until a reliable Luna discriminator is demonstrated. Explicit `gpt-<version>-luna...` variants are unchanged.

After you choose to register this build, `CHECK_MODEL_GATE.cmd` arms a private capture for at most 300 seconds or 128 events. It does not register hooks or start a model. `MODEL_GATE_REPORT.cmd` exports the allowlisted report; `STOP_MODEL_GATE.cmd` stops early and retains evidence. Normal non-Luna operation does not record diagnostic events. See [model scope, diagnostics and live acceptance](docs/MODEL_SCOPE.md).

`INSTALL_LUNA_HOME.cmd` / `CHECK_LUNA_HOME.cmd` / `UNREGISTER_LUNA_HOME.cmd` target `~/.codex-lunastra` instead of the default home. **They do not route Codex Desktop/IDE, copy login/config files, or disable hooks registered in another home.** CLI support alone does not establish Desktop/IDE routing. Use the isolated target only after confirming the effective home in the actual host. Normal single-home mixed-model use still depends on the model gate, not repeated install/unregister cycles.


## A moon dreaming of the stars.

**Keep Luna. Give it a team that plans, builds, challenges, and checks its work.**

LunAstra 4.3.0 **batchflow.3 / fixed-seven** keeps one main Luna and six persistent Luna children. They form a plan, work on separate obligations, and review the assembled result. The same six native sessions are reused; finishing a phase is not an excuse to start another swarm.

The ambition is to approach Astra Max-level task quality and efficiency with a light Luna configuration. That is a real-task evaluation target, **not a measured result of this release**. LunAstra does not call Astra, change model weights, select a heavier model, or quietly increase reasoning effort.

[Start here](#quick-start) · [How it works](#how-it-works) · [Fixed-seven protocol](docs/FIXED_SEVEN.md) · [Compatibility](docs/COMPATIBILITY.md) · [Security](SECURITY.md)

## Why build it?

For people who want more from the Luna they already use. Not just another answer: a plan worth following, a result checked against the original request, and a way back when something goes wrong.

Seven sessions do not automatically produce seven times the insight. LunAstra makes the work explicit instead: independent perspectives before committing to a plan, bounded implementation, evidence-based decisions, and two members who never implement and remain independent acceptance reviewers.

## What changes in 4.0

- A typed preflight registry rejects the wrong workspace and missing required inputs before spawning workers; absent outputs are allowed.
- `crew-step` groups current reports, legal actions, reservations and batch waits. Native calls and semantic decisions still belong to the actual host/root.
- Long literal JSON is staged automatically by the hook as a private owner-bound content-addressed request, rather than model-driven 1,000-character chunks.
- Changed dependencies make old blockers stale and eligible for a same-member recheck, never automatically successful. Results and incomplete certification are separate.
- Canonical path comparisons, opt-in deterministic receipt reuse, and snapshot/acceptance-bound review reuse remove identified false gates without ignoring real changes.
- Explicit continuous research uses a persistent local compute queue, verifier receipts, cooperative pause/drain and same-six checkpoint resumption. It does not trade, call a model API or promote authority.

See [4.0 behavior, migration and limits](docs/V4_STATEFLOW.md) and [release notes](docs/RELEASE_4.3.0.md).
This archive is a locally tested software build. Live Windows Codex, model quality, subscription usage savings and wall-clock speedup need separate measurement.

## How it works

```text
Your request
    |
    v
PREPARE resources and exact workspace
    |
    v
Main Luna + six persistent Luna children
    |
    +-- PLAN: six distinct investigations; main Luna chooses from evidence
    |
    +-- EXECUTE: reuse the same six; separate work and retain two reviewers
    |
    +-- CHECK: integrate implementation and run real acceptance commands
    |
    +-- REVIEW: all six inspect the assembled output; two cover every requirement
    |
    +-- findings? --> targeted repair with the same six --> new checks/review
    |
    v
Current evidence + reviewed artifact + final synthesis --> deliver
```

**Seven means one root plus six children, not seven helpers.** The roster is fixed, not the number of simultaneous writes. Dependencies can serialize work; idle members do not need to generate filler. If the host cannot provide six native child sessions, the protocol reports the capacity blocker rather than certifying a smaller crew as seven.

During planning and final review, recognized edits are blocked. During execution, implementation slots receive explicit file scopes and detached Git worktrees when safe. When isolation is unavailable, those slots become read-only advisors and the main Luna is the writer; the six-member roster is retained. Returned patches still need checked integration.

Completion requires six current, source-linked review reports, successful declared checks, matching worker identities, and the same artifact/input snapshot that was reviewed. Changed files, failed checks, missing reports, or an unacknowledged native call cannot become a verified result by changing a label.

## Not only code

The coordination contract also covers research, documents, data, spreadsheets, and other local deliverables supported by your actual Codex host. The root chooses checks appropriate to the output: data reconciliation, document structure, formula results, or software tests.

LunAstra provides no spreadsheet renderer, office application, or model API. Its bounded read-only reader is UTF-8 oriented. Binary outputs can be fingerprinted, but their contents require real host-side tools and checks. Git worktree and patch guards are specifically for repository work; they are not general document-merging tools or an OS sandbox.

## Quick Start

Requirements: Python **3.10+**, an installed Codex host that exposes the necessary lifecycle hooks and native Luna agent tools, a selected supported Luna model, and capacity for six child sessions. Git is needed for isolated implementation workspaces. Installation does not download prerequisites or change the host's concurrency settings.

### Windows

1. Fully extract this distribution into a **new folder**.
2. Run `INSTALL.cmd`.
3. In the Codex host you actually use, open `/hooks` and review the LunAstra handlers.
4. Select Luna and your intended reasoning setting. A new conversation is the simplest first-use check; an existing conversation can initialize on its next Luna prompt **if the host has loaded the approved hooks**. Check native child-model/reasoning defaults too; LunAstra does not rewrite them.
5. Try the [first-use check](docs/SMOKE_TEST.md) in a disposable project.
6. Run `CHECK.cmd` to inspect installed files and observed hook activity.

### macOS / Linux

From the fully extracted `LunAstra` directory:

```sh
python3 install.py apply
python3 install.py doctor
```

Review the hooks and follow the same first-use check as on Windows.

> [!IMPORTANT]
> Selecting Luna is not proof that hooks ran. Confirm current hook activity with `CHECK.cmd`, then confirm six distinct native child IDs and the same-ID reuse with `crew-state`. Older **dynamic-team LunAstra records** are not silently converted to fixed seven. Finish that work with its matching build; do not restart active work just to test the installation.

## Using it

Give Luna the task normally. You do not have to invent six roles or fill out the internal protocol forms.

> Read the source data, create the requested report, and check the totals and missing records before returning the file.

> Fix the parser without changing its public API. Add a reproduction and verify the integrated result.

The local helper supplies the phase contract, dispatch tickets, evidence storage, and integration checks. **Native Codex, not the helper, actually starts and communicates with the models.** The root performs the returned native calls and makes evidence-based decisions. A list of six reservations is not six running agents.

For the next action and compact progress, use the hook-supplied helper followed by `crew-step`; `crew-state` remains a detailed diagnostic. `context --recover` restores the contract, phase, exact member identities, and current work references. `crew-report-read SLOT` returns a full current report only when needed. A status question can be acknowledged with `crew-continue` without restarting active work; genuinely changed requirements use an explicit revision.

## Boundaries that stay intact

LunAstra does not rewrite your selected Luna, reasoning setting, authentication files, unrelated hooks, or normal Codex permission review. Native child defaults can still override a parent's model or effort, so check the effective child settings rather than assuming that full-history forks guarantee inheritance. The installed runtime adds no extra model API client, telemetry uploader, or automatic publisher. Arbitrary commands and native host tools can still access data or the network when the host permits them.

The extra sessions, inherited context, and review rounds **consume ordinary model usage**. Fixed seven is a quality-oriented policy, not a promised token-saving mode. It can cost more than a single Luna on a small task. Comparative efficiency must be measured per accepted deliverable, not inferred from the number of workers.

Read [Security](SECURITY.md), [Limits](docs/LIMITS.md), and [Compatibility](docs/COMPATIBILITY.md) before sensitive work.

## Check the software, then measure the model

```sh
python3 -m pip install -r requirements-dev.txt
python3 tools/validate.py --output /tmp/lunastra-validation
python3 tools/release.py --source-output /tmp/LunAstra-4.3.0-source.zip
python3 tools/release.py --output /tmp/LunAstra-4.3.0.zip
python3 tools/release.py --verify /tmp/LunAstra-4.3.0.zip
```

The test suite uses native-shaped **synthetic** model events and real local subprocesses, files, SQLite records, installation copies, and Git worktrees. It checks the software contract without charging a model account. It does not measure Astra Max parity or prove that a particular live Codex app exposes the required tools.

Use the separate [evaluation protocol](evals/PROTOCOL.md) for controlled light-Luna, fixed-seven, and Astra Max comparisons. Retain unsuccessful runs, actual elapsed time, interventions, and observed usage. Missing measurements remain unknown.

## Update or remove

Keep each distribution in its own folder. Version 4 uses separate `state-v4`; `state-v3` is not converted or deleted. Finish/drain old active work with its matching build before upgrading. Installation refuses a payload change when recorded old work/controllers remain unresolved. Installed payloads are content-addressed and earlier records are preserved. Review changed hooks and open a new session after updating.

`UNREGISTER.cmd` removes owned hook registrations without deleting local work. `PURGE.cmd` is a separate, explicit owned-data removal flow with activity and ownership checks. Read [Removal](docs/REMOVAL.md) before deleting state or worktree copies. Do not use an older dynamic-team build to resume an active fixed-seven run.

## Documentation

[Stability maintenance notes](docs/STABILITY.md)


[Fixed-seven protocol and recovery](docs/FIXED_SEVEN.md) · [Architecture](docs/ARCHITECTURE.md) and [Compatibility](docs/COMPATIBILITY.md) · [First-use check](docs/SMOKE_TEST.md) and [Troubleshooting](docs/TROUBLESHOOTING.md) · [Validation](docs/VALIDATION.md), [Evaluation](evals/PROTOCOL.md), and [Limits](docs/LIMITS.md) · [Security](SECURITY.md), [Removal](docs/REMOVAL.md), and [Publishing](docs/PUBLISHING.md) · [Contributing](CONTRIBUTING.md), [Changelog](CHANGELOG.md), and [Release notes](docs/RELEASE_4.3.0.md)

## License

[MIT](LICENSE). LunAstra is an independent project, not an OpenAI product or endorsement.

**Luna does the work. The ambition is bigger.**
