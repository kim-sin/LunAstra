# Fixed-seven stability maintenance

Version: 3.2.0. Build: fixed-seven-stability.2.

This is the automatic hook-based build. No /LunAstra command or solo fallback
is introduced. One root and six persistent native Luna children remain the
contract. A missing child is not certified as a complete seven-session run.

The merge lock now uses one canonical root identity.
Symlink roots are rejected before resolution. Windows fixtures use canonical
temporary roots; separate tests still exercise equivalent path aliases.
Inherited-filter fixtures set core.autocrlf locally before their first commit,
so replacing their global test configuration cannot change newline semantics.
Evidence and metadata connections are now closed even if database setup fails.
Corrupt databases remain errors, with their original bytes preserved.
These fixture settings never alter a user's Git configuration.
The validator resolves its temporary base for its own process and children;
it restores environment and cache values on exit, including exceptions.
This handles macOS /var aliases without relaxing runtime symlink rejection.

The inactive inherited-filter, source fingerprint and worker identity fixes
from the previous publication build are retained. No protocol, model,
reasoning setting, authentication file or approval policy is changed.

Extract the complete installation ZIP into a new folder and run INSTALL.cmd.
Review the updated LunAstra hooks in the actual Codex host. Prefer a disposable
project for the first check. Do not restart unrelated live work. CHECK.cmd
observations and six distinct reused child IDs must both be checked. Synthetic
software tests do not prove live Codex connectivity, eliminate network errors,
or measure Astra Max parity. Network error causes require actual host logs,
not an inference from software-test success.
