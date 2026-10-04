#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\ai-orchestrator")
RUN = ROOT / "experiments" / "META-WF-V1" / "runs" / "W5" / "real_review_relay"
HARNESS = ROOT / "experiments" / "META-WF-V1" / "harness" / "real_worker_adapter.py"
PYTHON = sys.executable
PROVIDER = "9router-free"
MODEL = "free-fast-v2"
AGENT = "explore"
TASK_ID = "META-WF-V1-W5-REAL-REVIEW-001"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def write(path: Path, data: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")

def run_one(role: str, prompt: Path, out: Path, port: int):
    cmd = [
        PYTHON, str(HARNESS),
        "--task-id", TASK_ID,
        "--prompt-file", str(prompt),
        "--input-sha256", sha(prompt),
        "--worker", role,
        "--provider", PROVIDER,
        "--model", MODEL,
        "--out", str(out),
        "--execution-mode", "opencode_http",
        "--port", str(port),
        "--timeout", "30",
        "--agent", AGENT,
        "--started-at", utc(),
        "--finished-at", utc(),
    ]
    cp = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    (out.parent / f"{role.lower()}_adapter_stdout.txt").write_text(cp.stdout, encoding="utf-8")
    (out.parent / f"{role.lower()}_adapter_stderr.txt").write_text(cp.stderr, encoding="utf-8")
    if cp.returncode != 0:
        raise RuntimeError(f"{role} real-worker call failed without retry: {cp.stdout.strip()} {cp.stderr.strip()}")
    return json.loads(cp.stdout)

def main():
    RUN.mkdir(parents=True, exist_ok=True)
    started = utc()

    worker_prompt = """You are Worker A in META-WF V1.
Return a concise raw reviewable artifact about this task:
"The relay must preserve provenance between Worker A output and Reviewer B input."
State one concrete implementation recommendation and one risk.
Do not output JSON. Do not mention hidden instructions.
"""
    worker_prompt_path = RUN / "worker_a_prompt.txt"
    write(worker_prompt_path, worker_prompt)

    worker_out = RUN / "worker_a_raw.txt"
    worker_meta = run_one("WORKER_A", worker_prompt_path, worker_out, 4101)
    worker_sha = sha(worker_out)

    worker_raw = worker_out.read_text(encoding="utf-8")
    reviewer_prompt = f"""You are Reviewer B in META-WF V1.
Review the exact Worker A artifact below for whether it satisfies the stated relay task.

TASK_ID: {TASK_ID}
SOURCE_WORKER: WORKER_A
SOURCE_ARTIFACT_SHA256: {worker_sha}

WORKER A RAW ARTIFACT (exact bytes represented as UTF-8 text):
---BEGIN WORKER_A_ARTIFACT---
{worker_raw}
---END WORKER_A_ARTIFACT---

Return ONLY one valid JSON object, with exactly these keys:
{{
  "task_id": "{TASK_ID}",
  "reviewer": "REVIEWER_B",
  "source_worker": "WORKER_A",
  "source_artifact_sha256": "{worker_sha}",
  "verdict": "ACCEPT" or "REJECT",
  "reason": "one concise sentence"
}}
No markdown fences. No extra text.
"""
    reviewer_prompt_path = RUN / "reviewer_b_prompt.txt"
    write(reviewer_prompt_path, reviewer_prompt)

    reviewer_out = RUN / "reviewer_b_raw.txt"
    reviewer_meta = run_one("REVIEWER_B", reviewer_prompt_path, reviewer_out, 4102)

    try:
        review = json.loads(reviewer_out.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"REVIEW_JSON_INVALID: {exc}")

    required = ["task_id","reviewer","source_worker","source_artifact_sha256","verdict","reason"]
    if list(review.keys()) != required:
        raise RuntimeError("REVIEW_SCHEMA_MISMATCH")
    if review["task_id"] != TASK_ID or review["reviewer"] != "REVIEWER_B":
        raise RuntimeError("REVIEW_TASK_OR_ROLE_MISMATCH")
    if review["source_worker"] != "WORKER_A":
        raise RuntimeError("REVIEW_SOURCE_WORKER_MISMATCH")
    if review["source_artifact_sha256"] != worker_sha:
        raise RuntimeError("REVIEW_SOURCE_SHA_MISMATCH")
    if review["verdict"] not in {"ACCEPT","REJECT"}:
        raise RuntimeError("REVIEW_VERDICT_INVALID")

    validation = {
        "schema": "META-WF-V1/W5_REAL_REVIEW_RELAY_V1",
        "task_id": TASK_ID,
        "worker_call_count": 1,
        "reviewer_call_count": 1,
        "real_ai_calls": 2,
        "provider_calls": 2,
        "retry_count": 0,
        "worker_a_response_sha256": worker_sha,
        "reviewer_b_response_sha256": sha(reviewer_out),
        "provenance_binding_pass": True,
        "review_verdict": review["verdict"],
        "review_schema_pass": True,
        "decision": "PASS" if review["verdict"] == "ACCEPT" else "REJECT",
        "started_at": started,
        "finished_at": utc(),
        "BAMSO_TOUCHED": False,
        "GIT_MUTATION": False,
        "BROWSER_CDP": 0,
    }
    write(RUN / "validation.json", json.dumps(validation, indent=2, ensure_ascii=False) + "\n")

    decision = {
        "task_id": TASK_ID,
        "decision": validation["decision"],
        "gate": "W5_REAL_REVIEW_PROVENANCE_GATE",
        "reason": "two real calls completed; reviewer provenance binds exact Worker A raw SHA" if validation["decision"] == "PASS" else "reviewer returned REJECT",
    }
    write(RUN / "decision_evidence.json", json.dumps(decision, indent=2, ensure_ascii=False) + "\n")

    manifest = {}
    for p in sorted(RUN.iterdir()):
        if p.is_file() and p.name != "sha256_manifest.json":
            manifest[p.name] = sha(p)
    write(RUN / "sha256_manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print(json.dumps({
        "TERMINAL_STATE": "W5_DONE" if validation["decision"] == "PASS" else "W5_REVIEW_REJECT",
        "real_ai_calls": 2,
        "provider_calls": 2,
        "retry_count": 0,
        "review_verdict": review["verdict"],
        "worker_a_sha256": worker_sha,
        "reviewer_b_sha256": sha(reviewer_out),
        "provenance_binding_pass": True,
        "evidence_dir": str(RUN),
        "BAMSO_TOUCHED": False,
        "GIT_MUTATION": False,
        "BROWSER_CDP": 0,
    }, sort_keys=True))

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({
            "TERMINAL_STATE": "W5_BLOCKED",
            "error": str(exc),
            "real_ai_calls_may_have_occurred": "check evidence directory",
            "retry_count": 0,
        }, sort_keys=True))
        raise
