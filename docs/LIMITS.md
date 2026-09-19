> Current 4.3.0 batchflow.4 corrections supersede the historical limits below where noted: [native receipts, opaque V2 routing, full streaming scans and packaging](RELEASE_4.3.0.md). No live-host certification is implied.

> 4.2 update: current short-context, batch-wait and V1/V2 behavior is specified in [V4_2_PERFORMANCE.md](V4_2_PERFORMANCE.md). Older full-history/V1-only descriptions below apply to preserved legacy mode, not new capsule runs. Actual host verification remains separate.

# Limits

- LunAstra changes orchestration behavior; it does not change model weights or guarantee Astra-equivalent results.
- Delegation quality still depends on the root Luna choosing useful work units and reviewing returned results.
- This build fixes one root plus six child sessions for new work. Six is no longer an optional allocation target. Dependencies may serialize their jobs. More sessions can increase usage without improving quality.
- Native feature flags, account limits and child capacity can block fixed-seven execution. Fewer than six observed children are never labeled a complete seven-session run.
- Git worktrees isolate repository state, not operating-system permissions. Effective process permissions come from the launching host; hooks do not add an OS sandbox.
- Arbitrary shell programs can reference absolute paths. LunAstra only enforces the command paths it can recognize and validate.
- Read-only source access is bounded and UTF-8 oriented; binary or unusually encoded project files may require ordinary Codex tools.
- Static source maps are navigation hints. They are not a completeness proof and do not replace source review.
- Verification records prove only the declared checks and inputs. The root model still has to choose tests that match the actual requirement.
- Compaction restoration occurs on the next supported context-capable event, not directly from `PostCompact`.
- The non-Luna fast path still starts the host shell or PowerShell wrapper; it is a low-overhead filter, not a zero-process path.
- Local runtime databases are integrity state for normal operation, not a tamper-resistant security boundary against a hostile local process.
- Native Windows/macOS execution and real model-quality/usage comparisons must be validated separately from Linux software tests.

- Installing files does not prove hook activation. A PATH CLI version is advisory and may not identify the desktop or IDE engine.
- Current-release event records describe observed local traffic, not authenticated live-host verification. CHECK does not create model calls or run task checks.

## Fixed-seven-specific limits

- Native models are dispatched by the root through Codex tools, not automatically by a standalone Python service.
- Planning/review guards apply to recognized hooked tool paths. Native search/MCP/host paths outside that coverage are not an OS security boundary.
- The model chooses meaningful requirements, test commands, source interpretation and synthesis; structural gates cannot prove those semantic judgments are correct.
- Slots 5 and 6 never implement; other members may review their own earlier work, so not all six are independent of implementation.
- Read-only members cannot directly run arbitrary shell programs. They send needed executable checks to the root.
- Final snapshots support binary bytes, not office-format semantics. Artifact tools must perform formula, document or rendering checks.
- Reusing sessions is not a promise of zero context overhead or token savings. A fixed seven-session run may be inappropriate for a trivial question.
- The requested light-Luna versus Astra Max comparison is an evaluation goal, not established by the package's test count.
- Earlier dynamic sessions are retained for migration. Start a new session to activate fixed seven; never force a running old session into a new phase contract.
