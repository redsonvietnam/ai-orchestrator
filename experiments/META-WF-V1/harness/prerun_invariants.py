import hashlib, json, subprocess, sys, time
from pathlib import Path
import yaml

ROOT = Path("D:/ai-orchestrator/experiments/META-WF-V1")
HAN = Path("D:/hanstroke-demo")
APPROVAL = yaml.safe_load((ROOT / "GATE1_APPROVAL.yaml").read_text(encoding="utf-8"))
FH = dict(APPROVAL["freeze_hashes_at_approval"])
ADD_PATH = ROOT / "GATE1_ADDENDUM.yaml"
ADD = yaml.safe_load(ADD_PATH.read_text(encoding="utf-8")) if ADD_PATH.exists() else {}
_prereg_fix = (ADD.get("prereg_syntax_fix") or {}).get("new_hashes") or {}
FH.update(_prereg_fix)  # human-approved anchors supersede approval-time ones

def h(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

checks = []

def check(name, ok, detail=""):
    checks.append({"check": name, "ok": bool(ok), "detail": detail})

# 1 prereg hash
check("prereg_hash", h(ROOT / "prereg/PREREG.sha256") == FH["prereg_file_sha256"],
      h(ROOT / "prereg/PREREG.sha256"))
# 2 ground-truth hash
check("ground_truth_hash", h(ROOT / "prereg/GROUND_TRUTH.yaml") == FH["ground_truth_sha256"],
      h(ROOT / "prereg/GROUND_TRUTH.yaml"))
# scoring hash (+ metrics + tasks listed inside prereg file check; explicit too)
check("scoring_hash", h(ROOT / "prereg/SCORING.yaml") == FH["scoring_sha256"],
      h(ROOT / "prereg/SCORING.yaml"))
check("metrics_hash", h(ROOT / "prereg/METRICS.yaml") == FH["metrics_sha256"],
      h(ROOT / "prereg/METRICS.yaml"))
check("tasks_yaml_hash", h(ROOT / "prereg/TASKS.yaml") == FH["tasks_yaml_sha256"],
      h(ROOT / "prereg/TASKS.yaml"))
# PREREG.sha256 internal validity
internal_ok = True
for line in (ROOT / "prereg/PREREG.sha256").read_text(encoding="utf-8").splitlines():
    hh, rel = line.split("  ", 1)
    if h(ROOT / rel) != hh:
        internal_ok = False
check("prereg_sha256file_valid", internal_ok)

# 4 task fixtures hash (addendum overrides changed tasks)
sums_anchors = dict(FH["task_sums"])
addendum_path = ROOT / "GATE1_ADDENDUM.yaml"
if addendum_path.exists():
    add = yaml.safe_load(addendum_path.read_text(encoding="utf-8"))
    sums_anchors.update(add.get("changed_task_sums") or {})
    for k, v in (add.get("unchanged_task_sums") or {}).items():
        if FH["task_sums"].get(k) != v:
            sums_anchors[k] = "__PARENT_MISMATCH__"
sums_ok = True
details = []
for t, expected in sums_anchors.items():
    if expected == "__PARENT_MISMATCH__":
        sums_ok = False
        details.append(f"{t} addendum unchanged-hash contradicts parent anchor")
        continue
    p = ROOT / "tasks" / t / "SHA256SUMS"
    actual = h(p)
    if actual != expected:
        sums_ok = False
        details.append(f"{t} sums file changed")
    for line in p.read_text(encoding="utf-8").splitlines():
        hh, rel = line.split("  ", 1)
        if h(ROOT / "tasks" / t / rel) != hh:
            sums_ok = False
            details.append(f"{t}/{rel} content changed")
check("task_fixtures_hash", sums_ok, "; ".join(details))

# 5 required artifacts
required = [
    "prereg/TASKS.yaml", "prereg/GROUND_TRUTH.yaml", "prereg/METRICS.yaml",
    "prereg/SCORING.yaml", "prereg/PREREG.sha256", "GATE1_APPROVAL.yaml",
    "GATE1_ADDENDUM.yaml",
    "transport/T0_SPEC.md", "harness/build_tasks.py", "harness/verify_prereg.py",
    "README.md",
]
for t in ["F1", "F2", "F3", "F4", "F5"]:
    required += [f"tasks/{t}/SHA256SUMS", f"tasks/{t}/metadata.json",
                 f"tasks/{t}/input", f"tasks/{t}/raw", f"tasks/{t}/source"]
missing = [r for r in required if not (ROOT / r).exists()]
check("required_artifacts_exist", not missing, ",".join(missing))

# 6 old workspace path unreferenced (pattern built non-contiguously; self excluded)
old_p1 = "D:" + chr(92) + "META" + chr(45) + "WF-V1"
old_p2 = "D:" + chr(47) + "META" + chr(45) + "WF-V1"
old_refs = []
for f in Path("D:/ai-orchestrator/experiments").rglob("*"):
    if not f.is_file() or f.name == "prerun_invariants.py":
        continue
    try:
        txt = f.read_text(encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, OSError):
        continue
    if old_p1 in txt or old_p2 in txt:
        old_refs.append(str(f))
check("old_workspace_path_unreferenced", not old_refs, ",".join(old_refs))

# 7 no production HANSTROKE changes
prod_ok = True
prod_detail = []
try:
    diff = subprocess.run(["git", "-C", str(HAN), "diff", "--name-only"],
                          capture_output=True, text=True, timeout=30)
    changed = [l for l in diff.stdout.splitlines() if l.strip()]
    allowed_modified = {"cache_hanstroke/human_screen_form.md"}
    bad = [c for c in changed if c not in allowed_modified]
    if bad:
        prod_ok = False
        prod_detail.append("modified: " + ",".join(bad))
    untracked = subprocess.run(["git", "-C", str(HAN), "status", "--porcelain"],
                               capture_output=True, text=True, timeout=30)
    utr = [l[3:].strip() for l in untracked.stdout.splitlines() if l.startswith("??")]
    bad_u = [u for u in utr if not (u.startswith("cache_hanstroke/") or u.startswith("experiment/"))]
    if bad_u:
        prod_ok = False
        prod_detail.append("untracked: " + ",".join(bad_u))
except Exception as e:
    prod_ok = False
    prod_detail.append(f"git error: {e}")
bench = (HAN / "benchmark_v3.py").read_text(encoding="utf-8")
if "83d444d66bf594b095ed3a3424a86dcb2f4624c703bef91d3f885181500a569d" not in bench:
    prod_ok = False
    prod_detail.append("GOLDEN_FROZEN_SHA256 constant changed")
if "GATE_THRESHOLD_PCT = 95.0" not in bench:
    prod_ok = False
    prod_detail.append("GATE_THRESHOLD_PCT changed")
check("no_production_changes", prod_ok, "; ".join(prod_detail))

# 8 no post-prereg amendment (hash anchors captured at approval + mtime ordering)
amend_ok = True
amend_detail = []
prereg_mtime = (ROOT / "prereg/PREREG.sha256").stat().st_mtime
for name in ["TASKS.yaml", "GROUND_TRUTH.yaml", "METRICS.yaml", "SCORING.yaml"]:
    if (ROOT / "prereg" / name).stat().st_mtime > prereg_mtime + 1:
        amend_ok = False
        amend_detail.append(f"{name} newer than PREREG.sha256")
if h(ROOT / "prereg/PREREG.sha256") != FH["prereg_file_sha256"]:
    amend_ok = False
    amend_detail.append("PREREG.sha256 content changed vs approval anchor")
check("no_post_prereg_amendment", amend_ok, "; ".join(amend_detail))

failed = [c for c in checks if not c["ok"]]
result = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checks": checks,
          "verdict": "PASS" if not failed else "STOP + HUMAN_REQUIRED"}
print(json.dumps(result, indent=2, ensure_ascii=False))
sys.exit(0 if not failed else 1)
