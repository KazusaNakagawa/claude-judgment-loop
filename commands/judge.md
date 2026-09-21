---
name: judge
description: Capture a rejection/revision/note into the judgment learning loop (layer 1)
argument-hint: "reject|revise|note --reason \"...\" [--domain d] [--fix \"...\"] [--tags a,b]"
allowed-tools: Bash(judge:*), Bash(bin/judge:*)
---

# judge — capture a judgment

Low-friction capture of a human verdict into the learning loop. Wraps the
`judge` CLI (`bin/judge`, on PATH). The only required input is `--reason`.

## What to do

Run the `judge` CLI with the arguments the user passed in `$ARGUMENTS`.

- If `$ARGUMENTS` already looks complete (a subcommand + `--reason`), run it as-is:
  ```bash
  judge $ARGUMENTS
  ```
- If the user described a judgment in prose instead of flags, translate it:
  pick the subcommand (`reject` / `revise` / `note`), distill the core `--reason`
  in one line, add `--fix` when there is a correction, and infer `--domain`
  (e.g. code-review / workflow / security / writing) from context. Then run it.
- `--domain` is inherited from the last logged event when omitted, so prefer
  leaving it off if the session already established one.

## Subcommands

| subcommand | verdict recorded |
|-----------|------------------|
| `reject`  | `rejected` |
| `revise`  | `revised` (pair with `--fix`) |
| `note`    | `accepted-with-note` |

## Examples

```bash
/judge reject --domain code-review --reason "新機能は実装から入らず、設計ドキュメントを先に起こす"
/judge revise --reason "ドキュメントに個人の絶対パスをコミットした" --fix "パスは書かず、ファイルの所在・性質で説明する"
/judge note --reason "改修したら関連 docs に乖離がないか確認し、同じ PR で更新する"
```

After running, report the printed event id back to the user so it can be traced.
