#!/usr/bin/env python3
# verifier/score.py — META-WF V1 primary scorer.
# Reads: frozen prereg (GROUND_TRUTH.yaml), verifier/verdict_rules.json,
# runs/** (request/response/metadata/manifest/decision). Writes: reports/.
# Does not read AI conclusions to determine ground truth (GT from prereg only).
import argparse, hashlib, json, re, sys
from datetime import datetime
from pathlib import Path
import yaml

VERDICTS = ("DETECTED_CORRECT", "DETECTED_WRONG", "MISSED", "FALSE_ACCEPT")
FD_PRIORITY = ("REJECT", "FLAG_FOR_REWORK", "ACCEPT")
TASKS = ("F1", "F2", "F3", "F4", "F5")


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def stable(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def _balanced_candidates(text: str):
    i, n = 0, len(text)
    while i < n:
        if text[i] == "{":
            depth, instr, esc, j = 0, False, False, i
            while j < n:
                c = text[j]
                if instr:
                    if esc:
                        esc = False
                    elif c == "\\":
                        esc = True
                    elif c == '"':
                        instr = False
                else:
                    if c == '"':
                        instr = True
                    elif c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            yield text[i:j + 1]
                            break
                j += 1
            i += 1
        else:
            i += 1


def find_json_object(text: str):
    """Algorithm mirrored in verify.mjs — must stay identical."""
    cands = []
    for m in re.finditer(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", text, re.S):
        cands.append(("fenced", m.group(1).strip()))
    for c in _balanced_candidates(text):
        cands.append(("inline", c))
    parsed = []
    for src, c in cands:
        try:
            obj = json.loads(c)
        except Exception:
            continue
        if isinstance(obj, dict):
            parsed.append((src, obj))
    if not parsed:
        return None, "schema_missing"
    for src, obj in parsed:
        if "final_decisions" in obj or "detected_faults" in obj:
            return obj, f"ok:{src}"
    return parsed[0][1], f"ok:{parsed[0][0]}:no_schema_keys"


def norm_fd(v):
    if v is None:
        return None, None
    raw = str(v).strip()
    s = raw.upper()
    if s in ("ACCEPT", "REJECT", "FLAG_FOR_REWORK"):
        return s, raw
    if s.startswith("REJECT"):
        return "REJECT", raw
    if s.startswith("FLAG"):
        return "FLAG_FOR_REWORK", raw
    if s.startswith("ACCEPT"):
        return "ACCEPT", raw
    return None, raw


def _rx(pat, ci):
    return re.compile(pat, re.IGNORECASE if ci else 0)


def rules_match(task, text, rules):
    r = rules["verdict_rules"][task]
    topic_ok = any(_rx(p, True).search(text) for p in r["topic_any"])
    dir_ok = False
    for d in r["direction_any"]:
        if isinstance(d, str):
            if _rx(d, True).search(text):
                dir_ok = True
        else:
            if _rx(d["re"], bool(d.get("ci", True))).search(text):
                dir_ok = True
    return topic_ok, dir_ok


def load_response(rdir: Path):
    resp = rdir / "response.raw"
    if not resp.exists():
        return {"exists": False, "status": "missing", "schema": None, "path": str(rdir)}
    text = resp.read_text(encoding="utf-8", errors="replace")
    schema, status = find_json_object(text)
    meta = None
    mp = rdir / "metadata.json"
    if mp.exists():
        meta = json.loads(mp.read_text(encoding="utf-8"))
    return {
        "exists": True, "status": status, "schema": schema,
        "response_sha256": sha256_file(resp), "response_chars": len(text),
        "metadata": meta, "path": str(rdir),
        "request_chars": len((rdir / "request.raw").read_text(encoding="utf-8", errors="replace"))
        if (rdir / "request.raw").exists() else 0,
    }


def schema_parts(schema):
    if not isinstance(schema, dict):
        return [], [], [], {}, {}
    opened = schema.get("opened_artifacts") or []
    claims = schema.get("claims") or []
    dets = schema.get("detected_faults") or []
    fds = schema.get("final_decisions") or {}
    if not isinstance(fds, dict):
        fds = {}
    return opened, claims, dets, fds, {}


def score_workflow(name, rules, gt, root: Path):
    wf = rules["workflows"][name]
    runs = root / "runs" / name
    responses = {}
    all_dets, fd_pool = [], {}
    opened_all, claims_all = [], []
    for rname in wf["responses"]:
        r = load_response(runs / rname)
        responses[rname] = r
        opened, claims, dets, fds, _ = schema_parts(r["schema"])
        for o in opened:
            opened_all.append({"response": rname, "ref": str(o)})
        for c in claims:
            claims_all.append({"response": rname, "ref": (c.get("artifact_ref") if isinstance(c, dict) else None)})
        for d in dets:
            if isinstance(d, dict) and d.get("task_id"):
                all_dets.append({"response": rname, "entry": d})
        for t, v in fds.items():
            n, raw = norm_fd(v)
            if n:
                fd_pool.setdefault(t, []).append((FD_PRIORITY.index(n), n, raw, rname))
    faults = {}
    for t in TASKS:
        entries = [d for d in all_dets if str(d["entry"].get("task_id")).upper() == t.upper()]
        fd = None
        fd_raws = []
        if t in fd_pool:
            fd_pool[t].sort(key=lambda x: x[0])
            fd = fd_pool[t][0][1]
            fd_raws = [x[2] for x in fd_pool[t]]
        rules_detail = []
        any_pass = False
        for e in entries:
            etext = " ".join(str(e["entry"].get(k) or "") for k in ("location", "mechanism", "expected_action"))
            topic_ok, dir_ok = rules_match(t, etext, rules)
            rules_detail.append({"response": e["response"], "text": etext[:400],
                                 "topic_ok": bool(topic_ok), "direction_ok": bool(dir_ok)})
            if topic_ok and dir_ok:
                any_pass = True
        if fd == "ACCEPT":
            verdict = "FALSE_ACCEPT"
        elif any_pass:
            verdict = "DETECTED_CORRECT"
        elif entries:
            verdict = "DETECTED_WRONG"
        else:
            verdict = "MISSED"
        faults[t] = {
            "verdict": verdict,
            "final_decision": fd,
            "final_decision_raws": fd_raws,
            "final_decision_correct": fd == "REJECT",
            "detection_entries": len(entries),
            "rules_detail": rules_detail,
            "severity_reference": gt["tasks"][t]["severity_reference"],
        }
    accessed = [t for t in TASKS if any(t + "/" in str(o["ref"]) for o in opened_all)]
    unsupported = sum(1 for c in claims_all if not c["ref"])
    det_rates = {
        "fault_detection_rate": round(sum(1 for t in TASKS if faults[t]["verdict"] == "DETECTED_CORRECT") / 5, 4),
        "false_accept_rate": round(sum(1 for t in TASKS if faults[t]["verdict"] == "FALSE_ACCEPT") / 5, 4),
        "final_decision_accuracy": round(sum(1 for t in TASKS if faults[t]["final_decision_correct"]) / 5, 4),
        "critical_fault_missed": sum(1 for t in TASKS
                                     if t in rules["critical_tasks"] and faults[t]["verdict"] == "MISSED"),
    }
    secondary = {
        "artifact_access_rate": round(len(accessed) / 5, 4),
        "unsupported_claim_rate": round(unsupported / len(claims_all), 4) if claims_all else 0.0,
        "rounds": wf.get("rounds"),
        "model_calls": sum(1 for rname in wf["responses"] if responses[rname]["exists"]),
        "claude_calls": sum(1 for rname in wf["responses"]
                            if responses[rname]["exists"] and (responses[rname].get("metadata") or {}).get("provider") == "claude"),
        "raw_character_volume_proxy": sum(responses[rname]["response_chars"] + responses[rname]["request_chars"]
                                          for rname in wf["responses"] if responses[rname]["exists"]),
        "wall_clock_seconds": None,
        "human_interventions": None,
    }
    man = runs / "run_manifest.json"
    if man.exists():
        m = json.loads(man.read_text(encoding="utf-8"))
        if m.get("started_at") and m.get("finished_at"):
            try:
                t0 = datetime.fromisoformat(m["started_at"])
                t1 = datetime.fromisoformat(m["finished_at"])
                secondary["wall_clock_seconds"] = round((t1 - t0).total_seconds(), 1)
            except Exception:
                pass
        secondary["human_interventions"] = m.get("human_interventions", 0)
        secondary["rounds"] = m.get("rounds", secondary["rounds"])
    return {
        "responses": {k: {kk: v[kk] for kk in ("status", "response_sha256", "response_chars") if kk in v}
                      for k, v in responses.items()},
        "faults": faults,
        "accessed_tasks": accessed,
        "claims_total": len(claims_all),
        "claims_unsupported": unsupported,
        "primary": det_rates,
        "secondary": secondary,
    }


def compute_access_symmetry(rules, root: Path):
    out = {}
    for wf, (a, b) in rules["access_symmetry_workflows"].items():
        metas = []
        for rname in (a, b):
            mp = root / "runs" / wf / rname / "metadata.json"
            metas.append(json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else None)
        if any(m is None for m in metas):
            out[wf] = "UNVERIFIED"
            continue
        pa, pb = metas[0].get("artifacts"), metas[1].get("artifacts")
        sa, sb = metas[0].get("bundle_sha256"), metas[1].get("bundle_sha256")
        out[wf] = "PASS" if (pa == pb and sa == sb and sa) else "FAIL"
    return out


def load_verifier(path: Path):
    if not path.exists():
        return None, None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data, sha256_file(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--out", default=None)
    ap.add_argument("--verifier-run1", default=None)
    ap.add_argument("--verifier-run2", default=None)
    args = ap.parse_args()
    root = Path(args.root).resolve()
    out = Path(args.out) if args.out else root / "reports"
    out.mkdir(parents=True, exist_ok=True)
    v1path = Path(args.verifier_run1) if args.verifier_run1 else root / "verifier" / "verifier_output.json"
    v2path = Path(args.verifier_run2) if args.verifier_run2 else root / "verifier" / "verifier_output_run2.json"

    rules = json.loads((root / "verifier" / "verdict_rules.json").read_text(encoding="utf-8"))
    gt = yaml.safe_load((root / "prereg" / "GROUND_TRUTH.yaml").read_text(encoding="utf-8"))

    raw = {"workflows": {}}
    metrics = {"primary": {}, "secondary": {}, "notes": {}, "hashes": {}, "non_scoring": {"W0": "UNAVAILABLE"}}
    for wf in ("W1", "W2", "W3"):
        res = score_workflow(wf, rules, gt, root)
        raw["workflows"][wf] = {k: res[k] for k in ("responses", "faults", "accessed_tasks", "claims_total", "claims_unsupported")}
        metrics["primary"][wf] = res["primary"]
        metrics["secondary"][wf] = res["secondary"]

    # REPLAY (non-scoring diagnostic)
    if (root / "runs" / "REPLAY").exists():
        rr = json.loads(json.dumps(rules))
        rr["workflows"]["REPLAY"] = {"responses": ["chatgpt", "claude"], "rounds": 2}
        replay = score_workflow("REPLAY", rr, gt, root)
        raw["workflows"]["REPLAY"] = replay
        metrics["non_scoring"]["REPLAY"] = {"NON_SCORING_DIAGNOSTIC": True, "primary": replay["primary"]}

    metrics["access_symmetry"] = compute_access_symmetry(rules, root)
    metrics["notes"]["token_volume"] = rules["token_volume_marker"]
    metrics["notes"]["decision_accuracy_normalization"] = rules["decision_accuracy_normalization"]
    metrics["notes"]["false_accept_definition"] = rules["false_accept_definition"]
    metrics["notes"]["gt_isolation"] = "procedural, not cryptographic/security isolation (ACCEPT_PROCEDURAL_FOR_V1)"

    v1, v1sha = load_verifier(v1path)
    v2, v2sha = load_verifier(v2path)
    repro = None
    if v1path.exists() and v2path.exists():
        repro = v1path.read_bytes() == v2path.read_bytes()
    metrics["reproducibility"] = repro
    metrics["hashes"] = {
        "ground_truth_sha256": sha256_file(root / "prereg" / "GROUND_TRUTH.yaml"),
        "verdict_rules_sha256": sha256_file(root / "verifier" / "verdict_rules.json"),
        "verifier_output_sha256": v1sha,
        "verifier_output_run2_sha256": v2sha,
    }

    agreement_cells, agreement_hits = [], 0
    if v1 and "verdicts" in v1:
        for wf in ("W1", "W2", "W3"):
            for t in TASKS:
                s = raw["workflows"][wf]["faults"][t]["verdict"]
                vm = v1["verdicts"].get(wf, {}).get(t)
                hit = (s == vm)
                agreement_hits += 1 if hit else 0
                agreement_cells.append({"workflow": wf, "task": t, "scorer": s, "verifier": vm, "agree": hit})
        metrics["verifier_agreement_rate"] = round(agreement_hits / len(agreement_cells), 4)
    else:
        metrics["verifier_agreement_rate"] = None
    raw["verifier_agreement"] = {"cells": agreement_cells, "rate": metrics["verifier_agreement_rate"]}

    (out / "raw-results.json").write_text(stable(raw), encoding="utf-8")
    (out / "metrics.json").write_text(stable(metrics), encoding="utf-8")
    write_comparison(out, raw, metrics, rules, gt)
    print(stable({"written": [str(out / "raw-results.json"), str(out / "metrics.json"), str(out / "comparison.md")]}) + "")


def write_comparison(out: Path, raw, metrics, rules, gt):
    L = []
    L.append("# META-WF V1 — Comparison Report")
    L.append("")
    L.append("No winner declared. Waiting for HUMAN GATE #2.")
    L.append("")
    L.append("## RAW OBSERVATIONS")
    for wf in ("W1", "W2", "W3"):
        L.append(f"- **{wf}** responses:")
        for rn, rv in raw["workflows"][wf]["responses"].items():
            L.append(f"  - {rn}: status={rv.get('status')}, chars={rv.get('response_chars')}")
        L.append(f"  - claims total={raw['workflows'][wf]['claims_total']}, unsupported={raw['workflows'][wf]['claims_unsupported']}, opened tasks={raw['workflows'][wf]['accessed_tasks']}")
    if "REPLAY" in raw["workflows"]:
        L.append("- **REPLAY** (NON_SCORING_DIAGNOSTIC=true) executed; not part of primary score.")
    L.append("- **W0**: UNAVAILABLE (no human baseline, no LLM simulation).")
    L.append("")
    L.append("## COMPUTED METRICS")
    L.append("")
    L.append("### Primary")
    L.append("")
    L.append("| metric | W1 | W2 | W3 |")
    L.append("|---|---|---|---|")
    for m in ("fault_detection_rate", "false_accept_rate", "final_decision_accuracy", "critical_fault_missed"):
        L.append(f"| {m} | {metrics['primary']['W1'][m]} | {metrics['primary']['W2'][m]} | {metrics['primary']['W3'][m]} |")
    L.append("")
    L.append("### Secondary")
    L.append("")
    L.append("| metric | W1 | W2 | W3 |")
    L.append("|---|---|---|---|")
    for m in ("artifact_access_rate", "unsupported_claim_rate", "rounds", "model_calls", "claude_calls",
              "raw_character_volume_proxy", "wall_clock_seconds", "human_interventions"):
        L.append(f"| {m} | {metrics['secondary']['W1'].get(m)} | {metrics['secondary']['W2'].get(m)} | {metrics['secondary']['W3'].get(m)} |")
    L.append("")
    L.append(f"- verifier_agreement_rate: {metrics.get('verifier_agreement_rate')}")
    L.append(f"- reproducibility: {metrics.get('reproducibility')}")
    L.append(f"- access_symmetry: {metrics.get('access_symmetry')}")
    L.append(f"- per-fault verdicts (scorer): " + "; ".join(
        f"{wf}=" + ",".join(f"{t}:{raw['workflows'][wf]['faults'][t]['verdict']}" for t in TASKS)
        for wf in ("W1", "W2", "W3")))
    L.append("")
    L.append("## VERIFIER RECOMPUTATION")
    L.append("")
    L.append(f"- verifier_output_sha256: {metrics['hashes'].get('verifier_output_sha256')}")
    L.append(f"- verifier_output_run2_sha256: {metrics['hashes'].get('verifier_output_run2_sha256')}")
    L.append(f"- agreement cells agree: {sum(1 for c in raw['verifier_agreement']['cells'] if c['agree'])}/{len(raw['verifier_agreement']['cells'])}")
    L.append("")
    L.append("## LIMITATIONS")
    L.append("")
    L.append("- Ground-truth isolation: procedural, not cryptographic/security isolation (ACCEPT_PROCEDURAL_FOR_V1).")
    L.append("- Token volume = raw character/message volume proxy (NOT_PROVIDER_TOKEN_COUNT).")
    L.append("- FALSE_ACCEPT automatic rule: ACCEPT decisions only; endorsement without ACCEPT token scored MISSED.")
    L.append("- final_decision vocabulary normalization: REJECT_* => REJECT; FLAG_FOR_REWORK counts incorrect (documented prereg vocabulary mismatch).")
    L.append("- Verdict DETECTED_CORRECT/WRONG classification uses pre-hashed keyword rules (verdict_rules.json), a deterministic heuristic.")
    L.append("- W0 human baseline unavailable; no human reference curve.")
    L.append("- Browser transport is UI-level; T0 results bound transport validity (A5: BLOCK_W3 on fail).")
    L.append("- Ground truth says every task contains exactly one fault; false-positive behavior beyond ACCEPT decisions not fully automated.")
    L.append("")
    L.append("## UNRESOLVED ISSUES")
    L.append("")
    L.append("- Human review of raw responses pending at GATE_2.")
    L.append("- Replay anchoring comparison pending human interpretation (non-scoring).")
    L.append("")
    L.append("## ORCHESTRATOR_INTERPRETATION")
    L.append("")
    L.append("**NON_AUTHORITATIVE** — no interpretation provided pre-GATE_2; metrics above speak for themselves. No winner declared.")
    L.append("")
    (out / "comparison.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
