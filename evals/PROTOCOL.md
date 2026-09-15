# Evaluation protocol

The evaluation tools do not call a model. They prepare isolated work directories, record submissions, grade public diagnostics, and compare previously captured runs.

## Stock Luna versus LunAstra

Use the same starting repository, task request, acceptance criteria, Luna model, and reasoning setting for both conditions. Confirm that LunAstra hooks are inactive for the stock condition and active for the LunAstra condition. Use separate workspaces and preserve failed or incomplete runs instead of replacing them.

Define success before running the task. Prefer blinded review when practical. Do not tune the harness on a task and then present that same task as independent evidence.

Record final success, user intervention, leader rework, missed requirements, repeated failures, recovery, wall-clock time, and any usage values that can be observed directly. Parallel worker time must not be added together and reported as elapsed wall time. Unknown usage is `null`, not zero.

## Public diagnostics

Prepare the bundled diagnostics with:

```powershell
py -3 .\evals\evaluate.py prepare --output .\luna-diagnostics --luna-only
```

This creates isolated stock-Luna and LunAstra work directories for eight synthetic software tasks. It does not run a model. Controller mappings, reference implementations, and graders should not be exposed to the task worker.

Submit and grade results with:

```powershell
py -3 .\evals\evaluate.py submit --output .\luna-diagnostics --job JOB_ID --metrics METRICS_JSON
py -3 .\evals\evaluate.py grade --output .\luna-diagnostics
py -3 .\evals\evaluate.py summary --output .\luna-diagnostics
```

The grader uses temporary directories and subprocesses; it is not a security sandbox for untrusted code.

## Recorded-run comparison

`compare.py` pairs stock and LunAstra records by task and trial. Required fields are `task_id`, `trial_id`, `arm`, `condition_id`, `model_id`, `reasoning_setting`, `success`, `source_trace`, and `source_trace_sha256`. Optional fields include `wall_seconds`, `credits`, `input_tokens`, `output_tokens`, `caller_rework`, `user_interventions`, and `failure_category`.

```powershell
py -3 .\evals\compare.py .\records.json --trace-root .\reviewed-traces
```

A pair is invalid if the task conditions, model, or reasoning setting differ. Trace hashes establish byte identity only; they do not certify the interpretation of a result.

## Astra reference runs

Use `--reference astra_reference` to compare LunAstra with separately recorded Astra runs. `condition_id` must still identify the same task, initial state, and acceptance criteria, while `model_id` and reasoning settings record what each run actually used.

Aggregate total elapsed time and observed usage for each condition. Do not infer Astra internals or invent missing usage values. Real model parity and usage savings are outside the bundled synthetic diagnostics and require fresh tasks that were not used to develop the harness.

## Fixed-seven light-Luna comparison

Use three explicitly recorded conditions: stock Luna at the chosen light setting, this fixed-seven build at that same Luna setting, and a separately recorded Astra Max reference. Record the actual model IDs and reasoning settings observed by the host; do not infer them from a display label or overwrite them to pass a comparison. Keep starting files, tools, task request, acceptance criteria and evaluation budget fixed. Include all six child sessions and root usage in the fixed-seven total.

Record six distinct native child IDs, initial spawn acknowledgements and same-ID reuse across phases. A configuration claiming seven without native execution evidence is not a seven-session model run. Measure quality by the same held-out task checks and review, and efficiency by elapsed time and observed usage per accepted deliverable. Include planning, integration, review and repair costs. If Astra itself delegates, record that allocation rather than describing it as a single-model baseline.

No real model runs or Astra Max efficiency result are bundled with this source release. The synthetic local tests are not substitutes for these experiments.

## Native child defaults

Record the effective model and reasoning setting for the parent and all six children, not just the selected UI label. Native `agents.default_subagent_model` and `agents.default_subagent_reasoning_effort` may override a full-history fork. A run with unknown child effort must not be labeled a verified light-Luna condition. Review conflicting defaults explicitly; do not silently alter account configuration to improve a comparison.
