# LunAstra 4.3.0 — Batchflow.3

LunAstra 4.3.0 promotes the final batchflow.3 maintenance line to the current public release while preserving the fixed-seven contract: one root Luna plus the same six persistent Luna children.

## What changed since 4.2

- Skip operational hook work for native read/search and other unhandled tools at both matcher and parsed-event boundaries. Model authorization remains unchanged.
- Reuse one thread-local SQLite connection inside a synchronous hook/controller operation while retaining nested transaction rollback and cleanup.
- Reconcile only the current session's completed synchronous edit leases at Stop. Missing native acknowledgements remain UNKNOWN rather than being treated as success.
- Compact fixed-seven startup/recovery context and restore only bounded scoped state plus member/phase pointers; full notes and contracts remain available through recovery commands.
- Require fixed-crew root shell work to use registered checks/research helpers, while structured edit tools enforce declared output scope. This is coordination, not an OS sandbox.
- Wake active local research queues on completed futures instead of a fixed one-second delay after every wave. Idle queues keep bounded low-frequency polling.
- Strengthen file hashing against pathname replacement and same-size/restored-mtime races by validating the opened file identity and change metadata.
- Preserve all 4.2 safety work: Luna-only model scope, stale blocker reevaluation, V1/V2 native adapters, short worker capsules, batch research notifications, complete-observation requirements, and safe controller recovery.

## Compatibility and limits

No model, reasoning level, account setting, concurrency limit, or unrelated hook is changed automatically. Existing v3/v4 runtime data remains protected. This release does not claim that arbitrary shell commands are sandboxed.

The software regression suite validates synthetic/native-shaped host events plus real local files, SQLite, subprocesses, packaging and install/update flows. Actual Windows Codex Desktop/IDE behavior, live V1/V2 child-agent behavior, Luna-to-Astra switching, and comparative model speed/token/quality remain live-host measurements rather than software-test claims.

## Version history

See [CHANGELOG.md](../CHANGELOG.md) for the complete retained public history. The current repository has authoritative detailed history from 3.0 onward. Earlier 1.x–2.x prototype history was not preserved as authoritative public release notes and is labeled accordingly rather than reconstructed from guesswork.
