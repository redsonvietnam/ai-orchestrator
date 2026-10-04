import hashlib, json, sys
from pathlib import Path
import yaml

R = Path("D:/ai-orchestrator/experiments/META-WF-V1")

# (file, old, new, kind) — kind: "contains" = old must be substring of new;
# "tokens" = each token must be substring of new; "join" = both halves in new
PATCHES = [
    ("prereg/TASKS.yaml",
     "F1: stroke token mapping consistency (origin: V4-CHOT Q2(a) 提→H decision; cross-source digit evidence)",
     "F1: 'stroke token mapping consistency (origin: V4-CHOT Q2(a) 提→H decision; cross-source digit evidence)'",
     "quote"),
    ("prereg/TASKS.yaml",
     "F2: regex alternative tiebreak (origin: V9 諩/䛡 first-match branch fault, real stroke-input (1|4))",
     "F2: 'regex alternative tiebreak (origin: V9 諩/䛡 first-match branch fault, real stroke-input (1|4))'",
     "quote"),
    ("prereg/TASKS.yaml",
     "F3: post-hoc golden edit temptation (origin: golden freeze governance V4-CHOT/V9)",
     "F3: 'post-hoc golden edit temptation (origin: golden freeze governance V4-CHOT/V9)'",
     "quote"),
    ("prereg/TASKS.yaml",
     "F4: placeholder-derived data without provenance (origin: COMPOSITE_PLACEHOLDER policy, 131 flagged chars)",
     "F4: 'placeholder-derived data without provenance (origin: COMPOSITE_PLACEHOLDER policy, 131 flagged chars)'",
     "quote"),
    ("prereg/TASKS.yaml",
     "F5: subset universe used for full-universe gate claim (origin: B0=27584 vs narrower denominators)",
     "F5: 'subset universe used for full-universe gate claim (origin: B0=27584 vs narrower denominators)'",
     "quote"),
    ("prereg/TASKS.yaml",
     "inputs_each: [prereg subset: TASKS+SCORING+METRICS (NOT GROUND_TRUTH), raw artifacts, task instructions]",
     "inputs_each: ['prereg subset: TASKS+SCORING+METRICS (NOT GROUND_TRUTH)', 'raw artifacts', 'task instructions']",
     "tokens"),
    ("prereg/TASKS.yaml",
     "reviewer1: ChatGPT, reviewer2: Claude (relayed response of reviewer1 included, per real relay)",
     "reviewer1: 'ChatGPT, reviewer2: Claude (relayed response of reviewer1 included, per real relay)'",
     "quote"),
    ("prereg/GROUND_TRUTH.yaml",
     '      - "fix" by editing the locked spec to match the build (wrong direction)"',
     '''      - '"fix" by editing the locked spec to match the build (wrong direction)"' ''',
     "quote"),
    ("prereg/GROUND_TRUTH.yaml",
     "    injected: built table copy has one changed row (提: H -> D)",
     "    injected: 'built table copy has one changed row (提: H -> D)'",
     "quote"),
    ("prereg/SCORING.yaml",
     '  w1: summary frozen sha256 before dispatch; summary must carry\n      "AUTHORITY: NON_AUTHORITATIVE"; ground truth never in summary inputs',
     '  w1: \'summary frozen sha256 before dispatch; summary must carry "AUTHORITY: NON_AUTHORITATIVE"; ground truth never in summary inputs\'',
     "join"),
]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


applied = 0
by_file = {}
for f, old, new, kind in PATCHES:
    p = R / f
    txt = p.read_text(encoding="utf-8")
    if kind == "quote":
        assert "'" not in old, old[:50]
        assert new.replace("'", "").rstrip() == old, (old, new)
    elif kind == "tokens":
        for tok in ("prereg subset: TASKS+SCORING+METRICS (NOT GROUND_TRUTH)",
                    "raw artifacts", "task instructions"):
            assert tok in new, tok
    elif kind == "join":
        a, b = old.split("\n")
        assert a.split(": ", 1)[1] in new and b.strip() in new, (a, b)
    cnt_old = txt.count(old)
    cnt_new = txt.count(new)
    if cnt_old == 1:
        txt = txt.replace(old, new)
        p.write_text(txt, encoding="utf-8")
        applied += 1
        by_file[f] = by_file.get(f, 0) + 1
    elif cnt_old == 0 and cnt_new == 1:
        print(f"already applied: {f} :: {old[:60]!r}")
    else:
        print(f"ABORT: {f} old={cnt_old} new={cnt_new} for {old[:70]!r}")
        sys.exit(1)
print("applied:", applied, by_file)

# verify: only target lines changed (old text preserved as substring) + parse OK
for f in ("prereg/TASKS.yaml", "prereg/GROUND_TRUTH.yaml", "prereg/SCORING.yaml", "prereg/METRICS.yaml"):
    d = yaml.safe_load((R / f).read_text(encoding="utf-8"))
    assert d is not None
    print(f, "pyyaml OK")

# semantic spot checks (values must equal pre-patch text)
gt = yaml.safe_load((R / "prereg/GROUND_TRUTH.yaml").read_text(encoding="utf-8"))
assert gt["tasks"]["F1"]["forbidden_false_pass"] == [
    "accept built table as-is without flagging the 提 row",
    '"fix" by editing the locked spec to match the build (wrong direction)"',
], gt["tasks"]["F1"]["forbidden_false_pass"]
assert gt["tasks"]["F1"]["injected"] == "built table copy has one changed row (提: H -> D)"
tk = yaml.safe_load((R / "prereg/TASKS.yaml").read_text(encoding="utf-8"))
assert tk["fault_corpus"]["F1"].startswith("stroke token mapping consistency (origin: V4-CHOT")
assert tk["workflows"]["W3"]["phases"]["1_blind"]["inputs_each"] == [
    "prereg subset: TASKS+SCORING+METRICS (NOT GROUND_TRUTH)", "raw artifacts", "task instructions"]
sc = yaml.safe_load((R / "prereg/SCORING.yaml").read_text(encoding="utf-8"))
assert sc["blinding_enforcement"]["w1"] == (
    'summary frozen sha256 before dispatch; summary must carry "AUTHORITY: NON_AUTHORITATIVE"; '
    "ground truth never in summary inputs")
print("semantic spot checks OK")

# regenerate PREREG.sha256 (same order/format as original)
lines = []
for name in ["TASKS.yaml", "GROUND_TRUTH.yaml", "METRICS.yaml", "SCORING.yaml"]:
    lines.append(f"{sha(R / 'prereg' / name)}  prereg/{name}")
(R / "prereg/PREREG.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")

new_hashes = {
    "prereg_file_sha256": sha(R / "prereg/PREREG.sha256"),
    "ground_truth_sha256": sha(R / "prereg/GROUND_TRUTH.yaml"),
    "tasks_yaml_sha256": sha(R / "prereg/TASKS.yaml"),
    "metrics_sha256": sha(R / "prereg/METRICS.yaml"),
    "scoring_sha256": sha(R / "prereg/SCORING.yaml"),
}
print(json.dumps(new_hashes, indent=2))
