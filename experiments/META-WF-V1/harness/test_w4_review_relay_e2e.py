from pathlib import Path
import json
from w4_review_relay import DEFAULT_OUT, audit_frozen_dir, build_proof, sha256

def test_w4_evidence_build_and_gate():
    assert DEFAULT_OUT.is_dir()
    validation = json.loads((DEFAULT_OUT / "validation.json").read_text(encoding="utf-8"))
    decision = json.loads((DEFAULT_OUT / "decision_evidence.json").read_text(encoding="utf-8"))
    assert validation["status"] == "PASS"
    assert decision["decision"]["decision"] == "PASS"
    manifest = json.loads((DEFAULT_OUT / "sha256_manifest.json").read_text(encoding="utf-8"))
    assert all(item["sha256"] == sha256(DEFAULT_OUT / item["file"]) for item in manifest["artifacts"])
    base = Path(DEFAULT_OUT).parents[2] / "runs"
    assert audit_frozen_dir(base / "W2" / "real_worker_adapter_demo")
    assert audit_frozen_dir(base / "W3" / "minimal_orchestration_proof")
