# Disable, remove, and recover


## 4.1 model-scope lifecycle

See [MODEL_SCOPE.md](MODEL_SCOPE.md) for the exact gate policy, bounded diagnostic commands and the separate live acceptance matrix. Hook registration is not activation; an emitted kernel is not proof of Desktop consumption or currently running workers.

Unregister disables future **owned** hook injections in the selected home only. Already injected conversation context is **NOT RETRACTED**. Model switching may retain old text, especially from pre-4.1 builds. Use a new conversation for clean non-Luna work; do not delete state or terminate workers to fix context. Re-registering does not erase history. Existing v3/v4 records and unrelated hooks are preserved.

Bare `gpt-reserve` is UNKNOWN/fail-closed pending a proven Luna discriminator. Do not infer the selected model from prompt words, a UI label or a PATH CLI version. The optional `--isolated` home is a targeted installation, **not live-verified Desktop/IDE routing**. Check additional project/managed hook sources separately; changing a home cannot prove that every other injection source is absent.


## Disable without losing work

Run `UNREGISTER.cmd` on Windows, or `python3 install.py unregister` from the extracted distribution on macOS/Linux. This removes only hook handlers owned by the installation record. It preserves installed releases, worktree copies, notes, logs, verification data and backups.

Start a new Codex session before checking that the extension is disabled. Unregister does not terminate sessions or processes that already loaded it.

## Delete owned local data

Close all Codex sessions and local verification jobs first. Export any patches or worktree changes you need. Run the following from the extracted distribution, not from an installed release directory:

```sh
python3 install.py purge-plan
python3 install.py purge --confirm DELETE-LUNASTRA-DATA --confirm-idle
```

Windows users can double-click `PURGE.cmd`. It displays the exact data directory and asks for `CLOSED` and `DELETE-LUNASTRA-DATA`. Nothing is deleted by `purge-plan`. `--confirm-idle` is a user assertion; PID existence is not treated as proof of inactivity.

Worktree copies require a separate explicit option after exporting needed work:

```sh
python3 install.py purge-plan --include-workspaces
python3 install.py purge --confirm DELETE-LUNASTRA-DATA --confirm-idle --include-workspaces
```

Removal is restricted to `luna-astra` under the selected Codex home. It refuses unknown ownership, symlinks/junctions, unexpected top-level data, malformed runtime records, unresolved workers and unfinished checks. It does not kill jobs to make removal succeed. A failure may leave some owned data in place; the ownership record is retained until other data is removed, allowing a retry.

The command does not delete external projects, Codex account/configuration files, unrelated hooks, the downloaded distribution, operating-system backups or logs stored elsewhere. A removed worktree may leave an administrative registration in its external Git repository; after confirming all related sessions are closed, review `git worktree list` there. Git's own `git worktree prune` can clean stale registrations; LunAstra does not run it automatically because it can affect other stale worktrees too.

## Damaged or interrupted installations

Do not break an install lock while another installer may be active. Close the relevant applications and inspect the lock before manually removing it. If an ownership record is missing, an old job is permanently marked as running, or a local record is corrupted, automatic purge deliberately refuses to guess.

Use `install.py plan --json` and `install.py doctor --json` to identify the exact data location; redact paths before sharing output. Back up needed work. Review the matching hook entries in Codex, disable/remove only LunAstra entries, close remaining sessions and then use the operating system's file manager to remove only the confirmed `luna-astra` data directory. Never delete the whole `.codex` directory. Do not share `auth.json`, unredacted hook backups or runtime databases.

## Upgrade and rollback

Extract each distribution into a new directory and run its installer. Releases are content-addressed, so previous installed releases and records are not overwritten. Review changed hook commands again in Codex. Finish active worker results with the version that created them before switching sessions.

To roll back, run `INSTALL.cmd` from a retained earlier distribution, review its hooks and start a new session. Runtime-state formats may differ; keep the existing data and review the earlier version's compatibility notes rather than deleting it. File-format compatibility is not inferred from a shared version label.

## Fixed-seven upgrades

Finish active dynamic work using its matching distribution. New observed root sessions load fixed-seven; existing persisted roots retain their prior mode. Do not roll an active fixed-seven run back to the earlier dynamic implementation. Finish or explicitly preserve its incomplete work first, then use a new session with the selected distribution.

Each reused worker assignment stores its own flat evidence context under `state-v4/sessions` (old `state-v3` is retained). Purge checks include those contexts, not just the latest worker ticket. Owner-bound JSON request blobs, research queues and logs, JSON input buffers, source-linked reports and crew history can contain project data and are part of owned local state.


Model-gate captures are preserved by unregister. Only the existing explicit, confirmed, idle data-removal operation can remove these owned diagnostic files. A diagnostic arm marker or control operation blocks purge until diagnostics are stopped. This is lifecycle compatibility, not a recommended remedy for contaminated context; do not use purge for model-switch problems.
