import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
WORKDIR = ROOT / "runs"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

WORKERS = {
    "claude": {"port": 9222, "url": "https://claude.ai/new", "profile": "profile-claude"},
    "chatgpt": {"port": 9223, "url": "https://chatgpt.com", "profile": "profile-chatgpt"},
    "gemini": {"port": 9224, "url": "https://gemini.google.com", "profile": "profile-gemini"},
}

ROLE_PROMPTS = {
    "claude": "You are the ARCHITECT. Solve the problem below and write complete, production-quality code with clear explanations.",
    "chatgpt": "You are the REVIEWER. Critique the draft: find bugs, edge cases, security issues, and design problems. Then output the corrected COMPLETE version.",
    "gemini": "You are the FINALIZER. Produce the final complete solution incorporating the review. Output only the final result, code blocks included.",
}


def launch_chrome(name, port, profile):
    profile_dir = ROOT / profile
    cmd = [
        CHROME,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    subprocess.Popen(cmd)
    for _ in range(30):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                if r.status == 200:
                    print(f"[chrome:{name}] CDP up on port {port} (profile: {profile_dir})")
                    return True
        except Exception:
            time.sleep(1)
    print(f"[chrome:{name}] FAILED to come up on port {port}")
    return False


def run_worker(name, prompt_text, out_name, model=None):
    w = WORKERS[name]
    prompt_file = WORKDIR / f"{out_name}.prompt.txt"
    out_file = WORKDIR / f"{out_name}.response.txt"
    prompt_file.write_text(prompt_text, encoding="utf-8")
    env = dict(os.environ)
    env["BU_NAME"] = f"worker-{name}"
    if model:
        env["BU_MODEL"] = model
    cmd = [
        sys.executable,
        "-u",
        str(ROOT / "worker.py"),
        "--name", name,
        "--port", str(w["port"]),
        "--url", w["url"],
        "--prompt-file", str(prompt_file),
        "--out", str(out_file),
    ]
    subprocess.run(cmd, env=env)
    return out_file.read_text(encoding="utf-8") if out_file.exists() else ""


def run_workers_parallel(jobs, model=None):
    procs = []
    for name, prompt_text, out_name in jobs:
        w = WORKERS[name]
        prompt_file = WORKDIR / f"{out_name}.prompt.txt"
        out_file = WORKDIR / f"{out_name}.response.txt"
        prompt_file.write_text(prompt_text, encoding="utf-8")
        env = dict(os.environ)
        env["BU_NAME"] = f"worker-{name}"
        if model:
            env["BU_MODEL"] = model
        cmd = [
            sys.executable,
            str(ROOT / "worker.py"),
            "--name", name,
            "--port", str(w["port"]),
            "--url", w["url"],
            "--prompt-file", str(prompt_file),
            "--out", str(out_file),
        ]
        procs.append((name, out_file, subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)))
    results = {}
    for name, out_file, proc in procs:
        out, err = proc.communicate()
        if out.strip():
            print(out.strip())
        if err.strip():
            print(err.strip()[-3000:])
        results[name] = out_file.read_text(encoding="utf-8") if out_file.exists() else ""
    return results


def pipeline(problem, model=None):
    WORKDIR.mkdir(exist_ok=True)
    board = {"problem": problem, "mode": "pipeline", "phases": []}
    print("== Phase 1/3: ARCHITECT (Claude tab) ==")
    r1 = run_worker("claude", f"{ROLE_PROMPTS['claude']}\n\nPROBLEM:\n{problem}", "phase1-claude", model)
    board["phases"].append({"worker": "claude", "response": r1})
    print("== Phase 2/3: REVIEWER (ChatGPT tab) ==")
    r2 = run_worker("chatgpt", f"{ROLE_PROMPTS['chatgpt']}\n\nPROBLEM:\n{problem}\n\nDRAFT:\n{r1}", "phase2-chatgpt", model)
    board["phases"].append({"worker": "chatgpt", "response": r2})
    print("== Phase 3/3: FINALIZER (Gemini tab) ==")
    r3 = run_worker("gemini", f"{ROLE_PROMPTS['gemini']}\n\nPROBLEM:\n{problem}\n\nDRAFT:\n{r1}\n\nREVIEW:\n{r2}", "phase3-gemini", model)
    board["phases"].append({"worker": "gemini", "response": r3})
    board["final"] = r3
    (WORKDIR / "board.json").write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
    (WORKDIR / "final.md").write_text(r3, encoding="utf-8")
    return r3


def swarm(problem, model=None):
    WORKDIR.mkdir(exist_ok=True)
    jobs = []
    for name in ("claude", "chatgpt", "gemini"):
        jobs.append((name, f"Solve the problem below independently. Write complete, production-quality code.\n\nPROBLEM:\n{problem}", f"swarm-{name}"))
    print("== Swarm: all 3 AI tabs working in parallel ==")
    results = run_workers_parallel(jobs, model)
    merged = "\n\n".join(f"=== {name.upper()} ===\n{text}" for name, text in results.items())
    print("== Synthesis: Gemini tab merges all answers ==")
    final = run_worker(
        "gemini",
        f"You are the SYNTHESIZER. Below are independent solutions to the same problem from Claude, ChatGPT, and Gemini. "
        f"Compare them, take the strongest parts, fix any errors, and output ONE final complete solution.\n\n"
        f"PROBLEM:\n{problem}\n\n{merged}",
        "swarm-final",
        model,
    )
    board = {"problem": problem, "mode": "swarm", "responses": results, "final": final}
    (WORKDIR / "board.json").write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
    (WORKDIR / "final.md").write_text(final, encoding="utf-8")
    return final


def require_key(model):
    if model.startswith(("gemini", "gemma")) and not os.environ.get("GOOGLE_API_KEY"):
        print("ERROR: GOOGLE_API_KEY not set. Get a FREE key at https://aistudio.google.com/apikey then run:")
        print('  $env:GOOGLE_API_KEY = "your-key"')
        sys.exit(1)
    if model.startswith("groq/") and not os.environ.get("GROQ_API_KEY"):
        print("ERROR: GROQ_API_KEY not set. Get a FREE key at https://console.groq.com/keys then run:")
        print('  $env:GROQ_API_KEY = "your-key"')
        sys.exit(1)


_MUTEX_HANDLE = None


def _acquire_single_instance():
    global _MUTEX_HANDLE
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _MUTEX_HANDLE = k32.CreateMutexW(None, False, "Local\\ai_orchestrator_single")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        print("another orchestrator instance is already running, exiting")
        sys.exit(1)


def main():
    import subprocess as _sp
    import traceback as _tb

    _orig_popen = _sp.Popen

    def _traced_popen(*a, **k):
        args = a[0] if a else k.get("args")
        print(f">> Popen pid={os.getpid()} args={args}", flush=True)
        _tb.print_stack()
        return _orig_popen(*a, **k)

    _sp.Popen = _traced_popen
    print(f"orchestrator start pid={os.getpid()}", flush=True)
    _acquire_single_instance()
    ap = argparse.ArgumentParser(description="Multi-AI-tab orchestrator (free stack: browser-use + Chrome CDP + Groq free tier)")
    ap.add_argument("problem", nargs="?", help="the problem to solve, or use --problem-file")
    ap.add_argument("--problem-file", help="path to a .txt/.md file containing the problem")
    ap.add_argument("--mode", choices=("pipeline", "swarm"), default="pipeline")
    ap.add_argument("--model", default=os.environ.get("BU_MODEL", "groq/openai/gpt-oss-120b,groq/openai/gpt-oss-20b"))
    ap.add_argument("--launch-only", action="store_true", help="only launch the 3 automation Chrome windows, then exit")
    args = ap.parse_args()

    require_key(args.model)

    if args.launch_only:
        for name, w in WORKERS.items():
            launch_chrome(name, w["port"], w["profile"])
        print("All automation Chrome windows launched. Log into each AI site once, then run the orchestrator.")
        return

    problem = args.problem
    if args.problem_file:
        problem = Path(args.problem_file).read_text(encoding="utf-8")
    if not problem:
        ap.error("provide a problem or --problem-file")

    for name, w in WORKERS.items():
        launch_chrome(name, w["port"], w["profile"])

    print(f"Mode: {args.mode} | Hands-LLM: {args.model} (free Gemini tier)")
    final = pipeline(problem, args.model) if args.mode == "pipeline" else swarm(problem, args.model)
    print("\n===== FINAL RESULT (saved to runs/final.md) =====")
    print(final[:4000])


if __name__ == "__main__":
    main()
