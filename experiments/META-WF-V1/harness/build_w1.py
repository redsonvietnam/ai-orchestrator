#!/usr/bin/env python3
# harness/build_w1.py — build W1 artifacts BEFORE any dispatch.
# summary.md: mechanical digest of input/+raw/ ONLY (no GT, no fault
# conclusions), header AUTHORITY: NON_AUTHORITATIVE, sha256 frozen to
# runs/W1/summary.sha256 prior to dispatch (SCORING.yaml blinding w1).
# Also writes prompts, access_log.json (delivered set + bundle hash).
import hashlib, json, sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
W1 = R / "runs" / "W1"
TASKS = ("F1", "F2", "F3", "F4", "F5")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(p.read_bytes())


def delivered_files():
    out = []
    for t in TASKS:
        td = R / "tasks" / t
        for sub in ("input", "raw", "source"):
            d = td / sub
            if d.exists():
                for f in sorted(d.rglob("*")):
                    if f.is_file():
                        out.append(f)
        out.append(td / "SHA256SUMS")
    return out


def bundle_hash(files):
    lines = [f"{sha256_file(f)}  {f.relative_to(R).as_posix()}" for f in sorted(files, key=lambda p: p.as_posix())]
    return sha256_bytes("\n".join(lines).encode("utf-8")), lines


def build_summary() -> str:
    L = ["AUTHORITY: NON_AUTHORITATIVE", "",
         "META-WF V1 — W1 orchestrator summary (author: OPENCODE)",
         "Sources used: tasks/F*/input/ and tasks/F*/raw/ ONLY.",
         "prereg/GROUND_TRUTH.yaml was NOT read for this summary.",
         "This is a structured digest, not an assessment: no consistency",
         "judgments or fault conclusions are included.", ""]
    for t in TASKS:
        L.append(f"## {t}")
        files = []
        for sub in ("input", "raw"):
            d = R / "tasks" / t / sub
            if d.exists():
                files += sorted(p for p in d.rglob("*") if p.is_file())
        for f in files:
            rel = f.relative_to(R).as_posix()
            L.append(f"### FILE: {rel}")
            L.append("```")
            L.append(f.read_text(encoding="utf-8", errors="replace").rstrip())
            L.append("```")
            L.append("")
    L.append("## Open questions")
    L.append("- None posed by the orchestrator. Assess each package independently.")
    L.append("")
    return "\n".join(L)


def main():
    W1.mkdir(parents=True, exist_ok=True)
    (W1 / "prompts").mkdir(exist_ok=True)

    summary = build_summary()
    summary_path = W1 / "summary.md"
    summary_path.write_bytes(summary.encode("utf-8"))
    summary_sha = sha256_file(summary_path)
    (W1 / "summary.sha256").write_text(f"{summary_sha}  runs/W1/summary.md\n", encoding="utf-8")

    files = delivered_files()
    bhash, blines = bundle_hash(files)
    access = {
        "workflow": "W1",
        "delivered_files": [f.relative_to(R).as_posix() for f in sorted(files, key=lambda p: p.as_posix())],
        "excluded": ["metadata.json", "prereg/GROUND_TRUTH.yaml"],
        "bundle_sha256": bhash,
        "summary_sha256": summary_sha,
    }
    (W1 / "access_log.json").write_text(json.dumps(access, indent=2) + "\n", encoding="utf-8")

    instructions = (R / "harness" / "review_instructions.md").read_text(encoding="utf-8")
    bundle_text = []
    for f in sorted(files, key=lambda p: p.as_posix()):
        rel = f.relative_to(R).as_posix()
        bundle_text.append(f"===== FILE: {rel} =====")
        bundle_text.append(f.read_text(encoding="utf-8", errors="replace").rstrip())
        bundle_text.append("===== END FILE =====")
        bundle_text.append("")
    bundle_block = "\n".join(bundle_text)

    common = (instructions + "\n\n## Orchestrator summary (W1, frozen before dispatch)\n\n"
              + summary + "\n\n## Artifact bundle (delivered files verbatim)\n\n" + bundle_block)
    chatgpt_prompt = ("You are reviewer 1 in a two-reviewer relay. Review the bundle per the "
                      "instructions. Output the single fenced ```json object only.\n\n" + common)
    (W1 / "prompts" / "chatgpt.txt").write_bytes(chatgpt_prompt.encode("utf-8"))
    access["prompt_chatgpt_sha256"] = sha256_bytes(chatgpt_prompt.encode("utf-8"))

    print(json.dumps({
        "summary_sha256": summary_sha,
        "bundle_sha256": bhash,
        "delivered_files": len(files),
        "chatgpt_prompt_sha256": access["prompt_chatgpt_sha256"],
        "chatgpt_prompt_chars": len(chatgpt_prompt),
    }, indent=2))


def build_claude_prompt(chatgpt_response_text: str):
    files = delivered_files()
    instructions = (R / "harness" / "review_instructions.md").read_text(encoding="utf-8")
    summary = (W1 / "summary.md").read_text(encoding="utf-8")
    bundle_text = []
    for f in sorted(files, key=lambda p: p.as_posix()):
        rel = f.relative_to(R).as_posix()
        bundle_text.append(f"===== FILE: {rel} =====")
        bundle_text.append(f.read_text(encoding="utf-8", errors="replace").rstrip())
        bundle_text.append("===== END FILE =====")
        bundle_text.append("")
    bundle_block = "\n".join(bundle_text)
    common = (instructions + "\n\n## Orchestrator summary (W1, frozen before dispatch)\n\n"
              + summary + "\n\n## Artifact bundle (delivered files verbatim)\n\n" + bundle_block)
    prompt = ("You are reviewer 2 in a two-reviewer relay. The relayed response of reviewer 1 "
              "(ChatGPT) is included below, per the real relay workflow. Review the bundle "
              "yourself per the instructions and output the single fenced ```json object only.\n\n"
              + common + "\n\n## Relayed response of reviewer 1 (ChatGPT)\n\n"
              + chatgpt_response_text)
    (W1 / "prompts" / "claude.txt").write_bytes(prompt.encode("utf-8"))
    access_path = W1 / "access_log.json"
    access = json.loads(access_path.read_text(encoding="utf-8"))
    access["prompt_claude_sha256"] = sha256_bytes(prompt.encode("utf-8"))
    access["relay"] = "reviewer1 response included verbatim per TASKS.yaml reviewer2 spec"
    access_path.write_text(json.dumps(access, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"claude_prompt_sha256": access["prompt_claude_sha256"],
                      "claude_prompt_chars": len(prompt)}, indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "claude":
        build_claude_prompt(sys.stdin.read())
    else:
        main()
