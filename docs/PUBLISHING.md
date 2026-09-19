# Publishing

## Repository source

Use `LunAstra-4.3.0-source.zip`. Extract it and put the contents of its `LunAstra` directory at the repository root, including `.github`, `.gitignore` and `.gitattributes`. Do not upload only a ZIP as the repository source.

`MANIFEST.sha256.json` is generated for the installable release archive only. It is not part of the repository source and is ignored by Git. If it was already committed from an earlier archive, remove it from Git tracking; an ignore entry does not untrack a committed file.

Review the staged file list. Do not publish your Codex home, account files, transcripts, runtime state, worktrees, task output or test logs. Review your Git author/email settings separately when personal attribution must remain private. No local scanner can control metadata on your GitHub account.

## Local checks

From the repository root:

```sh
python3 -m pip install -r requirements-dev.txt
python3 tools/validate.py --output ../lunastra-validation
python3 tools/release.py --source-output ../LunAstra-4.3.0-source.zip
python3 tools/release.py --output ../LunAstra-4.3.0.zip
python3 tools/release.py --verify ../LunAstra-4.3.0.zip
```

Use fresh output names/directories so previous evidence is not overwritten. Run the full suite from the final extracted installable ZIP as well. The repository workflow performs software tests on Windows, Linux and macOS, rebuilds the archives, verifies the release and reruns integration paths. Hosted results are unknown until the workflow has actually run on the uploaded commit.

## Release assets

Attach the installable `LunAstra-4.3.0.zip` and its SHA-256 file to a GitHub release. The `-source.zip` is for source upload and has no manifest; do not pass it to the installable archive verifier. Both contain the same code. Generate the checksum from the actual final archive, for example with PowerShell `Get-FileHash -Algorithm SHA256` or `sha256sum`.

Mark the public release as a preview until native first-use checks have been recorded for the operating systems you claim as verified. Keep `docs/COMPATIBILITY.md` and the release notes aligned with observed results. Do not present a local software test count as live Codex validation, model quality or usage savings.

The normal CI jobs have read-only repository permissions. A separate `publish-preview` job runs only after the full matrix passes, on a main-branch push to `kim-sin/LunAstra` whose commit message explicitly includes `[release]`. That maintainer opt-in authorizes publication of the tested commit, installable/source ZIPs and checksums as a prerelease. Ordinary commits, pull requests and forks do not publish releases. Existing releases are not overwritten. This repository-maintenance job is not installed into users' Codex environments.
