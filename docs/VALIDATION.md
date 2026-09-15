# Validation

LunAstra separates software correctness from model-quality claims. The repository test suite exercises the local orchestration, hook adapters, workspace isolation, evidence records, installation behavior, release packaging, and pinned Codex contract fixtures without calling a model.

## Local software checks

Run:

```sh
python3 -m pip install -r requirements-dev.txt
python3 tools/validate.py --output /tmp/lunastra-validation
```

The validator records the test count, failures, errors, skipped tests, wall time, and source fingerprint before and after the run. A successful result requires at least one test, zero failures/errors/skips/expected failures, and an unchanged source fingerprint.

The suite includes native-shaped child-session events, parent/spawn binding, join races, foreign worker IDs and models, `PreToolUse` rewrite semantics, the `Bash` hook shape, Windows literal argument construction, Luna V1 tool names, Luna Reserve recognition, read-only execution refusal, source-read bounds, real subprocess cwd behavior, stale verification state, Git integration safety, and installation ownership checks.

The publishing regressions also cover stable-host fallback events, advisory CLI provenance, no-CLI installation, local helper startup failure, read-only current-payload observations, explicit data removal, unknown ownership, active jobs, and the source/release archive split.

## Release checks

Build and verify the archive:

```sh
python3 tools/release.py --output /tmp/LunAstra-3.2.0.zip
python3 tools/release.py --verify /tmp/LunAstra-3.2.0.zip
```

The release verifier checks the allowlist, manifest membership, file hashes, archive paths, case collisions, symlinks, size limits, version consistency, documentation links, and common credential formats.

For a release candidate, extract the archive into a fresh directory and rerun at least the integration tests from that extracted copy. Hosted GitHub Actions should also pass on the published commit.

## Scope

Local tests do not substitute for a live Codex session on every supported operating system. They also do not measure Luna/Astra task quality, token usage, account limits, or subscription cost. Those questions require separate real-task evaluation under controlled conditions.

Connection tests use synthetic hook traffic. A passing test proves the tested parsing and bookkeeping path, not that a desktop, CLI or hosted runner has executed it. Historical observations from previous payloads are excluded; paired tool calls must match both turn and call identity.

## Fixed-seven coverage

The additional suites cover six actual-shaped native spawn acknowledgements, same-ID sends across three phases, two non-implementing reviewer slots, source-linked reports, root check coverage, artifact snapshots, no seventh child, no hidden model/effort override, join and acknowledgement races, crash recovery, requirement drift, current-ticket identity, bounded JSON staging, missing-report termination, and targeted repair.

Installed integration tests execute shell hooks and CLI helpers from an immutable copied installation. They use real temporary source files, subprocess checks, Git worktrees and guarded integration, while model messages and results remain synthetic. Existing dynamic integration fixtures explicitly seed an old root session to test migration instead of weakening the new fixed-seven policy.

A final release check should also rerun the whole suite from a fresh extraction of the exact delivered install ZIP. Keep that result separate from the original source run; duplicate reruns do not increase the number of distinct tests.
