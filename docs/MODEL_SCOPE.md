# Luna-only activation, lifetime and mixed-model operation

## What 4.1 changes, and what it does not prove

This release is based on 4.0 stateflow, not a rollback to 3.2. It preserves root plus the same six children, same-ID reports/recovery, guarded integration, verification freshness, JSON references, research queues and safe installation. It uses `state-v4` without deleting/converting `state-v3` or v4 records.

The reported incident is compatible with retained injected context, host model misclassification, or both. **The original raw event.model was not captured. The historical cause is not confirmed by this patch.** Capturing new events can distinguish current behavior but cannot reconstruct missing historical fields. No model names in synthetic tests are represented as live observations.

There are two distinct guarantees:

| Layer | Implemented rule | Remaining boundary |
|---|---|---|
| Code gate | Only a supported parsed event.model reaches task-state/prompt/permission logic | Trusts the host-supplied field, not independently authenticated |
| Prompt lifetime | New protocol says old crew duties are INACTIVE after model/role/activation change or unregister | Text is not a hard revocation primitive; actual same-conversation compliance needs a live check |
| Unregister | Removes only exact owned handlers from the selected home | Cannot retract old context or edit other hook sources |
| Isolated target | `--isolated` targets a different settings home | Does not route/launch Desktop/IDE or copy config/auth |

If an already injected conversation says it must obey fixed-seven after changing away from Luna, preserve the work and use a clean new non-Luna conversation. Do not demand an Astra crew. Installing 4.1 cannot retroactively rewrite older injections.

## Parsed model authority

`luna_astra/model_gate.py` is the single stdlib-only authority imported by both `luna.py` and `Hooks`. Exact versioned `gpt-<version>-luna` names and their supported suffix forms are accepted. Other names are inactive; malformed/missing values return UNKNOWN. JSON duplicate keys, malformed JSON and oversized hook input are inert. Unknown event types are inert too.

**Bare `gpt-reserve` is UNKNOWN and inactive.** This release has no evidence-backed field that proves it is Luna-only. No invented `model_family` or prompt/config word is consulted. A future patch may admit it only after a reliable live host contract is demonstrated, without authorizing non-Luna models. Explicit names containing the versioned Luna marker, such as a Luna reserve suffix, keep their existing classification.

The shell substring prefilter may notice `-luna`, `gpt-reserve` or escaped Unicode anywhere in raw JSON. It may then start Python, but it grants no authorization. Python parses event.model and exits before importing the task engine for non-Luna/unknown input. In normal mode there is no prompt load, workspace scan, alias/crew/task state, permission change, tool rewrite or additional model/process launch after this gate. The optional diagnostic route is a documented exception for bounded diagnostic-only writes, not for task side effects.

## Conditional injection

`CORE.md`, `FIXED_ROOT.md`, `FIXED_WORKER.md` and legacy role documents start with `LUNASTRA_APPLICABILITY`. The combined kernel emits this common guard once, before fixed-seven obligations, with:

- `LUNASTRA_ACTIVATION_ID` and turn-scope fingerprint;
- `LUNASTRA_VERIFIED_MODEL`, `LUNASTRA_ROLE`, `LUNASTRA_SCOPE=LUNA_ONLY`;
- build identity.

These are scope metadata derived from the accepted event. They are not independent host attestation. A fresh accepted Luna user turn refreshes its scope; stale model/role aliases are rejected rather than rebound. Stop/recovery feedback retains its routing markers and adds the same lifetime qualification. `PostCompact` still returns no additionalContext and uses the existing restore path. No new undocumented event or model-switch field is assumed.

## Optional bounded diagnostics

Run from the newly extracted distribution **after you choose to register that build**. These commands never register/approve hooks or launch a model.

| Windows launcher | Equivalent command | Meaning |
|---|---|---|
| `CHECK_MODEL_GATE.cmd` | `python install.py gate-trace` | Arm 300 seconds / 128 events |
| `MODEL_GATE_REPORT.cmd` | `python install.py gate-report` | Export a local allowlisted JSON report |
| `STOP_MODEL_GATE.cmd` | `python install.py gate-stop` | Stop early; preserve captures |
| `CHECK.cmd` | `python install.py doctor` | Read-only installation/observation layers |

On macOS/Linux use `python3`. Custom limits: `python install.py gate-trace --trace-seconds 120 --trace-events 64`. Hard maxima: 900 seconds, 512 events. `python install.py doctor --trace-model-gate` also explicitly arms a capture. Ordinary doctor does not arm one.

Add `--isolated` or `--codex-home "PATH"` to target a particular home; new diagnostic launchers forward those flags. Arming requires matching registered payload/definitions and refuses to install anything itself. If events never arrive, the capture is expired after its deadline, but cleanup of the marker is lazy on the next event; there is no background process. Re-arming after expiry creates a new capture; active re-arming is idempotent and does not extend the budget. Concurrency may drop advisory records when busy, never exceed the cap.

Recorded: time, event type, model, hashed session/agent, role, classifier, additionalContext/kernel/state flags and handler/build metadata. Not recorded: raw prompts, commands, file contents, credentials, transcripts. Exported report payloads omit filesystem paths; redact the local CLI report path before posting screenshots. Hash salts are private per capture. Captures stop on unregister but are retained. Never share auth/config backups or the full runtime DB for this diagnostic.

Interpretation:

| Record | Supported conclusion | Not established |
|---|---|---|
| NON_LUNA + no context/state | This observed event was inert | Every unobserved event or old conversation was clean |
| Luna-named model + kernel emitted | This hook classified and emitted a Luna kernel | UI selection was Luna or model obeyed the text |
| UI Astra + trace Luna model | Investigate actual host event provenance and model routing | Automatically blaming the classifier |
| Non-Luna trace inert but old fixed-seven text still affects model | Consistent with retained context; compare a clean new chat | Retroactive certainty about the original incident |
| No records | No observed evidence | Hooks definitely disabled or no contamination |

## Mixed-model operation

The default registered model-gated mode remains supported: new non-Luna events are inert and new supported-Luna events activate normally. This does not require repeated unregister/install while changing between **clean conversations**.

Optional extra defense is a separate home:

```text
python install.py plan --isolated
python install.py apply --isolated
python install.py doctor --isolated
python install.py unregister --isolated
```

The Windows `INSTALL_LUNA_HOME.cmd`, `CHECK_LUNA_HOME.cmd`, `UNREGISTER_LUNA_HOME.cmd` target `~/.codex-lunastra`. Plan/apply display the bound home. They do not launch Codex, copy login secrets, mutate model settings, remove the default home's hooks or claim Desktop/IDE environment inheritance. To target another explicit path, use `--codex-home` instead of `--isolated`.

Verify effective `CODEX_HOME` in the surface you actually use. A separate PATH CLI test is not Desktop/IDE proof. Project or managed hook layers may exist in addition to a user-home registration. This archive does not provide a supposedly verified Desktop launcher or any profile-based authorization bypass.

## CHECK layers

| Output | Meaning |
|---|---|
| HOOKS_REGISTERED | Exact owned handlers exist in the inspected home |
| LUNA_EVENT_ACCEPTED | Current-payload local accepted-event records exist |
| KERNEL_EMITTED | Current-payload kernel emission was observed locally |
| CREW_ACTIVE last recorded | Stored incomplete crew phases, **not current liveness** |
| Actual Desktop/IDE effective home: UNKNOWN | Not inferable from the handler path or CLI probe |

Names visible in a tool list or UI are not activation evidence. Doctor neither invents current worker liveness nor certifies host model selection.

## Required live acceptance — not performed by the software suite

Use disposable work, preserve running jobs and do not change model reasoning settings. Record observed UI model/surface/build, package fingerprint, scenario and the privacy-safe gate report. Model selection below is performed by the operator, not by the extension.

| Scenario | Operator flow | Required observation |
|---|---|---|
| A | Hooks approved; new Luna; then same conversation switched to non-Luna | Luna emits; non-Luna code route inert; no old fixed-seven refusal |
| B | Luna context; unregister; inspect old chat; new non-Luna chat | Owned hooks absent; old context limitation disclosed; new chat clean |
| C | Unregistered new non-Luna; register; new non-Luna; new Luna | Clean, clean, active respectively |
| D | New non-Luna with normal tool/Stop/other available lifecycle events | No context, permission/input edits, aliases or task state |
| E | Non-Luna child/tool events | No worker binding or alias creation |
| F | Missing/malformed/unknown model events where safely reproducible | Inert output, no task state, no hook crash |
| G | Supported new Luna task | Root plus actual same six IDs, reports/continuation/review unchanged |

There is no honest automatic inference that all scenarios passed just because captures exist. Capture output includes `live_host_verified=false`. A clean new Luna/new Astra pair helps diagnose model values; it does **not** replace the model-switch/unregister lifecycle. Mark unavailable scenarios NOT_RUN, not PASS. If old host context cannot be reliably deactivated, keep new-conversation isolation as the explicit limit.
