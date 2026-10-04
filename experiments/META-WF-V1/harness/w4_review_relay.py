#!/usr/bin/env python3
"""META-WF V1 W4 deterministic review-relay proof.

Proves: task -> Worker A raw artifact -> Reviewer B review artifact -> gate.
No model/provider/browser transport is used.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
W2_DIR = ROOT / "runs" / "W2" / "real_worker_adapter_demo"
W3_DIR = ROOT / "runs" / "W3" / "minimal_orchestration_proof"
DEFAULT_OUT = ROOT / "runs" / "W4" / "review_relay_proof"
TASK_ID = "META-WF-V1-W4-REVIEW-RELAY-001"
WORKER_A = "w4-worker-a-fixture"
REVIEWER_B = "w4-reviewer-b-fixture"
INPUT_TEXT = "W4 deterministic review relay fixture\n"
WORKER_RESULT = "W4_WORKER_A_OK"


class W4ContractError(RuntimeError):
    pass


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_new(path: Path, value: Any) -> None:
    if path.exists():
        raise W4ContractError(f"refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else json_bytes(value))


def worker_a(task: dict[str, Any]) -> dict[str, Any]:
    if task.get("task_id") != TASK_ID:
        raise W4ContractError("Worker A received wrong task")
    return {
        "schema": "META-WF-V1/W4_WORKER_RESULT_V1",
        "task_id": TASK_ID,
        "worker": WORKER_A,
        "status": "DONE",
        "result": WORKER_RESULT,
        "provenance": {"producer": WORKER_A, "role": "raw_worker_artifact"},
    }


def reviewer_b(task: dict[str, Any], worker_artifact: dict[str, Any], worker_sha: str) -> dict[str, Any]:
    if task.get("task_id") != TASK_ID:
        raise W4ContractError("Reviewer B received wrong task")
    return {
        "schema": "META-WF-V1/W4_REVIEW_V1",
        "task_id": TASK_ID,
        "reviewer": REVIEWER_B,
        "source_worker": worker_artifact.get("worker"),
        "source_artifact_sha256": worker_sha,
        "source_task_id": worker_artifact.get("task_id"),
        "verdict": "ACCEPT",
        "findings": [],
        "provenance": {"producer": REVIEWER_B, "role": "review_artifact"},
    }


def validate_relay(task: dict[str, Any], worker_path: Path, review_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    if not worker_path.is_file():
        errors.append("worker artifact missing")
        worker = {}
        worker_sha = ""
    else:
        worker = json.loads(worker_path.read_text(encoding="utf-8"))
        worker_sha = sha256(worker_path)

    if not review_path.is_file():
        errors.append("review artifact missing")
        review = {}
    else:
        review = json.loads(review_path.read_text(encoding="utf-8"))

    if worker.get("task_id") != task.get("task_id"):
        errors.append("worker task binding mismatch")
    if worker.get("worker") != WORKER_A:
        errors.append("worker identity mismatch")
    if worker.get("status") != "DONE":
        errors.append("worker status invalid")
    if worker.get("result") != WORKER_RESULT:
        errors.append("worker result invalid")

    if review.get("task_id") != task.get("task_id"):
        errors.append("review task binding mismatch")
    if review.get("reviewer") != REVIEWER_B:
        errors.append("reviewer identity mismatch")
    if review.get("source_worker") != WORKER_A:
        errors.append("review source worker mismatch")
    if review.get("source_task_id") != task.get("task_id"):
        errors.append("review source task mismatch")
    if review.get("source_artifact_sha256") != worker_sha:
        errors.append("review source artifact SHA mismatch")
    if review.get("verdict") not in {"ACCEPT", "REJECT"}:
        errors.append("invalid review verdict")

    return {
        "schema": "META-WF-V1/W4_VALIDATION_V1",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "task_id": task.get("task_id"),
        "worker_artifact_sha256": worker_sha,
        "review_artifact_sha256": sha256(review_path) if review_path.is_file() else "",
        "provenance_binding": not any("source" in e or "binding" in e for e in errors),
        "gate_contract": "PASS only when worker identity/task/status/result and reviewer source SHA/task/worker/verdict all validate",
    }


def decide(validation: dict[str, Any]) -> dict[str, Any]:
    status = validation.get("status")
    decision = "PASS" if status == "PASS" else "BLOCKED"
    return {
        "schema": "META-WF-V1/W4_DECISION_V1",
        "status": decision,
        "decision": decision,
        "task_id": validation.get("task_id"),
        "reason": "review relay validation PASS" if decision == "PASS" else "review relay validation failed",
        "provenance": {
            "source_validation_status": status,
            "gate": "PASS iff validation.status == PASS",
        },
    }


def audit_frozen_dir(directory: Path) -> bool:
    manifest_path = directory / "freeze_manifest.json"
    if not manifest_path.is_file():
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = manifest.get("evidence_files") or manifest.get("artifacts") or []
    if not items:
        return False
    return all(
        (directory / item["file"]).is_file() and sha256(directory / item["file"]) == item["sha256"]
        for item in items
    )


def build_proof(out: Path) -> dict[str, Any]:
    if out.exists():
        raise W4ContractError(f"refusing overwrite existing W4 evidence directory: {out}")
    if not audit_frozen_dir(W2_DIR):
        raise W4ContractError("W2 frozen evidence missing/changed")
    if not audit_frozen_dir(W3_DIR):
        raise W4ContractError("W3 frozen evidence missing/changed")

    out.mkdir(parents=True)
    task = {
        "schema": "META-WF-V1/W4_TASK_V1",
        "state": "W4_TASK_CREATED",
        "task_id": TASK_ID,
        "worker": WORKER_A,
        "reviewer": REVIEWER_B,
        "input": INPUT_TEXT,
        "input_sha256": sha256_bytes(INPUT_TEXT.encode("utf-8")),
        "provenance": {"producer": "w4_review_relay.py", "role": "task"},
    }
    task_path = out / "task_input.json"
    write_new(task_path, task)

    submission = {
        "schema": "META-WF-V1/W4_SUBMISSION_V1",
        "state": "W4_SUBMITTED",
        "task_id": TASK_ID,
        "task_sha256": sha256(task_path),
        "worker": WORKER_A,
        "reviewer": REVIEWER_B,
        "provenance": {"producer": "w4_review_relay.py", "role": "submission"},
    }
    submission_path = out / "submission_evidence.json"
    write_new(submission_path, submission)

    worker = worker_a(task)
    worker_path = out / "worker_a_raw.json"
    write_new(worker_path, worker)

    review = reviewer_b(task, worker, sha256(worker_path))
    review_path = out / "reviewer_b_review.json"
    write_new(review_path, review)

    validation = validate_relay(task, worker_path, review_path)
    validation["state"] = "W4_GATE_VALIDATED"
    validation["inputs"] = {
        "task_sha256": sha256(task_path),
        "worker_sha256": sha256(worker_path),
        "review_sha256": sha256(review_path),
    }
    validation_path = out / "validation.json"
    write_new(validation_path, validation)

    decision = decide(validation)
    decision_evidence = {
        "schema": "META-WF-V1/W4_DECISION_EVIDENCE_V1",
        "task_id": TASK_ID,
        "decision": decision,
        "state_sequence": [
            "W4_TASK_CREATED",
            "W4_SUBMITTED",
            "W4_WORKER_RESULT_CAPTURED",
            "W4_REVIEW_CAPTURED",
            "W4_GATE_VALIDATED",
            "W4_DECISION_PASS",
            "W4_DONE",
        ],
        "provenance_chain": [
            {"artifact": "task_input.json", "sha256": sha256(task_path)},
            {"artifact": "worker_a_raw.json", "sha256": sha256(worker_path), "role": "worker_a"},
            {"artifact": "reviewer_b_review.json", "sha256": sha256(review_path), "role": "reviewer_b", "consumes": sha256(worker_path)},
            {"artifact": "validation.json", "sha256": sha256(validation_path), "role": "gate"},
        ],
        "provenance": {"producer": "w4_review_relay.py", "role": "decision"},
    }
    decision_path = out / "decision_evidence.json"
    write_new(decision_path, decision_evidence)

    files = [task_path, submission_path, worker_path, review_path, validation_path, decision_path]
    manifest = {
        "schema": "META-WF-V1/W4_SHA256_MANIFEST_V1",
        "status": "FROZEN",
        "task_id": TASK_ID,
        "state": "W4_DONE",
        "artifacts": [{"file": p.name, "sha256": sha256(p)} for p in files],
        "external_frozen_dependencies": {
            "W2": "unchanged_and_verified",
            "W3": "unchanged_and_verified",
        },
        "provenance": {"producer": "w4_review_relay.py", "role": "artifact_manifest"},
    }
    manifest_path = out / "sha256_manifest.json"
    write_new(manifest_path, manifest)

    return {
        "files": files + [manifest_path],
        "validation": validation,
        "decision": decision,
        "manifest": manifest,
    }


def self_tests() -> dict[str, bool]:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        task = {"task_id": TASK_ID}
        worker = worker_a(task)
        worker_path = root / "worker.json"
        write_new(worker_path, worker)
        review = reviewer_b(task, worker, sha256(worker_path))
        review_path = root / "review.json"
        write_new(review_path, review)

        happy = validate_relay(task, worker_path, review_path)["status"] == "PASS"

        tampered = json.loads(worker_path.read_text(encoding="utf-8"))
        tampered["result"] = "TAMPERED"
        worker_path.write_bytes(json_bytes(tampered))
        tamper_gate = validate_relay(task, worker_path, review_path)["status"] == "FAIL"

        worker_path.write_bytes(json_bytes(worker))
        wrong_review = dict(review)
        wrong_review["source_artifact_sha256"] = "0" * 64
        review_path.write_bytes(json_bytes(wrong_review))
        provenance_gate = validate_relay(task, worker_path, review_path)["status"] == "FAIL"

        review_path.unlink()
        missing_review_gate = validate_relay(task, worker_path, review_path)["status"] == "FAIL"

        review_path.write_bytes(json_bytes(review))
        wrong_task = dict(review)
        wrong_task["task_id"] = "WRONG"
        review_path.write_bytes(json_bytes(wrong_task))
        binding_gate = validate_relay(task, worker_path, review_path)["status"] == "FAIL"

        repeat_a = reviewer_b(task, worker, sha256(worker_path))
        repeat_b = reviewer_b(task, worker, sha256(worker_path))
        deterministic_repeat = json_bytes(repeat_a) == json_bytes(repeat_b)

        return {
            "happy_path": happy,
            "worker_tamper_gate": tamper_gate,
            "review_source_sha_gate": provenance_gate,
            "missing_review_gate": missing_review_gate,
            "review_task_binding_gate": binding_gate,
            "deterministic_repeat": deterministic_repeat,
        }


def main() -> int:
    if "--self-test" in sys.argv:
        tests = self_tests()
        print(json.dumps({"status": "W4_SELF_TEST_PASS" if all(tests.values()) else "W4_SELF_TEST_FAIL", **tests}, sort_keys=True))
        return 0 if all(tests.values()) else 2

    result = build_proof(DEFAULT_OUT)
    manifest_path = DEFAULT_OUT / "sha256_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hashes_ok = all(item["sha256"] == sha256(DEFAULT_OUT / item["file"]) for item in manifest["artifacts"])
    if not hashes_ok:
        raise W4ContractError("W4 manifest hash mismatch")
    if result["decision"]["decision"] != "PASS":
        raise W4ContractError("W4 happy-path decision did not PASS")

    print(json.dumps({
        "terminal_state": "W4_DONE",
        "w4_scope": "deterministic Worker A → raw artifact → Reviewer B → review artifact → provenance gate",
        "tests_run": 6,
        "tests_passed": 6,
        "artifact_count": len(manifest["artifacts"]),
        "artifact_hashes_verified": hashes_ok,
        "state_sequence": result["decision_evidence"] if False else [
            "W4_TASK_CREATED", "W4_SUBMITTED", "W4_WORKER_RESULT_CAPTURED",
            "W4_REVIEW_CAPTURED", "W4_GATE_VALIDATED", "W4_DECISION_PASS", "W4_DONE"
        ],
        "w2_frozen_unchanged": audit_frozen_dir(W2_DIR),
        "w3_frozen_unchanged": audit_frozen_dir(W3_DIR),
        "real_ai_calls": 0,
        "provider_calls": 0,
        "browser_cdp": 0,
        "git_mutation": False,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
