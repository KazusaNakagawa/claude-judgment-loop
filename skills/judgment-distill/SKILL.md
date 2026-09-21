---
name: judgment-distill
description: Use weekly (or on demand) to distill accumulated judgment logs into reusable rules. Reads judgments.jsonl, reconciles against rules.jsonl, and proposes promote/new/retire diffs for human approval. Never auto-overwrites rules.
allowed-tools: Bash(cat:*), Bash(ls:*), Bash(wc:*), Bash(jq:*), Read, Write
---

# judgment-distill — logs → rules (layer 1 → layer 2)

Convert raw judgment logs into generalized, reusable rules. This is the
distillation step of the learning loop. See the repository README.
**The human is the final gate — you propose diffs, you never silently
overwrite `rules.jsonl`.**

## Data location

Everything lives in `$JUDGMENT_LOOP_DIR` (default `~/.local/share/judgment-loop/`),
**outside** your config repo:

- `judgments.jsonl` — input, append-only raw logs (layer 1)
- `rules.jsonl` — output, distilled rules (layer 2)

Resolve the dir first:

```bash
DIR="${JUDGMENT_LOOP_DIR:-$HOME/.local/share/judgment-loop}"
ls -la "$DIR"
```

## Procedure

1. **Load inputs.**
   - Read all of `judgments.jsonl`.
   - Read existing `rules.jsonl` (may be absent → start empty).
   - Determine which logs are *new* since the last distillation. If a
     `.distill-watermark` file exists in `$DIR`, only process logs with `id`
     newer than it; otherwise process everything.

2. **For each new log, decide one of:**

   | operation | condition | result |
   |-----------|-----------|--------|
   | **new** | no existing rule covers it | add as `tentative`, `evidence_count=1` |
   | **evidence++** | matches an existing rule | bump `evidence_count`; cross threshold → propose `active` |
   | **merge** | near-duplicate of another rule | fold into the stronger rule; weaker → `retired`. **Transport evidence**: emit `add_evidence` to move the weaker rule's `source_ids` onto the survivor *before* retiring it — otherwise that evidence and its traceability vanish. `distill-apply` applies ops individually and can't infer the transfer, so this is on you. |
   | **retire** | repeatedly contradicts an `active` rule | surface the contradiction; propose `retired` |

3. **Generalize — mandatory.** For every candidate rule, ask: *"Is this a
   reusable principle, or just this one case?"* If it cannot be stated as a
   general `trigger` + `rule` without naming the specific instance, do **not**
   promote it. Over-fitting is noise.

4. **Present a diff only.** Output three sections — **PROMOTE** (tentative→active),
   **NEW** (tentative additions), **RETIRE** (merges/contradictions) — each with
   the affected `rule_id`(s), the proposed text, and the `source_ids` backing it.
   Then stop and ask the human which entries to apply.

5. **Apply only what the human approved — deterministically.** Do **not**
   rewrite `rules.jsonl` yourself; regenerating the whole file risks silently
   mangling or dropping unrelated `active` rules. Instead, emit the approved
   entries as a structured patch (one op per line) and hand it to `distill-apply`,
   which merges, auto-numbers, and recomputes `evidence_count` from `source_ids`
   deterministically:

   ```bash
   # write only the human-approved ops, then:
   distill-apply "$DIR/patch.jsonl"
   ```

   Patch ops:
   ```jsonc
   {"op":"new","domain":"code-review","trigger":"…","rule":"…","rationale":"…","source_ids":["j_…"]}
   {"op":"add_evidence","rule_id":"r_code_007","source_ids":["j_…"]}
   {"op":"activate","rule_id":"r_code_007"}   // the human-approval gate → active
   {"op":"retire","rule_id":"r_code_003"}
   ```
   `evidence_count` / `source_ids` are derived by the tool, never asserted by you.

   **`activate` is a human gate, not an automatic rule.** `distill-apply` does
   not enforce an evidence threshold (so a human can deliberately promote a
   strong single-source rule). The *guideline* is: don't `activate` until
   `evidence_count` clears the threshold (≥2) **and** you've reviewed it. The
   discipline lives with the human, not the code.

6. **Advance the watermark** to the newest processed log `id`.

7. **Surface the reward.** End by reporting what the loop learned this week —
   "今週これを教えた: r_code_007 …" plus `judge stats` totals — so recording stays
   worth it even before rules are injected back into sessions.

## Rule schema (`rules.jsonl`, one JSON object per line)

```jsonc
{
  "rule_id": "r_code_007",
  "domain": "code-review",
  "trigger": "新機能に着手するとき",
  "rule": "実装・スキャフォールドから入らず、機能要件・設計ドキュメントを先に起こす",
  "rationale": "設計を飛ばすと、レビューで前提から覆されて手戻りが大きくなる",
  "source_ids": ["j_20260612_001", "j_20260823_001"],
  "evidence_count": 2,
  "status": "active",
  "updated_at": "2026-06-21T11:00:00+09:00"
}
```

- `rule_id`: `r_{domain略号}_{連番}` (code, write, work, …).
- `trigger`: **when it applies** — this drives retrieval / path-gate accuracy.
  Be concrete; vague triggers never get retrieved.
- `status`: `tentative` (1 case, not injected) → `active` (multi-evidence +
  human-approved, injected) → `retired` (merged/obsolete, not injected).
- `source_ids`: **never drop these.** A rule without traceable source logs
  can't be verified or retired later.

## Guardrails

- Keep `active` rules to a bounded set. When they grow, merge/retire the
  low-evidence ones rather than letting injection bloat.
- Plain text only — no provider-specific format. Rules must inject unchanged
  under any model.
- Watermark + `source_ids` keep the loop traceable and idempotent across runs.
