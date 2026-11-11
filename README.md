# natbot-lab: using the "OG natbot" to test browser personal assistants

A fork of [nat/natbot](https://github.com/nat/natbot), Nat Friedman's 2022 browser agent. Nat's original files are kept as they were: `natbot.py`, `LICENSE`, and his README, which you can read [upstream](https://github.com/nat/natbot/blob/main/README.md).

This fork adds:
- natbot ported to Claude (**natbot-2022**);
- 17 lines of fixes (**natbot-plus17**);
- a new 109-line assistant inspired by natbot (**natbot-mini-assist**).

The write-up is in [blog-post.md](blog-post.md).

Results on Claude Haiku 5.5, 25 tasks on 5 sandbox web apps, 3 runs per task:

| agent | lines | passed |
|---|---:|---:|
| natbot-2022 | 639 | 19/75 (25%) |
| natbot-plus17 | 639 + 17 | 30/75 (40%) |
| natbot-mini-assist | 109 | 50/75 (67%) |

| file | what |
|---|---|
| [`natbot.py`](natbot.py) | the original natbot, unchanged (MIT, [`LICENSE`](LICENSE)) |
| [`natbot_extra.py`](natbot_extra.py) | natbot on Claude: the Messages API, an `ANSWER` command, one system line, a step cap, and six optional fixes (`NATBOT_FIXES=coord,row,page,cache,mem,stop`). No fixes = natbot-2022; all six = natbot-plus17. Every change is marked `# EXTRA:` or `#F:<fix>`; `diff natbot.py natbot_extra.py` shows them all. |
| [`natbot_mini.py`](natbot_mini.py) | natbot-mini-assist, the 109-line assistant |
| [`blog-post.md`](blog-post.md) | results and write-up |

## Run

```bash
pip install playwright anthropic && playwright install chromium
export ANTHROPIC_API_KEY=...

# natbot-mini-assist: the task on stdin
echo 'Find the cheapest car and tell me its price' | NATBOT_START_URL=https://example.com python3 natbot_mini.py

# natbot_extra: like the original, it asks for the objective, then waits for Enter before each step;
# piping empty lines after the task runs it unattended
(echo 'Find the cheapest car and tell me its price'; yes '') | NATBOT_START_URL=https://example.com NATBOT_FIXES=mem,stop python3 natbot_extra.py
```

Both scripts:
- open a visible Chromium window;
- stop when the model replies `ANSWER`, or after `NATBOT_MAX_STEPS` steps (default 40);
- write the answer to `answer.txt`, and every model call to `events.jsonl` (natbot-mini-assist) or `natbot-events.jsonl` (natbot_extra).

The model is `NATBOT_MODEL` (default `claude-haiku-5-5`).
