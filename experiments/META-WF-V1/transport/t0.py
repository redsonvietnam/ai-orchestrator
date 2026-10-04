#!/usr/bin/env python3
# transport/t0.py — T0 send-fidelity harness (hash/file/verdict bookkeeping).
# Browser-side extraction is done by the operator; this script:
#   prepare  — freeze canary + F5 fixture prompts, hash them
#   verify   — one (provider, prompt) exchange: fidelity, extraction,
#              session identity, fail-loud; writes run files + T0_RESULT.json
# Never logs cookies/api keys/session secrets (request.raw = prompt text only).
import hashlib, json, re, sys, datetime
from pathlib import Path

R = Path(__file__).resolve().parents[1]
T0DIR = R / "transport" / "t0"
EXPECTED_URL = {
    "chatgpt": "https://chatgpt.com/c/6ac01362-d820-83ec-8eb9-94a768e9418e",
    "claude": "https://claude.ai/chat/8f292e1f-5ec2-4f18-bd8e-105bf5c7acf8",
}
CANARY = (
    "META-WF V1 T0 CANARY. Reply with exactly this line and nothing else:\n"
    "T0-CANARY-OK-8f3a2c"
)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def build_f5_prompt() -> str:
    tdir = R / "tasks" / "F5"
    parts = ["META-WF V1 T0 FIXTURE PROMPT (F5 bundle transport test).",
             "Goal: verify large multi-file prompt fidelity end-to-end.",
             "Artifact bundle follows. After reading, reply with the exact line",
             "T0-F5-OK-8f3a2c and nothing else.",
             ""]
    for rel in sorted(str(p.relative_to(tdir)).replace("\\", "/")
                      for p in tdir.rglob("*") if p.is_file()):
        if rel.endswith(("metadata.json", "SHA256SUMS")):
            continue
        parts.append(f"===== FILE: tasks/F5/{rel} =====")
        parts.append((tdir / rel).read_text(encoding="utf-8", errors="replace"))
        parts.append("===== END FILE =====")
        parts.append("")
    return "\n".join(parts)


def cmd_prepare():
    T0DIR.mkdir(parents=True, exist_ok=True)
    prompts = {
        "canary": CANARY,
        "f5": build_f5_prompt(),
    }
    meta = {}
    for name, text in prompts.items():
        (T0DIR / f"prompt_{name}.raw").write_bytes(text.encode("utf-8"))
        meta[name] = {"sha256": sha256_bytes(text.encode("utf-8")),
                      "chars": len(text)}
    (T0DIR / "prompts.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"prepared": meta}, indent=2))


def read_staging(provider: str, prompt: str) -> Path:
    d = T0DIR / "staging" / f"{provider}_{prompt}"
    if not d.exists():
        sys.exit(f"missing staging dir: {d}")
    return d


def cmd_verify(provider: str, prompt: str):
    if provider not in EXPECTED_URL:
        sys.exit(f"unknown provider {provider}")
    prompts = json.loads((T0DIR / "prompts.json").read_text(encoding="utf-8"))
    staging = read_staging(provider, prompt)
    run_dir = T0DIR / "runs" / provider / prompt
    run_dir.mkdir(parents=True, exist_ok=True)

    prompt_text = (T0DIR / f"prompt_{prompt}.raw").read_text(encoding="utf-8")
    prompt_sha = prompts[prompt]["sha256"]

    result = {"provider": provider, "prompt": prompt,
              "prompt_sha256_expected": prompt_sha,
              "checks": {}, "status": "ok", "fail_reasons": []}

    # --- composer readback (fidelity) -------------------------------------
    cb_path = staging / "composer_readback.txt"
    if not cb_path.exists():
        result["status"] = "fail"
        result["fail_reasons"].append("composer_readback missing")
        cb = None
    else:
        cb = cb_path.read_text(encoding="utf-8", errors="replace")
        ok = norm(cb) == norm(prompt_text)
        result["checks"]["prompt_fidelity"] = ok
        if not ok:
            result["status"] = "fail"
            result["fail_reasons"].append(
                f"composer mismatch: readback_sha={sha256_bytes(norm(cb).encode())} "
                f"expected_norm_sha={sha256_bytes(norm(prompt_text).encode())}")

    # --- thread url (session identity) ------------------------------------
    url_path = staging / "thread_url.txt"
    if not url_path.exists():
        result["status"] = "fail"
        result["fail_reasons"].append("thread_url missing")
        url = ""
    else:
        url = url_path.read_text(encoding="utf-8").strip()
        # identity: same site + (expected thread id present in URL)
        exp = EXPECTED_URL[provider]
        ok = url.startswith(exp.split("?")[0].rstrip("/")) or (
            provider == "chatgpt" and "/c/" in url) or (
            provider == "claude" and "/chat/" in url)
        # strict: require exact thread match when it's the expected thread
        strict_ok = exp.split("?")[0].rstrip("/") in url or url.split("?")[0].rstrip("/") == exp.split("?")[0].rstrip("/")
        result["checks"]["session_identity"] = bool(strict_ok)
        result["thread_url"] = url
        if not strict_ok:
            result["status"] = "fail"
            result["fail_reasons"].append(f"thread url mismatch: {url}")

    # --- response extraction ----------------------------------------------
    resp_path = staging / "response_text.txt"
    timing_path = staging / "timing.json"
    if not resp_path.exists():
        result["status"] = "fail"
        result["fail_reasons"].append("response_text missing")
        resp = ""
    else:
        resp = resp_path.read_text(encoding="utf-8", errors="replace")
        if not resp.strip():
            result["status"] = "fail"
            result["fail_reasons"].append("empty response")

    timing = {}
    if timing_path.exists():
        timing = json.loads(timing_path.read_text(encoding="utf-8"))

    # --- write run files + hashes -----------------------------------------
    request_raw = run_dir / "request.raw"
    response_raw = run_dir / "response.raw"
    request_raw.write_bytes(prompt_text.encode("utf-8"))
    response_raw.write_bytes(resp.encode("utf-8"))

    resp_sha = sha256_bytes(response_raw.read_bytes())
    req_sha = sha256_bytes(request_raw.read_bytes())
    hashes_ok = (req_sha == prompt_sha)
    result["checks"]["response_extraction"] = bool(resp.strip())
    result["prompt_sha256"] = req_sha
    result["response_sha256"] = resp_sha
    if not hashes_ok:
        result["status"] = "fail"
        result["fail_reasons"].append("request.raw sha != frozen prompt sha")

    meta = {
        "provider": provider,
        "model": timing.get("model") or "t0-unrecorded",
        "transport": "playwright_browser_adapter",
        "account_alias": "primary",
        "started_at": timing.get("started_at"),
        "finished_at": timing.get("finished_at"),
        "prompt_sha256": req_sha,
        "response_sha256": resp_sha,
        "artifact_refs": [],
        "status": "ok" if result["status"] == "ok" else "fail",
        "thread_url": url,
        "t0": True,
    }
    (run_dir / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    sums = "\n".join(f"{sha256_bytes((run_dir / f).read_bytes())}  {f}"
                     for f in ("request.raw", "response.raw", "metadata.json")) + "\n"
    (run_dir / "SHA256SUMS").write_text(sums, encoding="utf-8")

    result["checks"]["fail_loud"] = True  # this record exists; status/fail_reasons carry loudness
    (staging / "verify_result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    # merge into T0_RESULT.json
    overall_path = T0DIR / "T0_RESULT.json"
    overall = {"verdict": "PENDING", "exchanges": {},
               "canary_human_confirmation": "PENDING"}
    if overall_path.exists():
        overall = json.loads(overall_path.read_text(encoding="utf-8"))
    key = f"{provider}_{prompt}"
    overall["exchanges"][key] = result
    bad = [k for k, v in overall["exchanges"].items() if v["status"] != "ok"]
    overall["verdict"] = "PENDING" if len(overall["exchanges"]) < 4 else (
        "FAIL" if bad else "PASS")
    if bad:
        overall["verdict"] = "FAIL"
    overall["updated_at"] = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")
    overall_path.write_text(json.dumps(overall, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


JS_DIR = Path(__file__).resolve().parent / "js" / "gen"

FILL_TMPL = """// generated by t0.py gen — fill composer, return readback text
const TEXT = __TEXT__;
const el = document.querySelector('[data-testid="chat-input"]')
  || document.querySelector('[contenteditable="true"][aria-label*="Chat"]')
  || document.querySelector('div[contenteditable="true"].ProseMirror')
  || document.querySelector('div[contenteditable="true"]');
if (!el) throw new Error("composer not found");
el.focus();
await new Promise(r => setTimeout(r, 150));
document.execCommand("selectAll", false, null);
document.execCommand("insertText", false, TEXT);
await new Promise(r => setTimeout(r, 250));
return el.innerText;
"""

SEND_TMPL = """// generated by t0.py gen — click send, return started_at
const btn = document.querySelector('button[data-testid="send-button"]')
  || document.querySelector('button[data-testid="chat-input-send"]')
  || document.querySelector('button[aria-label="Send message"]')
  || document.querySelector('button[aria-label="Send Message"]');
if (!btn) throw new Error("send button not found");
if (btn.disabled) throw new Error("send button disabled");
btn.click();
return { clicked: true, started_at: new Date().toISOString() };
"""

PRESEND_TMPL = """// generated by t0.py gen — snapshot last ASSISTANT message before send
const pickLast = () => {
  const turns = document.querySelectorAll('[data-testid^="conversation-turn"]');
  if (turns.length) {
    for (let i = turns.length - 1; i >= 0; i--) {
      const t = turns[i];
      const isUser = t.querySelector('[data-testid="collapsible-user-message-root"], [data-testid="user-turn"], [data-testid="user-message"]');
      if (isUser) continue;
      const md = t.querySelector('.markdown');
      const txt = ((md || t).innerText || "").trim();
      if (txt) return txt;
    }
    return "";
  }
  const nodes = document.querySelectorAll(
    '[data-testid="assistant-message"], article');
  const last = nodes.length ? nodes[nodes.length - 1] : null;
  return last ? (last.innerText || "") : "";
};
return pickLast();
"""

EXTRACT_TMPL = """// generated by t0.py gen — wait for stream end + 2s stability, extract text
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PRE = __PRE__;
const pickLast = () => {
  const turns = document.querySelectorAll('[data-testid^="conversation-turn"]');
  if (turns.length) {
    for (let i = turns.length - 1; i >= 0; i--) {
      const t = turns[i];
      const isUser = t.querySelector('[data-testid="collapsible-user-message-root"], [data-testid="user-turn"], [data-testid="user-message"]');
      if (isUser) continue;
      const md = t.querySelector('.markdown');
      const txt = ((md || t).innerText || "").trim();
      if (txt) return txt;
    }
    return "";
  }
  const nodes = document.querySelectorAll(
    '[data-testid="assistant-message"], article');
  const last = nodes.length ? nodes[nodes.length - 1] : null;
  return last ? (last.innerText || "") : "";
};
const streamingGone = () => {
  const s = document.querySelector('.result-streaming')
    || document.querySelector('[data-testid="result-streaming"]');
  const stop = document.querySelector('button[aria-label*="Stop"]')
    || document.querySelector('button[data-testid="stop-button"]')
    || document.querySelector('button[aria-label*="stop"]')
    || document.querySelector('button[aria-label*="Dừng"]');
  return !s && !stop;
};
let prev = pickLast(), stableSince = Date.now(), changed = prev !== PRE;
for (let i = 0; i < 150; i++) {
  const cur = pickLast();
  if (cur && cur !== PRE) changed = true;
  if (changed && streamingGone() && cur && cur === prev) {
    if (Date.now() - stableSince >= 2000) break;
  } else {
    if (cur !== prev) stableSince = Date.now();
    prev = cur;
  }
  await sleep(1000);
}
const text0 = pickLast();
if (!text0 || text0 === PRE) throw new Error("no new response extracted (timeout)");
// post-capture stability verification: re-read after 4s; if changed, keep
// polling (guards against mid-stream pauses > stability window)
let text = text0;
for (let k = 0; k < 20; k++) {
  await sleep(4000);
  const again = pickLast();
  if (again === text) break;
  if (!again || again === PRE) throw new Error("response vanished during verification");
  text = again;
}
const modelEl = document.querySelector('[data-testid="model-switcher-button"]')
  || document.querySelector('button[aria-haspopup="menu"][aria-label*="mode" i]');
return { text, finished_at: new Date().toISOString(),
         model: modelEl ? (modelEl.innerText || "").trim().slice(0, 80) : null };
"""


def cmd_gen(provider: str, prompt: str, pre_file: str | None = None):
    JS_DIR.mkdir(parents=True, exist_ok=True)
    prompt_text = (T0DIR / f"prompt_{prompt}.raw").read_text(encoding="utf-8")
    writes = {
        f"fill_{provider}_{prompt}.js": FILL_TMPL.replace("__TEXT__", json.dumps(prompt_text)),
        f"send_{provider}.js": SEND_TMPL,
        f"presend_{provider}.js": PRESEND_TMPL,
    }
    pre = ""
    if pre_file:
        pre = Path(pre_file).read_text(encoding="utf-8", errors="replace")
    writes[f"extract_{provider}_{prompt}.js"] = EXTRACT_TMPL.replace(
        "__PRE__", json.dumps(pre))
    for name, body in writes.items():
        (JS_DIR / name).write_text(body, encoding="utf-8")
    print(json.dumps({"generated": sorted(writes)}, indent=2))


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: t0.py prepare | gen <provider> <prompt> [--pre-file f] | verify <provider> <prompt>")
    if sys.argv[1] == "prepare":
        cmd_prepare()
    elif sys.argv[1] == "gen":
        pre = None
        if "--pre-file" in sys.argv:
            pre = sys.argv[sys.argv.index("--pre-file") + 1]
        cmd_gen(sys.argv[2], sys.argv[3], pre)
    elif sys.argv[1] == "verify":
        cmd_verify(sys.argv[2], sys.argv[3])
    else:
        sys.exit(f"unknown cmd {sys.argv[1]}")


if __name__ == "__main__":
    main()
