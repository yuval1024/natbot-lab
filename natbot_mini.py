#!/usr/bin/env python3
"""natbot-mini-assist: a ~100-line browser personal assistant, for testing models (2026-11-11).
Same command grammar and transcript format as natbot_extra.py. Differences: whole-page element list with roles, values and
row context; click by element, not pixel; a short history of commands with their results; a verify-then-ANSWER rule."""
import json, os, sys, time
from playwright.sync_api import sync_playwright

SYSTEM = """You are a personal assistant controlling a web browser for the user. Each turn you get the task, your history
(commands you ran and what happened), the current URL, and the page as a list of elements: [id] role "name" (value) {row}.
Reply with exactly one command and nothing else:
CLICK id | TYPE id "text" | TYPESUBMIT id "text" (types, then presses Enter) | SCROLL DOWN | SCROLL UP | GOTO url | ANSWER "text"
Do only what the task asks. After a change, check on the page that it worked. Do not repeat a command that already worked.
When the task is done, or it asks a question you can answer from the page, reply ANSWER with the final answer."""

SNAPSHOT_JS = r"""() => {
  const out = [], seen = new Set(); let n = 0;
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const name = e => (e.getAttribute('aria-label') || e.labels?.[0]?.innerText || e.getAttribute('placeholder') ||
    e.getAttribute('title') || e.innerText || e.value || '').replace(/\s+/g, ' ').trim().slice(0, 80);
  const SEL = 'a[href],button,input,select,textarea,[role=button],[role=switch],[role=checkbox],[role=tab],[role=link],[role=menuitem],[role=option],[contenteditable=true]';
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  for (let x = walker.currentNode; x; x = walker.nextNode()) {
    if (x.nodeType === 3) { const t = x.textContent.replace(/\s+/g, ' ').trim(), p = x.parentElement;
      if (t && p && !p.closest(SEL) && vis(p) && !seen.has(p)) { seen.add(p); out.push('  ' + t.slice(0, 120)); } continue; }
    if (!x.matches(SEL) || !vis(x) || x.closest('[aria-hidden=true]')) continue;
    x.setAttribute('data-mini-id', ++n);
    const role = x.getAttribute('role') || ({A: 'link', INPUT: x.type || 'input'}[x.tagName] || x.tagName.toLowerCase());
    let val = x.tagName === 'SELECT' ? x.options[x.selectedIndex]?.text : ['INPUT', 'TEXTAREA'].includes(x.tagName) ? x.value : '';
    if (x.type === 'checkbox' || x.type === 'radio') val = x.checked ? 'checked' : 'unchecked';
    if (x.getAttribute('aria-checked')) val = 'checked=' + x.getAttribute('aria-checked');
    let row = x.closest('tr,[role=row]'), nm = name(x);  // row context: the table row, else the largest box with no other same-named control
    if (!row) { row = x; while (row.parentElement && row.parentElement !== document.body && [...row.parentElement.querySelectorAll(SEL)].filter(e => name(e) === nm).length === 1) row = row.parentElement; }
    const rt = row && row !== x ? row.innerText.replace(/\s+/g, ' ').trim().slice(0, 90) : '';
    out.push(`[${n}] ${role} "${name(x)}"` + (val ? ` (${val})` : '') + (rt ? ` {row: ${rt}}` : '') + (x.disabled ? ' disabled' : ''));
  }
  return out.join('\n');
}"""

MODEL, LOGF = os.environ.get("NATBOT_MODEL", "claude-haiku-5-5"), open(os.environ.get("NATBOT_LOG", "events.jsonl"), "a")
OAI = not MODEL.startswith("claude-")
if OAI:
    import openai
    client = openai.OpenAI(base_url=os.environ.get("NATBOT_OAI_BASE", "https://openrouter.ai/api/v1"), max_retries=4)
else:
    import anthropic
    client = anthropic.Anthropic(max_retries=4)


def log(**kw):
    kw["t"] = int(time.time() * 1000); LOGF.write(json.dumps(kw) + "\n"); LOGF.flush()


def ask(user):
    t0 = int(time.time() * 1000)
    if OAI:
        r = client.chat.completions.create(model=MODEL, max_tokens=300, extra_body={"reasoning": {"effort": os.environ.get("NATBOT_OAI_EFFORT", "minimal")},
            "usage": {"include": True}}, messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])
        text, u = r.choices[0].message.content or "", r.usage
        usage, cost = {"input": u.prompt_tokens, "cache_read": 0, "cache_write": 0, "output": u.completion_tokens}, (u.model_extra or {}).get("cost")
    else:
        kw = {"output_config": {"effort": "low"}, "max_tokens": 4000} if "opus" in MODEL else {"thinking": {"type": "disabled"}, "max_tokens": 300}
        r = client.messages.create(model=MODEL, system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                                   messages=[{"role": "user", "content": user}], **kw)
        text, u, cost = "".join(b.text for b in r.content if b.type == "text"), r.usage, None
        usage = {"input": u.input_tokens, "cache_read": u.cache_read_input_tokens or 0, "cache_write": u.cache_creation_input_tokens or 0, "output": u.output_tokens}
    log(ev="llm", t0=t0, text=text, usage=usage, cost_usd=cost, content=user)
    return next((l.strip().strip("`") for l in text.splitlines() if l.strip().strip("`").split(" ")[0] in
                 ("CLICK", "TYPE", "TYPESUBMIT", "SCROLL", "GOTO", "ANSWER")), text.strip())


def act(page, cmd):
    op, _, rest = cmd.partition(" ")
    el = lambda: page.locator(f'[data-mini-id="{rest.split(" ")[0]}"]').first
    text = rest.split(" ", 1)[1].strip().strip('"') if " " in rest else ""
    if op == "CLICK": el().click(timeout=5000)
    elif op in ("TYPE", "TYPESUBMIT"):
        el().fill(text, timeout=5000)
        if op == "TYPESUBMIT": el().press("Enter")
    elif op == "SCROLL": page.mouse.wheel(0, 800 if "DOWN" in rest else -800)
    elif op == "GOTO": page.goto(rest.strip())
    else: return "not a command; reply with exactly one command"
    page.wait_for_load_state(); time.sleep(1)
    return "ok"


def main():
    task, history = sys.stdin.readline().strip(), []
    with sync_playwright() as p:
        page = p.chromium.launch(headless=False).new_page(viewport={"width": 1280, "height": 1080})
        page.goto(os.environ["NATBOT_START_URL"]); page.wait_for_load_state(); time.sleep(1)
        for n in range(1, int(os.environ.get("NATBOT_MAX_STEPS", "40")) + 1):
            log(ev="turn_start", n=n)
            snap = page.evaluate(SNAPSHOT_JS)[:20000]
            cmd = ask(f"TASK: {task}\n\nHISTORY:\n" + ("\n".join(history[-15:]) or "(none)") + f"\n\nURL: {page.url}\n\nPAGE:\n{snap}\n\nYOUR COMMAND:")
            if cmd.startswith("ANSWER"):
                ans = cmd[6:].strip().strip('"')
                open(os.environ.get("NATBOT_ANSWER", "answer.txt"), "w").write(ans); log(ev="answer", text=ans); return
            t0 = int(time.time() * 1000)
            try: res = act(page, cmd)
            except Exception as e: res = "error: " + str(e).split("\n")[0][:150]
            line = next((l for l in snap.splitlines() if l.startswith(f"[{cmd.split(' ')[1]}]")), "") if cmd.split(" ")[0] in ("CLICK", "TYPE", "TYPESUBMIT") and " " in cmd else ""
            history.append(f"{n}. {cmd} -> {res}" + (f"  (on {line[:100]})" if line else ""))
            log(ev="cmd", t0=t0, cmd=cmd, ok=res == "ok", err=None if res == "ok" else res)
        log(ev="step_cap", n=n); sys.exit(3)


if __name__ == "__main__":
    main()
