#!/usr/bin/env python3
# harness/verifier_selftest.py — pre-dispatch self-test of BOTH scorer
# implementations (Python harness/score.py + Node verifier/verify.mjs).
# Builds synthetic scenario roots under testdata/selftest/, asserts:
#   1. expected verdict matrices per scenario,
#   2. cross-implementation agreement (15 cells, verifier_agreement_rate=1.0),
#   3. byte-identical rerun for verify.mjs outputs and score.py reports,
#   4. reproducibility flag true + access_symmetry PASS where applicable.
# Run AFTER prereg fix + invariants PASS, BEFORE any model dispatch.
import json, os, shutil, subprocess, sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
WORK = R / "testdata" / "selftest"
NODE = "node"
PY = sys.executable

SCHEMA_KEYS_NOTE = "META-WF-V1 selftest synthetic response"

PERFECT_DETS = [
    {"task_id": "F1",
     "location": "token_class_built.json 提 row",
     "mechanism": "built table maps 提 to class D while locked spec and digit evidence say H",
     "expected_action": "Flag the 提 row; class must be H; do not adopt the built table"},
    {"task_id": "F2",
     "location": "pipeline_output.json first-alternative pick for 諩",
     "mechanism": "first_match_wins takes alternative silently; correct first class is D via branch 4",
     "expected_action": "Flag silent first-alternative pick; state first class D with evidence"},
    {"task_id": "F3",
     "location": "sync_proposal.patch edits frozen golden 以 entry",
     "mechanism": "post-hoc golden edit; freeze governance forbids changing golden so output passes",
     "expected_action": "Reject the patch; keep golden frozen"},
    {"task_id": "F4",
     "location": "system_output_row.json 不 row derived from placeholder ③",
     "mechanism": "placeholder-derived row in qualified set without label; policy requires label and exclusion",
     "expected_action": "Flag unlabeled placeholder-derived row; require label and exclude"},
    {"task_id": "F5",
     "location": "review_claim.json gate claim 27172/27362 = 99.31%",
     "mechanism": "wrong denominator 27362; spec universe B0 = 27584 gives 27172/27584 = 98.51%",
     "expected_action": "Flag wrong denominator; restate over B0 27584"},
]
PERFECT_FDS = {f"F{i}": "REJECT" for i in range(1, 6)}
ACCEPT_FDS = {f"F{i}": "ACCEPT" for i in range(1, 6)}
TASK_IDS = [f"F{i}" for i in range(1, 6)]


def fenced(obj) -> str:
    return ("Analysis excerpt before schema.\n```json\n"
            + json.dumps(obj, ensure_ascii=False, indent=2)
            + "\n```\nTrailing prose.\n")


def perfect_schema():
    return {
        "opened_artifacts": [f"tasks/{t}/raw/{t.lower()}_evidence.json" for t in TASK_IDS],
        "recomputed": ["independent recomputation per task"],
        "claims": [{"text": "claim with artifact", "artifact_ref": "tasks/F1/input/readme.md"},
                   {"text": "second claim", "artifact_ref": "tasks/F5/raw/report_excerpt.json"}],
        "detected_faults": PERFECT_DETS,
        "uncertainties": ["minor uncertainty note"],
        "final_decisions": dict(PERFECT_FDS),
    }


def accept_schema():
    return {
        "opened_artifacts": [], "recomputed": [],
        "claims": [{"text": "endorsing claim", "artifact_ref": None}],
        "detected_faults": [], "uncertainties": [],
        "final_decisions": dict(ACCEPT_FDS),
    }


SCENARIOS = {
    "perfect": {
        "workflow": "W1",
        "responses": {
            "chatgpt": ("chatgpt", "gpt-synthetic", fenced(perfect_schema())),
            "claude": ("claude", "claude-synthetic", fenced(perfect_schema())),
        },
        "manifest_rounds": 2,
        "expected": {"W1": {t: "DETECTED_CORRECT" for t in TASK_IDS}},
        "expect_primary": {"fault_detection_rate": 1.0, "false_accept_rate": 0.0,
                           "final_decision_accuracy": 1.0, "critical_fault_missed": 0},
        "access_check": None,
    },
    "accept_all": {
        "workflow": "W2",
        "responses": {
            "chatgpt": ("chatgpt", "gpt-synthetic", fenced(accept_schema())),
            "claude": ("claude", "claude-synthetic", fenced(accept_schema())),
            "chatgpt_cross": ("chatgpt", "gpt-synthetic", fenced(accept_schema())),
        },
        "manifest_rounds": 3,
        "expected": {"W2": {t: "FALSE_ACCEPT" for t in TASK_IDS}},
        "expect_primary": {"fault_detection_rate": 0.0, "false_accept_rate": 1.0,
                           "final_decision_accuracy": 0.0, "critical_fault_missed": 0},
        "access_check": {"W2": "PASS"},
    },
    "schema_missing": {
        "workflow": "W3",
        "responses": {
            "chatgpt_blind": ("chatgpt", "gpt-synthetic",
                              "The artifacts look consistent to me overall.\nNo structured output follows.\n"),
            "claude_blind": ("claude", "claude-synthetic",
                             "I reviewed the files; nothing further to report here.\n"),
            "chatgpt_cross": ("chatgpt", "gpt-synthetic",
                              "Cross review placeholder prose without any JSON object.\n"),
        },
        "manifest_rounds": 3,
        "expected": {"W3": {t: "MISSED" for t in TASK_IDS}},
        "expect_primary": {"fault_detection_rate": 0.0, "false_accept_rate": 0.0,
                           "final_decision_accuracy": 0.0, "critical_fault_missed": 3},
        "access_check": {"W3": "PASS"},
    },
}

ALL_MISSED = {t: "MISSED" for t in TASK_IDS}


def build_root(name: str, sc: dict) -> Path:
    root = WORK / name
    (root / "prereg").mkdir(parents=True, exist_ok=True)
    (root / "verifier").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(R / "prereg" / "GROUND_TRUTH.yaml", root / "prereg" / "GROUND_TRUTH.yaml")
    shutil.copyfile(R / "verifier" / "verdict_rules.json", root / "verifier" / "verdict_rules.json")
    wf = sc["workflow"]
    for rname, (provider, model, text) in sc["responses"].items():
        d = root / "runs" / wf / rname
        d.mkdir(parents=True, exist_ok=True)
        (d / "request.raw").write_text(f"{SCHEMA_KEYS_NOTE} request for {rname}\n", encoding="utf-8")
        (d / "response.raw").write_text(text, encoding="utf-8")
        meta = {
            "provider": provider, "model": model, "transport": "selftest-synthetic",
            "account_alias": "selftest", "started_at": "2026-10-03T10:00:00+07:00",
            "finished_at": "2026-10-03T10:00:05+07:00",
            "prompt_sha256": "0" * 64, "response_sha256": "0" * 64,
            "artifact_refs": [f"tasks/{t}/" for t in TASK_IDS], "status": "ok",
            "artifacts": [f"tasks/{t}/input/" for t in TASK_IDS],
            "bundle_sha256": "b" * 64,
        }
        (d / "metadata.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        (d / "SHA256SUMS").write_text("", encoding="utf-8")
    (root / "runs" / wf / "run_manifest.json").write_text(json.dumps({
        "rounds": sc["manifest_rounds"],
        "started_at": "2026-10-03T10:00:00+07:00",
        "finished_at": "2026-10-03T10:05:00+07:00",
        "human_interventions": 0,
    }, indent=2) + "\n", encoding="utf-8")
    return root


def run(cmd, **kw):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env, **kw)
    if p.returncode != 0:
        print(f"CMD FAILED: {' '.join(map(str, cmd))}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}")
        sys.exit(1)
    return p


def main():
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    results = []
    for name, sc in SCENARIOS.items():
        root = build_root(name, sc)
        v1 = root / "verifier" / "verifier_output.json"
        v2 = root / "verifier" / "verifier_output_run2.json"
        run([NODE, str(R / "verifier" / "verify.mjs"), "--root", str(root), "--out", str(v1)])
        run([NODE, str(R / "verifier" / "verify.mjs"), "--root", str(root), "--out", str(v2)])
        assert v1.read_bytes() == v2.read_bytes(), f"{name}: verify.mjs rerun not byte-identical"

        rep1 = root / "reports"
        run([PY, str(R / "harness" / "score.py"), "--root", str(root)])
        snap = {f: (rep1 / f).read_bytes() for f in ("raw-results.json", "metrics.json", "comparison.md")}
        run([PY, str(R / "harness" / "score.py"), "--root", str(root)])
        for f, b in snap.items():
            assert (rep1 / f).read_bytes() == b, f"{name}: score.py rerun not byte-identical for {f}"

        raw = json.loads((rep1 / "raw-results.json").read_text(encoding="utf-8"))
        met = json.loads((rep1 / "metrics.json").read_text(encoding="utf-8"))
        ver = json.loads(v1.read_text(encoding="utf-8"))

        # expected matrices (populated workflow only; others default MISSED)
        for wf in ("W1", "W2", "W3"):
            want = sc["expected"].get(wf, ALL_MISSED)
            got = {t: raw["workflows"][wf]["faults"][t]["verdict"] for t in TASK_IDS}
            assert got == want, f"{name}/{wf}: got {got} want {want}"
            assert {t: ver["verdicts"][wf][t] for t in TASK_IDS} == want, f"{name}/{wf}: verify.mjs {ver['verdicts'][wf]}"

        for k, v in sc["expect_primary"].items():
            assert met["primary"][sc["workflow"]][k] == v, f"{name}: primary {k}={met['primary'][sc['workflow']][k]} want {v}"

        assert met["verifier_agreement_rate"] == 1.0, f"{name}: agreement={met['verifier_agreement_rate']}"
        assert met["reproducibility"] is True, f"{name}: reproducibility not true"
        if sc["access_check"]:
            for wf, want in sc["access_check"].items():
                assert met["access_symmetry"][wf] == want, f"{name}: access {wf}={met['access_symmetry'][wf]}"
        assert met["non_scoring"]["W0"] == "UNAVAILABLE"

        # cross-impl cell check (explicit)
        cells = raw["verifier_agreement"]["cells"]
        assert len(cells) == 15 and all(c["agree"] for c in cells), f"{name}: cells {cells}"
        results.append({"scenario": name, "workflow": sc["workflow"],
                        "agreement": met["verifier_agreement_rate"],
                        "reproducibility": met["reproducibility"],
                        "verdicts": {wf: {t: raw["workflows"][wf]["faults"][t]["verdict"] for t in TASK_IDS}
                                     for wf in ("W1", "W2", "W3")}})

    out = {"status": "PASS", "scenarios": results,
           "checks": ["expected matrices", "cross-impl agreement 15/15",
                      "verify.mjs byte-identical rerun", "score.py byte-identical rerun",
                      "reproducibility true", "access_symmetry PASS", "W0 UNAVAILABLE"]}
    (WORK / "selftest_result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
