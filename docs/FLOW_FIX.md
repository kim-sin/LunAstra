# Fixed-seven continuation repair

Version: 3.2.0. Build: `fixed-seven-flow.1`.

The roster contract is unchanged: one lead plus the same six native children,
activated automatically for Luna. No model, reasoning, account, host permission,
or subagent-default setting is changed. This is not a network reconnect fix.

## Repair

The previous fixed-crew Stop handler issued one continuation and then returned
`continue: false` when `stop_hook_active` was set, even after actual progress.
The same correction also told workers to inspect parent-only `crew-state`.
An empty `crew-next.calls` had no actionable native wait descriptor.

`crew-drive` now returns the state-derived next action: dispatch, native wait,
same-member report recovery, checked integration, phase advance or a concrete
blocker. The root is told the next action immediately after native dispatch and
wait results. Native wait timeouts do not fabricate a report or mark a failure.
The blocking `wait_agent` uses `targets`, with one current member at a time;
all six children may still work concurrently. A singleton result keyed by the
host's agent path can be correlated without guessing a multi-member mapping.

Stop feedback uses actual assignment, report and evidence progress rather than
treating `stop_hook_active` as a failure flag. Repeated immediate corrections
without progress or a genuine blocking wait are bounded at three for the root
and one for a worker. Worker join/report/evidence progress renews its correction.
These are failure exits, never completion; user interruption is always respected.
There is no arbitrary wall-time cutoff for a worker doing a long running task.

When a native member is explicitly observed as completed but omitted a checked
report, `crew-recover SLOT` prepares an exact `send_input` to that same ID and
same ticket. Dispatch acknowledgement, scope, model and input identity are
rechecked transactionally. Two report-recovery attempts per ticket are allowed.
Running, unknown, failed or genuinely blocked members are not blindly restarted.
Reports and tests are never fabricated from a natural-language completion.

Wait results are bound to the exact native call, plan, ticket and dispatch epoch.
Late results cannot mutate a later round or a recovered attempt reusing the ID.
Observed native failures invalidate current checked handbacks, retaining prior
evidence, and cannot bypass phase/completion gates. A new `crew-state.flow`
section separates the next action, report count and observed native state from
the local `running` bookkeeping label.

## Installation and an already-ended turn

Install into the existing Codex settings home with `INSTALL.cmd`, then review
and approve the changed LunAstra hooks in `/hooks`. Do not delete old releases,
worktrees, evidence or other hooks. The application does not retroactively run
an already-ended model turn. After approval, resume that existing conversation
once and tell the root to preserve the current six IDs, refresh `crew-drive`,
and complete the existing goal. Subsequent normal phase transitions must not
need a user to type “continue”. This package does not silently turn off other
hooks or change host trust decisions.

## Verification boundary

Regression tests reproduce the old early-stop conditions before the fix.
They cover partial-finish bypass, independent report submission, same-ID repair,
late responses, malformed schemas, cancellation, failed capacity, preservation
and the full PLAN -> EXECUTE -> REVIEW -> COMPLETE flow from one user request.
Installed subprocess tests use real helper commands, Git and files. Native
model responses in these tests are simulated. Neither software tests nor a
seven-member count certify live model quality or desktop network connectivity.
