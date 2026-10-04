#!/usr/bin/env python3
"""Minimal deterministic subprocess observation runner.

Captures stdout, stderr, lifecycle timestamps, and exit code. It never
interprets or invokes an AI/provider itself.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_opencode_executable(command: list[str]) -> tuple[list[str], dict]:
    """Resolve bare opencode to the exact executable path Python can spawn."""
    if not command:
        raise ValueError("command requires a command")

    executable = command[0]
    resolution = {
        "original_executable": executable,
        "resolver": "literal-opencode-via-shutil.which",
        "applied": False,
        "resolved_executable": executable,
        "which_opencode": shutil.which("opencode"),
        "which_opencode_cmd": shutil.which("opencode.cmd"),
        "which_opencode_exe": shutil.which("opencode.exe"),
        "which_opencode_ps1": shutil.which("opencode.ps1"),
    }

    if executable.lower() != "opencode":
        return command, resolution

    resolved = resolution["which_opencode"]
    if not resolved:
        raise FileNotFoundError("shutil.which('opencode') returned no executable")

    resolved_command = [resolved, *command[1:]]
    resolution["applied"] = True
    resolution["resolved_executable"] = resolved
    return resolved_command, resolution


def run(command: list[str], out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = out_dir / "stdout.txt"
    stderr_path = out_dir / "stderr.log"
    resolved_command, executable_resolution = resolve_opencode_executable(command)
    started_at = now()
    started_mono = time.monotonic()

    proc = subprocess.Popen(
        resolved_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = proc.communicate()
    finished_at = now()
    duration_ms = round((time.monotonic() - started_mono) * 1000, 3)

    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    evidence = {
        "command": command,
        "resolved_command": resolved_command,
        "executable_resolution": executable_resolution,
        "pid": str(proc.pid),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
        "exit_code": proc.returncode,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
        "status": "PASS" if proc.returncode == 0 else "FAIL",
    }
    (out_dir / "lifecycle.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command:
        ap.error("command requires a command")
    try:
        evidence = run(command, Path(args.out_dir))
        print(json.dumps(evidence, sort_keys=True))
        return 0 if evidence["exit_code"] == 0 else 1
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
