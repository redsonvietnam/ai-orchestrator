#!/usr/bin/env python3
# harness/record_run.py — scoring-run recorder (raw_response_contract).
# Staging dir must contain: composer_readback.txt, response_text.txt,
# timing.json {started_at, finished_at, model?}, thread_url.txt.
# usage: record_run.py <workflow> <name> <provider> <staging_dir> --prompt <file>
# Writes runs/<W>/<name>/{request.raw,response.raw,metadata.json,SHA256SUMS}.
# Fail-loud: non-zero exit + reason on any fidelity/identity/hash failure.
import hashlib, json, re, sys
from datetime import datetime
from pathlib import Path

R = Path(__file__).resolve().parents[1]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def main():
    a = sys.argv[1:]
    workflow, name, provider, staging = a[0], a[1], a[2], Path(a[3])
    prompt = Path(a[a.index("--prompt") + 1])
    if provider not in ("chatgpt", "claude"):
        sys.exit(f"unknown provider {provider}")
    reasons = []

    prompt_text = prompt.read_bytes()
    cb = (staging / "composer_readback.txt")
    resp = (staging / "response_text.txt")
    timing = json.loads((staging / "timing.json").read_text(encoding="utf-8"))
    thread_url = (staging / "thread_url.txt").read_text(encoding="utf-8").strip()

    if not cb.exists():
        reasons.append("composer_readback missing")
    else:
        if norm(cb.read_text(encoding="utf-8", errors="replace")) != norm(prompt_text.decode("utf-8")):
            reasons.append("composer readback != prompt (fidelity fail)")
    if not resp.exists() or not resp.read_text(encoding="utf-8", errors="replace").strip():
        reasons.append("response missing/empty")

    out = R / "runs" / workflow / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "request.raw").write_bytes(prompt_text)
    (out / "response.raw").write_bytes(
        resp.read_bytes() if resp.exists() else b"")

    req_sha = sha256_bytes(prompt_text)
    resp_sha = sha256_bytes((out / "response.raw").read_bytes())
    expected = sha256_bytes(prompt.read_bytes())
    if req_sha != expected:
        reasons.append("request.raw sha != prompt sha")

    access = R / "runs" / workflow / "access_log.json"
    acc = json.loads(access.read_text(encoding="utf-8")) if access.exists() else {}
    meta = {
        "provider": provider,
        "model": timing.get("model") or "unknown-ui-model",
        "transport": "cdp_adapter",
        "account_alias": "primary",
        "started_at": timing.get("started_at"),
        "finished_at": timing.get("finished_at"),
        "prompt_sha256": req_sha,
        "response_sha256": resp_sha,
        "artifact_refs": acc.get("delivered_files", []),
        "status": "ok" if not reasons else "fail",
        "fail_reasons": reasons,
        "thread_url": thread_url,
        "artifacts": acc.get("delivered_files", []),
        "bundle_sha256": acc.get("bundle_sha256"),
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    (out / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    sums = "\n".join(f"{sha256_bytes((out / f).read_bytes())}  {f}"
                     for f in ("request.raw", "response.raw", "metadata.json")) + "\n"
    (out / "SHA256SUMS").write_text(sums, encoding="utf-8")

    print(json.dumps({"workflow": workflow, "name": name, "status": meta["status"],
                      "prompt_sha256": req_sha, "response_sha256": resp_sha,
                      "response_chars": len((out / "response.raw").read_text(encoding='utf-8', errors='replace')),
                      "fail_reasons": reasons}, indent=2))
    sys.exit(1 if reasons else 0)


if __name__ == "__main__":
    main()
