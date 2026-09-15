# Upstream test schemas

The `.schema.json` files in this directory are unmodified generated schemas from OpenAI Codex. Copyright 2025 OpenAI. Licensed under the Apache License, Version 2.0; see `Apache-2.0.txt`. LunAstra is an independent project.

Source revision: `4d205c7a4dc36b719679a0356a45b23133732265`.

- `codex-rs/hooks/schema/generated/pre-tool-use.command.output.schema.json`, Git blob `6730b27fd4fc80f8075d64346a554a1cfc94470a`.
- `codex-rs/hooks/schema/generated/subagent-start.command.input.schema.json`, Git blob `2f6edd60387aee5af5573e3683702d94773e2dd1`.

The contract tests also enforce the `updatedInput` / `permissionDecision` semantic restriction implemented in `codex-rs/hooks/src/engine/output_parser.rs`. Native-shaped events are replayed locally; these tests do not call a model.

The unmodified user-prompt-submit.command.input.schema.json is from openai/codex, tag rust-v0.154.0, Git blob 6a10a9f75c19720b0863d11d7d7d80f190e8eacd. It is distributed under the same Apache-2.0 license above.
