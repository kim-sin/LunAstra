# LunAstra 4.3.0 — batchflow.4

This is the correction of the public 4.3.0 batchflow.3 source line. The version remains 4.3.0; the build marker is batchflow.4. It is not a claim that live model quality was measured. One coordinating Luna and the same six persistent native Luna children remain the contract.

## Missing native acknowledgements

crew-step automatically attempts local receipt reconciliation; crew-reconcile is an explicit root-only entry point. Recovery reads only the transcript path supplied by an observed native pre-hook. It checks the root session header, file identity, exact call ID, original argument hash and native function name; turn context is checked when present. Only a matching function_call followed by function_call_output can restore an acknowledgement. Reads are incremental and bounded to 8 MiB per pass and 2 MiB per record. Raw transcript contents are not copied to runtime diagnostics or sent to a service.

A recovered success binds the actual returned identity; it starts no model. The exact V1 host rejection `collab spawn failed: agent thread limit reached` records that the call did not start. After addressing the actual cause, the root can run `crew-retry SLOT --reason TEXT`; this preserves the same ticket and does not itself launch anything. Generic errors, timeouts, missing records and unobserved transcript paths remain UNKNOWN. They cannot safely prove that a child was not already created. Missing host evidence remains a real operational limit, not a reason to guess or erase pending work.

## V2 routing and tool names

Opaque encrypted message content is not searched for a plaintext ticket. A call must match one unique, currently emitted routing intent for its phase, reserved task name or bound target, call kind and non-message arguments. Existing exact-ticket worker joins, actual model observations, canonical names and same-six reuse still gate execution/completion. Model/effort overrides remain forbidden. This authenticates routing; it does not inspect or decrypt the message semantics. Plaintext V1 tickets remain required. Dotted `multi_agent_v1.spawn_agent` and related native names are recognized alongside retained legacy names.

## Large files and content integrity

Automatic previews remain cheap and bounded. Initial fixed-seven contracts establish a complete baseline before dispatch, outside a SQLite writer lock. Full certification and review fingerprints stream large files instead of excluding them at the old 2 MiB/32 MiB or 64 MiB/512 MiB limits. Missing/read-error/symlink/special/changing paths never become partial success. Existing active incomplete baselines are not silently reset. One-million-entry review bounds protect memory; full observations still require memory proportional to file count, sufficient storage throughput and a stable readable tree.

Late mutations of an earlier file while later files are read, newly appearing declared outputs, directory mutations and dependency walk errors invalidate the snapshot. Overlapping dependency paths share hashes inside a traversal. There is no persistent mtime-only content cache.

Stop/SubagentStop certification handlers have a 300-second timeout rather than the ordinary 10-second tool-hook budget. This is a ceiling, not a fixed wait. No claim of unlimited file size/count or host reliability is made. Hooks do not implement an OS sandbox, and host crash/timeout behavior remains outside the package's guarantee.

## Less repeated research I/O

After enqueue, input bytes are checked before compute, after compute and at final ingest. The duplicate adjacent verifier/ingest pass is removed. Parsed result bytes must match the checked output hash. Output and input mutation by a verifier and a failed verifier still prevent promotion. These are local control-path reductions, not a measured live model speedup.

## Portable packaging

Git attributes request CRLF CMD checkouts. The source/archive builder also normalizes CMD line endings without altering the input checkout; manifests are calculated from the actual packaged bytes. The verifier rejects malformed/noncanonical launchers. Thus an LF-only API upload does not quietly recreate the same broken downloadable Windows launchers. All other file bytes retain normal integrity checks.

## Install and verification boundary

Finish or cooperatively drain old active work using its matching build. Extract this distribution into a new folder, run INSTALL.cmd and review changed hooks in the actual Codex host. The installer preserves previous payloads, unrelated hooks, accounts/config and v3/v4 records, and refuses unresolved active work. No user PC or remote repository is modified by building an archive.

Software tests use synthetic host events and real local files, processes, SQLite, Git checkouts and installations. They do not establish Windows Desktop/IDE behavior, V1/V2 model inference, model-switch behavior or Astra-equivalent quality. Full retained history is in [CHANGELOG.md](../CHANGELOG.md).
