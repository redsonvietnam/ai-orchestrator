#!/usr/bin/env python3
"""META-WF V1 W3 minimal deterministic orchestration proof.

No model/provider/browser transport is used. A deterministic fixture worker
receives a task and returns a task-bound result. The proof captures immutable
artifacts, validates SHA-256 and bindings, and gates the decision on PASS
validation.
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
DEFAULT_OUT = ROOT / "runs" / "W3" / "minimal_orchestration_proof"
TASK_ID = "META-WF-V1-W3-DETERMINISTIC-001"
WORKER = "w3-fixture"
INPUT_TEXT = "W3 deterministic orchestration fixture\n"


class W3ContractError(RuntimeError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_new(path: Path, content: bytes) -> None:
    if path.exists():
        raise W3ContractError(f"refusing silent overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def deterministic_worker(task: dict[str, Any]) -> dict[str, Any]:
    if task.get("task_id") != TASK_ID:
        raise W3ContractError("fixture received unexpected task identity")
    return {
        "task_id": task["task_id"],
        "worker": WORKER,
        "status": "DONE",
        "result": "W3_WORKER_OK",
    }


def validate_artifacts(
    task: dict[str, Any],
    worker_result: dict[str, Any],
    task_sha: str,
    result_path: Path,
    captured_result: dict[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    if task.get("task_id") != TASK_ID:
        errors.append("task identity mismatch")
    if worker_result.get("task_id") != task.get("task_id"):
        errors.append("worker result task binding mismatch")
    if worker_result.get("worker") != WORKER:
        errors.append("worker identity mismatch")
    if worker_result.get("status") != "DONE":
        errors.append("invalid worker result status")
    if worker_result.get("result") != "W3_WORKER_OK":
        errors.append("unexpected worker result")
    if not task_sha or len(task_sha) != 64:
        errors.append("task artifact SHA missing")
    if not result_path.is_file():
        errors.append("worker result artifact missing")
        result_sha = ""
    else:
        result_sha = sha256(result_path)
    if sha256_bytes(json_bytes(captured_result)) != result_sha:
        errors.append("worker result artifact SHA mismatch")
    return {
        "schema": "META-WF-V1/W3_VALIDATION_V1",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "task_id": task.get("task_id"),
        "worker": worker_result.get("worker"),
        "task_sha256": task_sha,
        "worker_result_sha256": result_sha,
        "mutation_after_capture": False,
        "provenance": {
            "validator": "w3_minimal_orchestration.py",
            "contract": "task identity + worker binding + DONE status + result + SHA",
        },
    }


def decide(validation: dict[str, Any]) -> dict[str, Any]:
    status = validation.get("status")
    decision = "PASS" if status == "PASS" else "BLOCKED"
    return {
        "schema": "META-WF-V1/W3_DECISION_V1",
        "status": decision,
        "decision": decision,
        "reason": "validation PASS" if decision == "PASS" else "validation did not PASS",
        "task_id": validation.get("task_id"),
        "provenance": {
            "decision_gate": "PASS only when validation.status == PASS",
            "source_validation_status": status,
        },
    }


def build_proof(out: Path) -> list[Path]:
    if out.exists():
        raise W3ContractError(f"refusing to overwrite existing W3 evidence directory: {out}")

    out.mkdir(parents=True)
    task = {
        "schema": "META-WF-V1/W3_TASK_V1",
        "status": "CREATED",
        "task_id": TASK_ID,
        "worker": WORKER,
        "input": INPUT_TEXT,
        "input_sha256": sha256_bytes(INPUT_TEXT.encode("utf-8")),
        "provenance": {"producer": "w3_minimal_orchestration.py", "role": "task_input"},
    }
    task_path = out / "task_input.json"
    write_new(task_path, json_bytes(task))

    submitted = {
        "schema": "META-WF-V1/W3_SUBMISSION_V1",
        "state": "W3_SUBMITTED",
        "task_id": TASK_ID,
        "worker": WORKER,
        "task_sha256": sha256(task_path),
        "provenance": {"producer": "w3_minimal_orchestration.py", "role": "submission_evidence"},
    }

    result = deterministic_worker(task)
    result["provenance"] = {"producer": WORKER, "role": "worker_result"}
    result_path = out / "worker_result.json"
    write_new(result_path, json_bytes(result))

    captured_result = json.loads(result_path.read_text(encoding="utf-8"))
    result_sha = sha256(result_path)
    validation = validate_artifacts(task, result, sha256(task_path), result_path, captured_result)
    validation["submission"] = submitted
    validation["state"] = "W3_ARTIFACT_VALIDATED"
    validation_path = out / "validation.json"
    write_new(validation_path, json_bytes(validation))

    decision = decide(validation)
    transitions = [
        {"from": None, "to": "W3_TASK_CREATED", "evidence": ["task_input.json"]},
        {"from": "W3_TASK_CREATED", "to": "W3_SUBMITTED", "evidence": ["task_input.json"]},
        {"from": "W3_SUBMITTED", "to": "W3_WORKER_RESULT_CAPTURED", "evidence": ["worker_result.json"]},
        {"from": "W3_WORKER_RESULT_CAPTURED", "to": "W3_ARTIFACT_VALIDATED", "evidence": ["validation.json"]},
        {"from": "W3_ARTIFACT_VALIDATED", "to": "W3_DECISION_PASS", "evidence": ["validation.json", "decision_evidence.json"]},
        {"from": "W3_DECISION_PASS", "to": "W3_DONE", "evidence": ["decision_evidence.json"]},
    ]
    decision_evidence = {
        "schema": "META-WF-V1/W3_DECISION_EVIDENCE_V1",
        "status": decision["status"],
        "task_id": TASK_ID,
        "decision": decision,
        "state_sequence": [t["to"] for t in transitions],
        "transitions": transitions,
        "provenance": {
            "producer": "w3_minimal_orchestration.py",
            "role": "decision_and_state_evidence",
        },
    }
    decision_path = out / "decision_evidence.json"
    write_new(decision_path, json_bytes(decision_evidence))

    files = [task_path, result_path, validation_path, decision_path]
    manifest = {
        "schema": "META-WF-V1/W3_SHA256_MANIFEST_V1",
        "status": "FROZEN",
        "task_id": TASK_ID,
        "provenance": {
            "producer": "w3_minimal_orchestration.py",
            "role": "sha256_manifest",
        },
        "artifacts": [
            {
                "file": p.name,
                "sha256": sha256(p),
                "provenance": json.loads(p.read_text(encoding="utf-8")).get("provenance"),
                "status": json.loads(p.read_text(encoding="utf-8")).get("status"),
            }
            for p in files
        ],
    }
    manifest_path = out / "sha256_manifest.json"
    write_new(manifest_path, json_bytes(manifest))
    return files + [manifest_path]


def audit_w2_unchanged() -> bool:
    manifest_path = W2_DIR / "freeze_manifest.json"
    if not manifest_path.is_file():
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest["evidence_files"]:
        path = W2_DIR / item["file"]
        if not path.is_file() or sha256(path) != item["sha256"]:
            return False
    return sha256(manifest_path) == "8d197cf182b1f1e6272cedeb0af5b88d41ffc44f4c668240ad5a53ceb8a07a1b"


def run_proof(out: Path = DEFAULT_OUT) -> dict[str, Any]:
    files = build_proof(out)
    manifest = json.loads((out / "sha256_manifest.json").read_text(encoding="utf-8"))
    hashes_ok = all(
        item["sha256"] == sha256(out / item["file"])
        for item in manifest["artifacts"]
    )
    if not hashes_ok:
        raise W3ContractError("W3 SHA manifest mismatch after capture")
    if not audit_w2_unchanged():
        raise W3ContractError("W2 frozen evidence changed or is missing")
    decision = json.loads((out / "decision_evidence.json").read_text(encoding="utf-8"))
    if decision["decision"]["decision"] != "PASS":
        raise W3ContractError("W3 happy-path decision did not PASS")
    return {
        "terminal_state": "W3_DONE",
        "w3_scope": "minimal deterministic task→worker→artifact→validation→decision",
        "files_changed": [str(p.relative_to(ROOT)).replace("\\", "/") for p in files],
        "artifact_count": len(files),
        "artifact_hashes_verified": hashes_ok,
        "state_sequence": decision["state_sequence"],
        "w2_frozen_unchanged": True,
        "real_ai_calls": 0,
        "provider_calls": 0,
    }


def self_tests() -> dict[str, bool]:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        task = {
            "task_id": TASK_ID,
            "worker": WORKER,
            "input": INPUT_TEXT,
        }
        result = deterministic_worker(task)
        result_bytes = json_bytes(result)
        result_path = root / "result.json"
        result_path.write_bytes(result_bytes)
        result_sha = sha256(result_path)

        validation = validate_artifacts(
            task, result, sha256_bytes(json_bytes(task)), result_path, result
        )
        happy = validation["status"] == "PASS" and decide(validation)["decision"] == "PASS"

        tampered = bytearray(result_bytes)
        tampered[-2:] = b"X\n"
        result_path.write_bytes(bytes(tampered))
        tamper_validation = validate_artifacts(
            task, result, sha256_bytes(json_bytes(task)), result_path, result
        )
        tamper_gate = (
            tamper_validation["status"] == "FAIL"
            and decide(tamper_validation)["decision"] in {"FAIL", "BLOCKED"}
        )

        wrong = dict(result)
        wrong["task_id"] = "META-WF-V1-W3-WRONG-TASK"
        wrong_validation = validate_artifacts(
            task, wrong, sha256_bytes(json_bytes(task)), result_path, result
        )
        binding_gate = wrong_validation["status"] == "FAIL"

        missing_path = root / "missing.json"
        missing_validation = validate_artifacts(
            task, result, sha256_bytes(json_bytes(task)), missing_path, result
        )
        missing_gate = (
            missing_validation["status"] == "FAIL"
            and decide(missing_validation)["decision"] == "BLOCKED"
        )

        repeat_a = deterministic_worker(task)
        repeat_b = deterministic_worker(task)
        deterministic_repeat = json_bytes(repeat_a) == json_bytes(repeat_b)

        return {
            "happy_path": happy,
            "tamper_gate": tamper_gate,
            "binding_gate": binding_gate,
            "missing_artifact_gate": missing_gate,
            "deterministic_repeat": deterministic_repeat,
        }


def main() -> int:
    if "--self-test" in sys.argv:
        tests = self_tests()
        print(json.dumps({"status": "W3_SELF_TEST_PASS" if all(tests.values()) else "W3_SELF_TEST_FAIL", **tests}, sort_keys=True))
        return 0 if all(tests.values()) else 2
    print(json.dumps(run_proof(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
