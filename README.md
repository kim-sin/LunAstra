# LunAstra

<p align="center">
  <img src="docs/assets/lunastra-hero.webp" width="420" alt="LunAstra: a robot and a cat watching the moon together" />
</p>

## Current release

**LunAstra 4.3.0 — batchflow.4**

The same root and six persistent Luna children, with corrected native-acknowledgement recovery, encrypted-message routing, large-file certification and Windows archive line endings. Ordinary read/search hooks stay lightweight; correctness is not replaced by a timeout or cached file timestamp.

[Correction details](docs/RELEASE_4.3.0.md) · [Full changelog](CHANGELOG.md) · [Development history](#development-history)

Software regressions validate synthetic host events plus real local files, processes, SQLite and installation. Actual Desktop/IDE behavior and model speed, usage and quality remain separate measurements.

## A moon dreaming of the stars.

**Keep Luna. Give it a team that plans, builds, challenges, and checks its work.**

LunAstra 4.3.0 **batchflow.4 / fixed-seven** keeps one main Luna and six persistent Luna children. They form a plan, work on separate obligations, and review the assembled result. The same six native sessions are reused; finishing a phase is not an excuse to start another swarm.

The ambition is to approach Astra Max-level task quality and efficiency with a light Luna configuration. That is a real-task evaluation target, **not a measured result of this release**. LunAstra does not call Astra, change model weights, select a heavier model, or quietly increase reasoning effort.

[Start here](#quick-start) · [How it works](#how-it-works) · [Fixed-seven protocol](docs/FIXED_SEVEN.md) · [Compatibility](docs/COMPATIBILITY.md) · [Security](SECURITY.md)

## Why build it?

For people who want more from the Luna they already use. Not just another answer: a plan worth following, a result checked against the original request, and a way back when something goes wrong.

Seven sessions do not automatically produce seven times the insight. LunAstra makes the work explicit instead: independent perspectives before committing to a plan, bounded implementation, evidence-based decisions, and two members who never implement and remain independent acceptance reviewers.

## What the 4.x line changed

- **4.0 — stateflow:** preflight resources/workspace identity, staged requests, batched waits, source-bound blocker reassessment and persistent local research.
- **4.1 — model scope:** one Luna/non-Luna classifier, turn/role-scoped lifetime, bounded diagnostics and clear unregister limits.
- **4.2 — batchflow:** notification batches, shorter worker context, fewer redundant scans, explicit V1/V2 adapters and safer full-report/controller recovery.
- **4.3 — control-path corrections:** lower hook/DB overhead, compact recovery, completed-work wakeups, authentic native receipt recovery, opaque-message routing, large-file streaming and portable launcher packaging.

Fixed seven means one root and the same six children, not permission to manufacture success when evidence is missing. See [stateflow](docs/V4_STATEFLOW.md), [model scope](docs/MODEL_SCOPE.md), [historical performance notes](docs/V4_2_PERFORMANCE.md) and [current correction notes](docs/RELEASE_4.3.0.md).

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

## Development history

Retained history, newest first. Each maintenance build is distinct; detailed changes and limits remain in [CHANGELOG.md](CHANGELOG.md). 1.x/2.x are labeled undocumented rather than invented.

| Release / build | Main changes |
|---|---|
| **4.3.0 batchflow.4** | Recover missing native PostToolUse acknowledgements from exact function-call/output pairs in a host-observed local transcript. Bind the call ID, original input hash, root session, turn when present, transcript identity and current ticket; assistant prose and generic error text cannot authorize another model. Expose root-only crew-reconcile and same-ticket crew-retry. Only the exact observed V1 pre-start capacity rejection can authorize a deliberate retry after its cause is addressed. Unknown/running calls and missing receipts remain protected; no timeout-based respawn. |
| **4.3.0 batchflow.3** | Skip operational hooks for native read/search and other unhandled tools, both at matcher and early parsed-event boundaries. Model authorization remains unchanged. Share one thread-local SQLite connection per synchronous hook/controller operation, preserving transaction boundaries and nested rollback. Static schema setup no longer commits an outer transaction. |
| **4.2.0 batchflow.2** | Correct V2 task-name grammar and require declared total capacity for the fixed roster, without changing Codex settings. Capacity includes the root; it is not a statement that all retained identities are simultaneously active. Reject incomplete before/after workspace observations for whole-change certification. Keep successful scoped test results as evidence, not falsely COMPLETE. |
| **4.2.0 batchflow.1** | Batch local research notifications with persistent delivery cursors; old errors/revision-only changes do not repeatedly wake the model. Replace job-pair output conflict checks with a path trie and iterative dependency traversal; use indexed ready selection, SQL counts and bounded status receipts. |
| **4.1.0 model-scope.1** | Scope every newly injected protocol to its observed Luna activation, turn and role; place the inactive-on-model-change/unregister rule before any crew obligation. Use one stdlib-only parsed-model gate before task imports and inside hooks. Non-Luna, missing, malformed and unknown models produce inert output. |
| **4.0.0 stateflow.1** | Add preflight resource roles and expected workspace validation before native dispatch. Unify path identities used by output coverage, evidence and Stop guards. |
| **3.2.0 fixed-seven-flow.1** | Repair premature parent Stop and worker-specific report recovery. Drive native waits and same-member recovery without replacing the six IDs. |
| **3.2.0 fixed-seven-stability.2** | Preserve automatic Luna activation and one lead plus six persistent workers. Canonicalize merge-lock identity before acquiring a filesystem lock. |
| **3.2.0 fixed-seven-publication.1** | Correct inactive inherited-filter handling without running active checkout filters. Normalize snapshot and worker alias paths; retain symlink and ownership guards. |
| **3.2.0 fixed-seven** | Add a seven-session contract: one root and six persistent native Luna children, reused across plan, execution and final review. Require actual native identities and send acknowledgements; refuse replacement or nested workers. |
| **3.2.0 installation compatibility** | Remove the PATH CLI version cutoff; CLI provenance is diagnostic, not active-host identity. Treat direct root feature settings as advisory because profiles and policy can differ. |
| **3.2.0 publication maintenance** | Add CLI version diagnostics and stable-host startup-fallback regressions (the original version gate is removed by installation compatibility maintenance). Report unknown, old, preview and unreviewed hosts separately from installation success. |
| **3.2.0 — 2026-09-12** | Bounded Luna worker planning with native child-agent binding and a six-worker concurrency ceiling. Isolated Git workspaces for implementation tasks, with checked patch integration and single-writer fallback. |
| **3.1.0** | Added a lightweight installed-hook prefilter for ordinary non-Luna events. Retained exact model validation inside the Python helper. |
| **3.0.0** | Rebuilt the project around a Luna-led transactional work plan, bounded native delegation, worktree isolation, checked integration, verification records, and source-only distribution. |
| **2.x — legacy pre-public prototype line** | No authoritative detailed 2.x release notes/artifacts are retained in the current repository; earlier changes are not invented. |
| **1.x — legacy pre-public prototype line** | No authoritative detailed 1.x release notes/artifacts are retained in the current repository; earlier changes are not invented. |

Release-specific notes: [4.3](docs/RELEASE_4.3.0.md), [4.2](docs/RELEASE_4.2.0.md), [4.1](docs/RELEASE_4.1.0.md), [4.0](docs/RELEASE_4.0.0.md) and [3.2](docs/RELEASE_3.2.0.md).

## License

[MIT](LICENSE). LunAstra is an independent project, not an OpenAI product or endorsement.

**Luna does the work. The ambition is bigger.**
