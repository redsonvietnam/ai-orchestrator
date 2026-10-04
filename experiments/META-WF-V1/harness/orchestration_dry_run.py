#!/usr/bin/env python3
"""META-WF V1 deterministic orchestration dry-run.

This is plumbing-only: it consumes persisted W2 evidence, uses an explicit
UNAVAILABLE Claude marker, and never invokes an AI transport or scoring path.
Logical timestamps are derived from persisted ChatGPT evidence so identical
inputs produce byte-identical state/artifact graphs.
"""
import argparse
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "runs" / "W2" / "dry_run" / "orchestration_dry_run.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iso_add(ts: str, seconds: int) -> str:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (dt + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def artifact(path: Path, producer: str, role: str) -> dict:
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "sha256": sha256(path),
        "producer": producer,
        "role": role,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    manifest_p = ROOT / "runs/W2/run_manifest.json"
    reconciliation_p = ROOT / "runs/W2/chatgpt/state_transition_reconciliation.json"
    chat_meta_p = ROOT / "runs/W2/chatgpt/metadata.json"
    raw_binding_p = ROOT / "runs/W2/raw_artifact_binding.json"
    claude_binding_p = ROOT / "runs/W2/claude_artifact_binding.json"
    claude_prompt_p = ROOT / "runs/W2/prompts/claude.txt"

    manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
    chat_meta = json.loads(chat_meta_p.read_text(encoding="utf-8"))
    reconciliation = json.loads(reconciliation_p.read_text(encoding="utf-8"))

    if manifest.get("status") != "CHATGPT_SUBMITTED":
        raise SystemExit("DRY_RUN_BLOCKED: expected persisted W2 state CHATGPT_SUBMITTED")
    if not (chat_meta.get("status") == "ok"
            and chat_meta.get("send_performed") is True
            and chat_meta.get("extraction_status") == "EXTRACTION_PASS"
            and chat_meta.get("stream_ended") is True
            and chat_meta.get("stable") is True):
        raise SystemExit("DRY_RUN_BLOCKED: ChatGPT persisted evidence is not complete")
    if manifest.get("claude_started") is not False:
        raise SystemExit("DRY_RUN_BLOCKED: Claude is not in the required unstarted state")
    if any(manifest.get(k) for k in ("cross_review_started", "decision_started", "w3_started")):
        raise SystemExit("DRY_RUN_BLOCKED: downstream real execution already started")

    raw_binding = json.loads(raw_binding_p.read_text(encoding="utf-8"))
    bundle_sha = raw_binding.get("bundle_sha256")
    if bundle_sha != manifest.get("bundle_sha256"):
        raise SystemExit("DRY_RUN_BLOCKED: raw bundle anchor mismatch")
    if sha256(claude_prompt_p) != manifest.get("claude_prompt_sha256"):
        raise SystemExit("DRY_RUN_BLOCKED: Claude prompt hash mismatch")

    chat_art = artifact(chat_meta_p, "chatgpt", "persisted_execution_evidence")
    recon_art = artifact(reconciliation_p, "orchestrator_reconciliation", "state_reconciliation")
    raw_art = artifact(raw_binding_p, "freeze", "frozen_input_bundle")
    claude_bind_art = artifact(claude_binding_p, "orchestrator", "Claude_readiness_binding")
    claude_prompt_art = artifact(claude_prompt_p, "freeze", "frozen_Claude_prompt")

    start = chat_meta["finished_at"]
    ts = [start]
    for _ in range(7):
        ts.append(iso_add(ts[-1], 1))

    transitions = []
    def add(before, after, t, producer, refs, reason):
        transitions.append({
            "state_before": before,
            "state_after": after,
            "upstream_artifact_references": refs,
            "producer": producer,
            "timestamp": t,
            "deterministic_reason": reason,
        })

    add("PACKAGE_READY", "CHATGPT_SUBMITTED", ts[0],
        "persisted_execution_evidence",
        [raw_art, chat_art, recon_art],
        "Persisted ChatGPT execution is complete and reconciliation proves send_performed=true.")

    claude_placeholder = {
        "path": "runs/W2/dry_run/CLAUDE_REVIEW_UNAVAILABLE.marker",
        "sha256": None,
        "producer": "dry_run",
        "role": "explicit_non_reviewer_placeholder",
        "status": "UNAVAILABLE",
    }
    add("CHATGPT_SUBMITTED", "CLAUDE_SUBMITTED", ts[1],
        "dry_run",
        [chat_art, claude_bind_art, claude_prompt_art, raw_art, claude_placeholder],
        "Simulate only the state transition; no Claude request or reviewer output exists.")

    add("CLAUDE_SUBMITTED", "CROSS_REVIEW_ELIGIBLE", ts[2],
        "dry_run",
        [chat_art, claude_placeholder],
        "Plumbing eligibility requires two first-pass slots; Claude is represented only by an explicit UNAVAILABLE marker.")

    cross_placeholder = {
        "path": "runs/W2/dry_run/CROSS_REVIEW_NOT_EXECUTED.marker",
        "sha256": None,
        "producer": "dry_run",
        "role": "explicit_non_review_placeholder",
        "status": "NOT_EXECUTED",
    }
    add("CROSS_REVIEW_ELIGIBLE", "CROSS_REVIEW_SUBMITTED", ts[3],
        "dry_run",
        [chat_art, claude_placeholder, cross_placeholder],
        "Simulate cross-review submission plumbing only; no reviewer is called and no content is generated.")

    decision_placeholder = {
        "path": "runs/W2/dry_run/DECISION_NOT_EXECUTED.marker",
        "sha256": None,
        "producer": "dry_run",
        "role": "explicit_non_decision_placeholder",
        "status": "NOT_EXECUTED",
    }
    add("CROSS_REVIEW_SUBMITTED", "DECISION", ts[4],
        "dry_run",
        [cross_placeholder, decision_placeholder],
        "Simulate decision plumbing only; no decision result or score is produced.")

    add("DECISION", "W2_CLOSED", ts[5],
        "dry_run",
        [decision_placeholder],
        "Simulate closure transition only; no real W2 closure claim is made.")

    add("W2_CLOSED", "W3_ELIGIBLE", ts[6],
        "dry_run",
        [decision_placeholder],
        "Simulate downstream eligibility plumbing only; W3 execution is explicitly not started.")

    report = {
        "workflow": "W2",
        "mode": "ORCHESTRATION_DRY_RUN",
        "authoritative_state_before": manifest["status"],
        "final_state": "W3_ELIGIBLE",
        "real_artifacts_used": [raw_art, chat_art, recon_art, claude_bind_art, claude_prompt_art],
        "placeholder_markers": [claude_placeholder, cross_placeholder, decision_placeholder],
        "transitions": transitions,
        "controls": {
            "manual_dispatches": 0,
            "external_ai_calls": 0,
            "chatgpt_rerun": False,
            "claude_called": False,
            "file_upload": False,
            "cross_review_executed": False,
            "decision_executed": False,
            "w3_executed": False,
            "scoring_methodology_changed": False,
            "frozen_inputs_changed": False,
            "git_mutation": False,
        },
        "determinism": {
            "timestamp_source": "persisted ChatGPT finished_at + fixed 1-second transition offsets",
            "volatile_runtime_time_used": False,
            "artifact_graph_ordered": True,
        },
    }

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    out.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
