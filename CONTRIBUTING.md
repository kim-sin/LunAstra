# Contributing

LunAstra requires Python 3.10+ and Git. The runtime uses the Python standard library; `requirements-dev.txt` contains test-only dependencies.

## Development setup

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
```

Use `tools/validate.py` for a source-fingerprint-aware full run and `tools/release.py` for release packaging checks. Tests should use temporary repositories rather than a live Codex workspace.

## Change requirements

- Add regression coverage for changes to identity, scope, completion, evidence, installation ownership, or hook contracts.
- Preserve user changes and native Codex approval boundaries.
- Keep model selection and reasoning effort unchanged unless a future version explicitly changes the project contract.
- Do not add hidden model calls, telemetry, uncontrolled worker fan-out, destructive process management, automatic trust approval, or implicit remote publication.
- Treat static source navigation as a hint, not a substitute for reading source or running acceptance checks.
- Cite the upstream Codex contract when adding or changing a hook adapter.

Before publishing a release, run the full local suite, verify documentation links and structured files, build the public archive, verify its manifest, scan the public bytes for credentials and private paths, and rerun integration tests from the extracted archive. Hosted CI should pass on the published commit.
