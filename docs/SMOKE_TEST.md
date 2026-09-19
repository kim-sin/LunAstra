> 4.2 update: current short-context, batch-wait and V1/V2 behavior is specified in [V4_2_PERFORMANCE.md](V4_2_PERFORMANCE.md). Older full-history/V1-only descriptions below apply to preserved legacy mode, not new capsule runs. Actual host verification remains separate.

# First-use check


## 4.1 model-scope lifecycle

See [MODEL_SCOPE.md](MODEL_SCOPE.md) for the exact gate policy, bounded diagnostic commands and the separate live acceptance matrix. Hook registration is not activation; an emitted kernel is not proof of Desktop consumption or currently running workers.

Unregister disables future **owned** hook injections in the selected home only. Already injected conversation context is **NOT RETRACTED**. Model switching may retain old text, especially from pre-4.1 builds. Use a new conversation for clean non-Luna work; do not delete state or terminate workers to fix context. Re-registering does not erase history. Existing v3/v4 records and unrelated hooks are preserved.

Bare `gpt-reserve` is UNKNOWN/fail-closed pending a proven Luna discriminator. Do not infer the selected model from prompt words, a UI label or a PATH CLI version. The optional `--isolated` home is a targeted installation, **not live-verified Desktop/IDE routing**. Check additional project/managed hook sources separately; changing a home cannot prove that every other injection source is absent.


Use a disposable project in the Codex app or CLI you actually use. Do not update an unrelated CLI just because the installer reports its version.

1. Fully extract the distribution and run `INSTALL.cmd` (Windows) or `python3 install.py apply` (macOS/Linux). The output separates installed files from connection status.
2. In your active Codex host, open `/hooks`, review the LunAstra definitions and approve them. For the simplest first-use check, start a new Luna conversation. An existing chat can initialize on its next Luna prompt if this host has loaded the approved hooks; verify the observation rather than assuming model selection activated it. Review native child-model/reasoning defaults before dispatch; full-history forks alone do not override those defaults. Confirm the effective child model/effort in the host before a light-Luna benchmark. Do not restart existing research or workers for this check.
3. Ask Luna to inspect a small local file. Run `CHECK.cmd` or `python3 install.py doctor`. Look for current-release observations and the last-event timestamp. `TOOL_CYCLE_OBSERVED` means matched before/after events were recorded; it is not a result-quality certificate.
4. In a clean disposable Git repository, request a small file change and a behavior test. For this fixed-seven build, confirm exactly six native child IDs are returned during PLAN, all six join and report, and the same six IDs receive EXECUTE and REVIEW work through native `send_input` acknowledgements. There must be no replacement seventh child. Slots 5 and 6 remain read-only. Request the current `crew-state` summary rather than accepting a list of planned roles as proof of live agents.
5. Confirm implementation stays within its assigned worktree, checked integration reaches the root, actual root commands pass, and all six final reports refer to the current output. `phase=COMPLETE` is only software evidence for that locked artifact and declared checks. A host with fewer than six available child sessions must report the limit without claiming success.
6. Inspect the resulting diff and test output. Verify unrelated files are unchanged. A successful test command only covers the behavior actually tested.
7. Optionally unregister, start a new conversation and confirm that owned hooks are disabled. Reinstall only when ready to enable them again.

For an automated observation gate, note the current Unix timestamp before step 2, then run `python3 install.py doctor --require-observed --since TIMESTAMP --json`. Code 3 means the required current-payload observation is still missing. Do not send that placeholder literally; use the timestamp you recorded. This command observes local records and makes no model calls.

An installation with no events is not a passed connection test. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for the effective config location, trust, model and missing-capability checks. Only consider a host update when the host you actually use lacks a required feature or exhibits an identified contract incompatibility.

Record OS, Python version, Codex surface/build, package fingerprint and the observed result. Do not publish credentials, full transcripts, personal paths or project contents. The live steps use the account's ordinary usage allowance; installation and doctor do not create model calls.
