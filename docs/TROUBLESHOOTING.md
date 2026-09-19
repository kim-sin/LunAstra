# Troubleshooting


## 4.1 model-scope lifecycle

See [MODEL_SCOPE.md](MODEL_SCOPE.md) for the exact gate policy, bounded diagnostic commands and the separate live acceptance matrix. Hook registration is not activation; an emitted kernel is not proof of Desktop consumption or currently running workers.

Unregister disables future **owned** hook injections in the selected home only. Already injected conversation context is **NOT RETRACTED**. Model switching may retain old text, especially from pre-4.1 builds. Use a new conversation for clean non-Luna work; do not delete state or terminate workers to fix context. Re-registering does not erase history. Existing v3/v4 records and unrelated hooks are preserved.

Bare `gpt-reserve` is UNKNOWN/fail-closed pending a proven Luna discriminator. Do not infer the selected model from prompt words, a UI label or a PATH CLI version. The optional `--isolated` home is a targeted installation, **not live-verified Desktop/IDE routing**. Check additional project/managed hook sources separately; changing a home cannot prove that every other injection source is absent.


## Installation was refused because of a Codex version

An earlier 3.2.0 distribution treated the CLI on PATH as the active Codex host and enforced a version cutoff. The current maintenance distribution removes that gate. Install it from a new extracted folder. Do not delete the existing installation, settings or work to bypass the earlier message.

This package is 4.3.0; old 3.2.0 records remain historical. Compare the distribution checksum and installer fingerprint to distinguish copies. A version message alone does not establish which engine your desktop app uses or whether it supports the needed hooks.

## Installed, but waiting for Luna

`INSTALLED` reports copied files and matching hook definitions. It does not start a model. In the host you use, review `/hooks`, approve LunAstra and open a new Luna conversation. Ask it to read a small file, then run `CHECK.cmd`.

If no events appear, compare the reported Codex settings directory with the active host's directory. Desktop, CLI, WSL and remote environments can use different homes and Python installations. Install into the environment that executes the hooks. Use `--codex-home PATH` only for that confirmed settings directory; do not copy or publish account files. A local installation does not automatically install the extension on a remote executor.

Check the selected model and effective hook setting in Codex. Root TOML settings shown by the diagnostic can be overridden by profiles or policy. A historical observation from another app using the same home does not authenticate the current app. For a new first-use test, filter with `--since` as described in [SMOKE_TEST.md](SMOKE_TEST.md).

## Hook errors or missing capabilities

Read the actual hook error in Codex. Python must be available at the interpreter path saved in the installed command. If Python was moved or removed, rerun the installer with a working interpreter, review the changed definitions, and use a new conversation.

If the host has no lifecycle hooks, the extension cannot be activated there. If it lacks native Luna V1 agents, do not assume delegated work is available. Do not forge worker identities or disable permission controls to make a test pass. A host update may help an identified missing feature; updating every Codex component is not the default remedy.

`HOOK_ERRORS_OBSERVED` and `DIAGNOSTICS_UNREADABLE` are not success states. Preserve the records and fix the reported cause. Do not purge evidence merely to make CHECK appear clean. Connection records summarize up to 200 recent sessions and do not replace task verification.

## Python launcher or local startup check failed

Windows launchers test `py -3`, then `python`, for Python 3.10 or newer before the operation starts. Installation and removal are each attempted only once. If neither interpreter works, install or repair Python. The installer never downloads or upgrades it automatically.

A local helper startup failure occurs before hook definitions are changed. Check executable access, the extracted file set and local security-software diagnostics. Do not disable antivirus, sandbox or approval protections. The staged release may be retained for inspection.

## Damaged hook definitions, locks or ownership records

The installer refuses to overwrite malformed hook definitions, unowned LunAstra entries and active installation locks. Read the reported path and preserve the files. A failed CHECK does not repair state or launch another install. See [REMOVAL.md](REMOVAL.md) for recovery and explicit removal.

## Exit status

| Command | Code | Meaning |
| --- | --- | --- |
| `apply` | 0 | Local installation and helper startup succeeded; inspect connection status separately. |
| `doctor` | 0 | Local diagnostics completed without an installation/error-state failure. Waiting is allowed. |
| `doctor` | 2 | Installed files/definitions mismatch or connection records show an error. |
| `doctor --require-observed` | 3 | Current-payload kernel plus a matched tool cycle has not been observed in the requested window. |
| Any command | 1 | The operation failed. Read its diagnostic before taking action. |

Native host permission review is always required. Observation metadata is not a security boundary or proof of model quality.


## 4.0 specific diagnostics

`UPGRADE_ACTIVE_WORK`: finish or cooperatively drain the recorded old work in its matching build before replacing hook definitions. Do not delete runtime rows, break locks, stop healthy Python processes or silently migrate active tickets. An unreadable/unknown controller is not proof of exit. Keep the old installation and its evidence intact.

`WORKSPACE_MISMATCH`: use the prepared task folder, not the directory containing the test pack or its answer/grader files. Do not copy model answers or graders into another model's workspace.

`CHANGED_PATH_UNVERIFIED`: inspect the exact changed files and actual check dependencies before certification. Add a real relevant check or restore only unintended changes you own; do not add broad fake coverage labels.

`REASSESS`: the dependency of a blocked report changed. Follow the returned send_input to the same completed member/ticket. Wait for a new report; STALE is not PASS.

Long JSON should be sent once with literal `--input-json`. A large request is rewritten to an owner-scoped sha256 reference by the approved hook. If a host does not honor documented updatedInput, stop with the actual transport limitation rather than claiming a speed improvement.

A local queue with `supervisor_liveness=UNCONFIRMED` is retained. Do not launch an unobserved replacement against the same outputs. Export its status/logs and confirm actual exit before recovery; this build does not automatically adopt orphaned operating-system processes.

## 4.2 batchflow.2 explicit recovery and certification errors

- `NATIVE_CAPACITY_UNKNOWN` / `NATIVE_CAPACITY_INSUFFICIENT`: use the actual exposed host configuration to declare V2 total capacity (root included). Do not alter concurrency, model or effort automatically. New V1 runs are unchanged.
- `REPORT_DETAILS_REQUIRED`: run `crew-step --details` for the current bounded report batch, or `crew-report-read SLOT`; repeat only for the reported remaining slots. Changed report bytes require a fresh retrieval.
- `WORKSPACE_OBSERVATION_INCOMPLETE`: successful scoped tests remain saved, but unknown workspace edits cannot be called complete. Preserve the baseline and inspect the unobserved scope; never delete files or reset state to bypass the check.
- `CONTROLLER_EXITED`: `research-recover` checks actual process exit and retains interrupted jobs/outputs. `research-start` includes the same check. Healthy/unknown processes are not restarted.
- `ORPHAN_JOB_UNRESOLVED`: the controller exited but a direct job process is alive or its launch cannot be resolved. Preserve it; a stale heartbeat is not permission to kill or duplicate it.

## batchflow.3 missing tool completion and scoped shell

An apply_patch/Edit/Write failure may not produce PostToolUse on every host. The next safe Stop boundary releases only this session's recorded synchronous edit lease. It records UNKNOWN, not success; changed files still need verification. A second Pre event or elapsed time cannot revoke an in-flight lease. Other sessions, manual leases and explicitly running operations remain protected.

This does not repair an unacknowledged native spawn by guessing it failed: the host may already have created a member. Preserve pending work; do not reset state, spawn replacements or claim fixed-seven completed. The current host must provide actual identity/acknowledgement evidence.

For fixed-crew root shell calls use the session's LOCAL_HELPER_COMMAND for registered checks/research. Use supported scoped edit tools for source changes. Direct exec_command uses cmd; native Bash uses command. The Windows transport stages large JSON once. A registered command still executes with native host permissions and is not a filesystem sandbox.

Compaction recovery retains the contract, reports and notes outside the prompt. crew-step returns current actions; context --recover returns the complete saved context. Do not equate the short recovery message with having read the full original. Previous legacy dynamic sessions must not be converted to fixed-seven merely by compaction.


## batchflow.4 receipt and streaming corrections

Run crew-step normally; it reconciles supported authentic native transcript receipts before selecting the next action. crew-reconcile performs just that recovery. REJECTED_BEFORE_START is different from UNKNOWN: only the observed exact capacity rejection permits crew-retry SLOT --reason TEXT after addressing the cause. Do not use retries to change host settings, replace a possibly running child or fabricate an acknowledgement. Missing transcripts, unsupported receipt formats and ambiguous errors remain unresolved.

Full contract/certification scans now include large files. Preserve a changing or inaccessible tree and diagnose the actual read/race error; do not delete files to obtain COMPLETE. Existing active incomplete baselines are not overwritten. A 300-second terminal hook ceiling and available memory/I/O still apply.

For LF-only source uploads, use tools/release.py to produce canonical Windows CMD bytes and fresh hashes. Do not manually change a ZIP without rebuilding its manifest. The archive verifier rejects noncanonical CMD bytes.
