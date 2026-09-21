## Judgment learning loop
Only when the human *explicitly* rejects, corrects, or flags something to keep —
never on your own inference — capture it with the `judge` CLI (or `/judge`):
one line of `--reason` is enough; other fields are optional. The log is the
human's judgment, so don't put your guesses in it. This feeds the learning loop
(logs → `judgment-distill` → rules). `judge stats` shows the cumulative count.
Don't paste rule bodies here.
