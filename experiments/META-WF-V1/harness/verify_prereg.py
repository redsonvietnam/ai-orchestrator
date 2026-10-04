import hashlib, json, re, sys
from pathlib import Path

ROOT = Path("D:/ai-orchestrator/experiments/META-WF-V1")
errors = []

def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

# 1) SHA256SUMS integrity
for t in ["F1", "F2", "F3", "F4", "F5"]:
    d = ROOT / "tasks" / t
    for line in (d / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        h, rel = line.split("  ", 1)
        actual = sha256(d / rel)
        if actual != h:
            errors.append(f"SUMS mismatch {t}/{rel}")

# 2) PREREG.sha256 integrity
for line in (ROOT / "prereg/PREREG.sha256").read_text(encoding="utf-8").splitlines():
    h, rel = line.split("  ", 1)
    if sha256(ROOT / rel) != h:
        errors.append(f"PREREG mismatch {rel}")

# 3) GT isolation: no GT file/strings inside delivered bundles
BAD = ["correct_digit", "fault\": true", "fault=true", "answer=", "ground_truth", "GROUND_TRUTH", "temptation"]
for t in ["F1", "F2", "F3", "F4", "F5"]:
    d = ROOT / "tasks" / t
    for f in list((d / "input").rglob("*")) + list((d / "raw").rglob("*")) + list((d / "source").rglob("*")):
        if f.is_file():
            txt = f.read_text(encoding="utf-8", errors="replace")
            for b in BAD:
                if b in txt:
                    errors.append(f"GT-leak {b} in {t}/{f.relative_to(d)}")

# 4) Evidence chains re-derived
lock = json.loads((ROOT / "tasks/F1/input/token_class_locked.json").read_text(encoding="utf-8"))
built = json.loads((ROOT / "tasks/F1/input/token_class_built.json").read_text(encoding="utf-8"))
dig = json.loads((ROOT / "tasks/F1/input/digit_class_convention.json").read_text(encoding="utf-8"))
aff = json.loads((ROOT / "tasks/F1/input/affected_positions.json").read_text(encoding="utf-8"))
if not (lock["提"] == "H" and built["提"] == "D" and lock["提"] != built["提"]):
    errors.append("F1 lock/built chain broken")
if not all(dig[r["digit_at_i_positions"][0]] == "H" for r in aff["rows"]):
    errors.append("F1 digit evidence chain broken")

f2out = json.loads((ROOT / "tasks/F2/input/pipeline_output.json").read_text(encoding="utf-8"))
yan = json.loads((ROOT / "tasks/F2/input/yan_cnchar_letter_sequence.json").read_text(encoding="utf-8"))
lt = json.loads((ROOT / "tasks/F2/input/letter_table.json").read_text(encoding="utf-8"))
nc = json.loads((ROOT / "tasks/F2/input/name_class_table.json").read_text(encoding="utf-8"))
derived = nc[lt[yan["jian_letter_sequence"][0]]["name"]]
if not (derived == "D" and f2out["first_class"] == "H" and derived != f2out["first_class"]):
    errors.append(f"F2 chain broken: derived={derived} out={f2out['first_class']}")

f3g = json.loads((ROOT / "tasks/F3/input/golden_entry.json").read_text(encoding="utf-8"))
f3o = json.loads((ROOT / "tasks/F3/input/pipeline_output.json").read_text(encoding="utf-8"))
patch = (ROOT / "tasks/F3/input/sync_proposal.patch").read_text(encoding="utf-8")
if not (f3g["first"] == "Z" and f3o["first_class"] == "H" and '-    "first": "Z"' in patch and '+    "first": "H"' in patch):
    errors.append("F3 chain broken")

f4 = json.loads((ROOT / "tasks/F4/input/system_output_row.json").read_text(encoding="utf-8"))
ids4 = (ROOT / "tasks/F4/input/ids_line.txt").read_text(encoding="utf-8")
if not ("③" in ids4 and f4["secondary_anchor"] == "③" and f4["qualified"] is True
        and f4["placeholder_label"] is None and f4["provenance"] is None):
    errors.append("F4 chain broken")

f5s = json.loads((ROOT / "tasks/F5/input/spec_gate.json").read_text(encoding="utf-8"))
f5r = json.loads((ROOT / "tasks/F5/input/full_report_excerpt.json").read_text(encoding="utf-8"))
f5c = json.loads((ROOT / "tasks/F5/input/review_claim.json").read_text(encoding="utf-8"))
if not (f5s["B0_universe"] == 27584 and f5c["denominator_used"] == 27362
        and f5r["qualified_chars"] == 27172 and f5c["denominator_used"] != f5s["B0_universe"]):
    errors.append("F5 chain broken")
correct = round(f5r["qualified_chars"] / f5s["B0_universe"] * 100, 2)
gt = (ROOT / "prereg/GROUND_TRUTH.yaml").read_text(encoding="utf-8")
if f"{correct}%" not in gt:
    errors.append(f"GT missing correct rate {correct}%")

if errors:
    print("VERIFY FAIL:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("VERIFY PASS: sums, prereg hashes, GT isolation, all 5 evidence chains")
print(f"F5 correct figure: {f5r['qualified_chars']}/{f5s['B0_universe']} = {correct}%")
