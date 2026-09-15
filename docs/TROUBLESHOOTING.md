# Troubleshooting

## Installation was refused because of a Codex version

An earlier 3.2.0 distribution treated the CLI on PATH as the active Codex host and enforced a version cutoff. The current maintenance distribution removes that gate. Install it from a new extracted folder. Do not delete the existing installation, settings or work to bypass the earlier message.

The package version remains 3.2.0. Compare the distribution checksum and installer fingerprint to distinguish copies. A version message alone does not establish which engine your desktop app uses or whether it supports the needed hooks.

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
