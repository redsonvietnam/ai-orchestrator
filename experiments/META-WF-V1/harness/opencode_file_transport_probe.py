#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "runs" / "W2" / "opencode_prompt_transport"
FIXTURE = OUT / "input_prompt.bin"
TIMEOUT_SECONDS = 10


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    fixture = (
        'META-WF V1 deterministic --file transport fixture\n'
        'quote="\n'
        'percent=%\n'
        'ampersand=&\n'
        'exclamation=!\n'
        'backslash=\\\n'
        'unicode=Hán-Việt 漢字\n'
        'json_like={"text":"quote=\" percent=% ampersand=& exclamation=!"}\n'
    ).encode("utf-8")
    FIXTURE.write_bytes(fixture)

    resolved = shutil.which("opencode")
    raw = {
        "python_version": sys.version,
        "sys_executable": sys.executable,
        "cwd": str(Path.cwd()),
        "resolved_executable": resolved,
        "fixture_path": str(FIXTURE.resolve()),
        "input_byte_count": len(fixture),
        "input_sha256": sha256(fixture),
        "timeout_seconds": TIMEOUT_SECONDS,
        "child_spawned": False,
        "MODEL_EXECUTION_REACHED": False,
    }

    if not resolved or not os.path.isabs(resolved) or not resolved.lower().endswith(".cmd"):
        raw["terminal_state"] = "OPENCode_FILE_TRANSPORT_FIXTURE_BLOCKED"
        (OUT / "raw.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return 2

    argv = [resolved, "run", "--file", str(FIXTURE.resolve())]
    raw["argv_repr"] = repr(argv)

    started = time.monotonic()
    lifecycle = {
        "started_at": utc_now(),
        "timeout_seconds": TIMEOUT_SECONDS,
        "spawned": False,
        "model_execution_reached": False,
    }

    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(Path.cwd()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
    except OSError as exc:
        raw["terminal_state"] = "OPENCode_FILE_TRANSPORT_FIXTURE_BLOCKED"
        raw["error"] = str(exc)
        (OUT / "raw.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return 2

    lifecycle["spawned"] = True
    lifecycle["pid"] = proc.pid
    raw["child_spawned"] = True

    try:
        stdout, stderr = proc.communicate(timeout=TIMEOUT_SECONDS)
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        stdout = exc.output or b""
        stderr = exc.stderr or b""
        timed_out = True
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)

    duration_ms = round((time.monotonic() - started) * 1000, 3)
    exit_code = proc.returncode
    model_reached = timed_out

    (OUT / "stdout.bin").write_bytes(stdout)
    (OUT / "stderr.bin").write_bytes(stderr)

    raw.update({
        "transport": "OpenCode CLI --file",
        "argv_repr": repr(argv),
        "stdout_byte_count": len(stdout),
        "stderr_byte_count": len(stderr),
        "stdout_sha256": sha256(stdout),
        "stderr_sha256": sha256(stderr),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_ms": duration_ms,
        "MODEL_EXECUTION_REACHED": model_reached,
    })

    if model_reached:
        state = "OPENCode_FILE_TRANSPORT_REACHES_MODEL"
    elif exit_code == 0:
        state = "OPENCode_FILE_TRANSPORT_PASS"
    else:
        state = "OPENCode_FILE_TRANSPORT_REJECTED"

    raw["terminal_state"] = state
    lifecycle.update({
        "finished_at": utc_now(),
        "duration_ms": duration_ms,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "model_execution_reached": model_reached,
    })

    (OUT / "raw.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "lifecycle.json").write_text(json.dumps(lifecycle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    artifact_names = [
        "raw.json",
        "input_prompt.bin",
        "stdout.bin",
        "stderr.bin",
        "lifecycle.json",
    ]
    (OUT / "sha256sums.txt").write_text(
        "\n".join(
            f"{sha256((OUT / name).read_bytes())}  {name}"
            for name in artifact_names
        ) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "transport": "--file",
        "argv_contains_prompt_content": False,
        "input_sha256": sha256(fixture),
        "artifacts": artifact_names + ["sha256sums.txt", "artifact_manifest.json"],
    }
    (OUT / "artifact_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(state)
    return 0 if state == "OPENCode_FILE_TRANSPORT_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
