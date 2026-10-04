#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "runs" / "W2" / "opencode_server_probe"
PORT = 4097
BASE = f"http://127.0.0.1:{PORT}"
START_TIMEOUT = 10.0
HTTP_TIMEOUT = 5.0


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def get(url):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return r.status, r.read(), dict(r.headers)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    exe = shutil.which("opencode")
    argv = [exe, "serve", "--hostname", "127.0.0.1", "--port", str(PORT)] if exe else []
    lifecycle = {"started_at": now(), "port": PORT, "ready": False, "stopped": False}
    raw = {
        "python_version": sys.version,
        "sys_executable": sys.executable,
        "cwd": str(Path.cwd()),
        "executable": exe,
        "argv_repr": repr(argv),
        "port": PORT,
        "base_url": BASE,
        "message_model_provider_execution": False,
    }

    if not exe or not os.path.isabs(exe) or not exe.lower().endswith(".cmd"):
        raw["terminal_state"] = "OPENCode_SERVER_START_BLOCKED"
        (OUT / "raw.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        return 2

    stdout_path = OUT / "server_stdout.bin"
    stderr_path = OUT / "server_stderr.bin"
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            argv, cwd=str(Path.cwd()), shell=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except OSError as exc:
        raw["error"] = str(exc)
        raw["terminal_state"] = "OPENCode_SERVER_START_BLOCKED"
        (OUT / "raw.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        return 2

    raw["server_pid"] = proc.pid
    lifecycle["pid"] = proc.pid
    health = None
    doc = None
    ready = False
    deadline = time.monotonic() + START_TIMEOUT
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            try:
                status, body, headers = get(BASE + "/global/health")
                health = {"status": status, "headers": headers, "body": body.decode("utf-8", "replace")}
                ready = status == 200
                if ready:
                    break
            except Exception:
                time.sleep(0.2)

        startup_ms = round((time.monotonic() - started) * 1000, 3)
        raw["startup_duration_ms"] = startup_ms
        raw["health"] = health
        lifecycle["ready"] = ready
        lifecycle["startup_duration_ms"] = startup_ms

        if not ready:
            raw["terminal_state"] = "OPENCode_SERVER_START_BLOCKED"
            return 3

        status, body, headers = get(BASE + "/doc")
        doc = {"status": status, "headers": headers, "body": body.decode("utf-8", "replace")}
        (OUT / "health.json").write_text(json.dumps(health, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (OUT / "openapi.json").write_bytes(body)

        spec = json.loads(doc["body"])
        raw["openapi_sha256"] = digest(body)
        raw["openapi_version"] = spec.get("openapi")
        raw["message_schema_discovered"] = False
        raw["file_text_parts_schema_discovered"] = False
        raw["schema_findings"] = {}

        paths = spec.get("paths", {})
        for path, item in paths.items():
            if not isinstance(item, dict):
                continue
            for method, operation in item.items():
                if method.lower() not in {"post", "put", "patch"} or not isinstance(operation, dict):
                    continue
                blob = json.dumps(operation, ensure_ascii=False).lower()
                if "session" in path.lower() or "session" in blob:
                    raw["message_schema_discovered"] = raw["message_schema_discovered"] or "message" in blob
                if "message" in path.lower() or "message" in blob:
                    raw["message_schema_discovered"] = True
                    raw["schema_findings"][f"{method.upper()} {path}"] = operation

        raw["file_text_parts_schema_discovered"] = any(
            token in json.dumps(spec, ensure_ascii=False).lower()
            for token in ["filepart", "textpart", "attachment", "file", "text"]
        )

        raw["terminal_state"] = "OPENCode_SERVER_API_DISCOVERY_PASS"
        return 0
    except Exception as exc:
        raw["error"] = repr(exc)
        raw["terminal_state"] = "OPENCode_SERVER_API_DISCOVERY_BLOCKED"
        return 4
    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
            stdout, stderr = proc.communicate(timeout=2)
        except Exception:
            stdout, stderr = b"", b""
        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        lifecycle["finished_at"] = now()
        lifecycle["exit_code"] = proc.returncode
        lifecycle["stopped"] = True
        lifecycle["stdout_sha256"] = digest(stdout)
        lifecycle["stderr_sha256"] = digest(stderr)
        (OUT / "lifecycle.json").write_text(json.dumps(lifecycle, indent=2) + "\n", encoding="utf-8")
        (OUT / "raw.json").write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        names = ["raw.json", "server_stdout.bin", "server_stderr.bin", "health.json", "openapi.json", "lifecycle.json"]
        sums = []
        for name in names:
            p = OUT / name
            if p.exists():
                sums.append(f"{digest(p.read_bytes())}  {name}")
        (OUT / "sha256sums.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
        manifest = {
            "artifacts": names + ["sha256sums.txt", "artifact_manifest.json"],
            "http_methods_used": ["GET"],
            "http_paths": ["/global/health", "/doc"],
            "post_message_called": False,
            "model_provider_execution": False,
        }
        (OUT / "artifact_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(raw.get("terminal_state", "OPENCode_SERVER_API_DISCOVERY_BLOCKED"))


if __name__ == "__main__":
    raise SystemExit(main())
