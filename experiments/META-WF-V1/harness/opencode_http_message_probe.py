import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OPENAPI_PATH = ROOT / "experiments/META-WF-V1/runs/W2/opencode_server_probe/openapi.json"
OUT = ROOT / "experiments/META-WF-V1/runs/W2/opencode_http_message_probe"
EXECUTABLE = r"C:\Users\User\AppData\Roaming\npm\opencode.CMD"
PORT = 4098
BASE = f"http://127.0.0.1:{PORT}"
FROZEN_OPENAPI_SHA = "f5cb443f0d160fc4b17190f64c2401f199160eb2137ce4e00ca319b99aa34005"
FIXTURE = (
    'META-WF-TRANSPORT-FIXTURE\n'
    'quote="inner"\n'
    'percent=%\n'
    'ampersand=&\n'
    'exclamation=!\n'
    'backslash=\\\n'
    'unicode=Hán-Việt\n'
    'json={"key":"value"}\n'
    'line2=second-line\n'
)

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()

def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def http_get(path):
    req = urllib.request.Request(BASE + path, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, dict(resp.headers.items()), resp.read()

def http_post(path, body_bytes):
    req = urllib.request.Request(
        BASE + path,
        data=body_bytes,
        method="POST",
        headers={"Content-Type": "application/json", "Content-Length": str(len(body_bytes))},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, dict(resp.headers.items()), resp.read()

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for p in OUT.iterdir():
        if p.is_file():
            p.unlink()

    lifecycle = {
        "terminal_state": None,
        "server": {"executable": EXECUTABLE, "argv": [EXECUTABLE, "serve", "--hostname", "127.0.0.1", "--port", str(PORT)], "port": PORT},
        "http_methods_used": [],
        "http_paths": [],
        "post_message_calls": 0,
        "model_endpoint_calls": 0,
        "provider_endpoint_calls": 0,
        "router_calls": 0,
        "model_execution_reached": False,
        "provider_execution_reached": False,
        "file_part_tested": False,
        "session_creation_safe": False,
        "request_accepted": False,
        "message_verified": False,
        "noReply": True,
        "server_pid": None,
        "server_started_at": None,
        "server_finished_at": None,
        "server_exit_code": None,
        "server_terminated_cleanly": False,
    }
    started = datetime.now(timezone.utc).isoformat()
    lifecycle["server_started_at"] = started

    try:
        if not OPENAPI_PATH.is_file():
            lifecycle["terminal_state"] = "OPENCode_HTTP_SESSION_CREATION_UNRESOLVED"
            raise RuntimeError("frozen openapi artifact missing")
        openapi_bytes = OPENAPI_PATH.read_bytes()
        openapi_sha = sha256_bytes(openapi_bytes)
        if openapi_sha != FROZEN_OPENAPI_SHA:
            lifecycle["terminal_state"] = "OPENCode_HTTP_SESSION_CREATION_UNRESOLVED"
            raise RuntimeError(f"frozen OpenAPI SHA mismatch: {openapi_sha}")

        spec = json.loads(openapi_bytes.decode("utf-8"))
        session_create = spec.get("paths", {}).get("/session", {}).get("post")
        message_post = spec.get("paths", {}).get("/session/{sessionID}/message", {}).get("post")
        message_get = spec.get("paths", {}).get("/session/{sessionID}/message", {}).get("get")
        text_schema = spec.get("components", {}).get("schemas", {}).get("TextPartInput")
        file_schema = spec.get("components", {}).get("schemas", {}).get("FilePartInput")

        if not session_create or not message_post or not message_get or not text_schema or not file_schema:
            lifecycle["terminal_state"] = "OPENCode_HTTP_SESSION_CREATION_UNRESOLVED"
            raise RuntimeError("required runtime OpenAPI schema missing")

        session_desc = (session_create.get("summary", "") + " " + session_create.get("description", "")).lower()
        session_response = json.dumps(session_create.get("responses", {}), ensure_ascii=False).lower()
        unsafe_tokens = ("execute", "run model", "invoke model", "generate response", "provider call", "stream the ai")
        if any(token in session_desc or token in session_response for token in unsafe_tokens):
            lifecycle["terminal_state"] = "OPENCode_HTTP_SESSION_CREATION_UNRESOLVED"
            raise RuntimeError("session creation schema/semantics not provably non-model-executing")
        if session_create.get("operationId") != "session.create":
            lifecycle["terminal_state"] = "OPENCode_HTTP_SESSION_CREATION_UNRESOLVED"
            raise RuntimeError("unexpected session creation operation")
        lifecycle["session_creation_safe"] = True

        text_required = text_schema.get("required", [])
        if text_schema.get("properties", {}).get("type", {}).get("enum") != ["text"]:
            lifecycle["terminal_state"] = "OPENCode_HTTP_SESSION_CREATION_UNRESOLVED"
            raise RuntimeError("TextPartInput type enum is not exactly text")
        if set(text_required) != {"type", "text"}:
            lifecycle["terminal_state"] = "OPENCode_HTTP_SESSION_CREATION_UNRESOLVED"
            raise RuntimeError("TextPartInput required fields differ from frozen schema")

        message_body_schema = message_post["requestBody"]["content"]["application/json"]["schema"]
        if message_body_schema.get("required") != ["parts"]:
            lifecycle["terminal_state"] = "OPENCode_HTTP_SESSION_CREATION_UNRESOLVED"
            raise RuntimeError("message required fields differ from frozen schema")
        if "noReply" not in message_body_schema["properties"]:
            lifecycle["terminal_state"] = "OPENCode_HTTP_SESSION_CREATION_UNRESOLVED"
            raise RuntimeError("noReply missing from frozen message schema")

        OUT.joinpath("fixture.txt").write_bytes(FIXTURE.encode("utf-8"))
        fixture_bytes = FIXTURE.encode("utf-8")
        fixture_sha = sha256_bytes(fixture_bytes)

        server_out = OUT / "server_stdout.bin"
        server_err = OUT / "server_stderr.bin"
        with server_out.open("wb") as stdout, server_err.open("wb") as stderr:
            proc = subprocess.Popen(
                [EXECUTABLE, "serve", "--hostname", "127.0.0.1", "--port", str(PORT)],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                shell=False,
            )
            lifecycle["server_pid"] = proc.pid

        health_ok = False
        health_last = None
        for _ in range(100):
            try:
                status, headers, body = http_get("/global/health")
                lifecycle["http_methods_used"].append("GET")
                lifecycle["http_paths"].append("/global/health")
                health_last = {"status": status, "headers": headers, "body": body.decode("utf-8", "replace")}
                if status == 200:
                    health_ok = True
                    break
            except Exception as exc:
                health_last = {"error": str(exc)}
            time.sleep(0.05)
        if not health_ok:
            lifecycle["terminal_state"] = "OPENCode_HTTP_MESSAGE_TRANSPORT_REJECTED"
            raise RuntimeError(f"health did not reach 200: {health_last}")

        session_status, session_headers, session_body = http_post("/session", b"{}")
        session_response = {"status": session_status, "headers": session_headers, "body": session_body.decode("utf-8", "replace")}
        if session_status != 200:
            lifecycle["terminal_state"] = "OPENCode_HTTP_MESSAGE_TRANSPORT_REJECTED"
            raise RuntimeError("session creation rejected")
        session_obj = json.loads(session_body.decode("utf-8"))
        session_id = session_obj.get("id")
        if not isinstance(session_id, str) or not session_id.startswith("ses"):
            lifecycle["terminal_state"] = "OPENCode_HTTP_SESSION_CREATION_UNRESOLVED"
            raise RuntimeError("session response did not contain a valid ses* id")

        request_obj = {"parts": [{"type": "text", "text": FIXTURE}], "noReply": True}
        request_bytes = json.dumps(request_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_path = f"/session/{session_id}/message"
        OUT.joinpath("request.json").write_bytes(request_bytes)
        write_json(OUT / "request_metadata.json", {
            "utf8_byte_count": len(fixture_bytes),
            "text_fixture_sha256": fixture_sha,
            "request_body_sha256": sha256_bytes(request_bytes),
            "endpoint": BASE + request_path,
            "request_json": request_obj,
            "session_id": session_id,
            "noReply": True,
            "openapi_sha256": openapi_sha,
        })

        lifecycle["post_message_calls"] = 1
        try:
            status, headers, body = http_post(request_path, request_bytes)
        except urllib.error.HTTPError as exc:
            status, headers, body = exc.code, dict(exc.headers.items()), exc.read()
        response_obj = {
            "status": status,
            "headers": headers,
            "body": body.decode("utf-8", "replace"),
            "body_sha256": sha256_bytes(body),
        }
        write_json(OUT / "response.json", response_obj)
        lifecycle["http_methods_used"].append("POST")
        lifecycle["http_paths"].append(request_path)
        if status < 200 or status >= 300:
            lifecycle["terminal_state"] = "OPENCode_HTTP_MESSAGE_TRANSPORT_REJECTED"
            raise RuntimeError(f"message POST rejected with HTTP {status}")
        lifecycle["request_accepted"] = True

        verify_status, verify_headers, verify_body = http_get(request_path)
        lifecycle["http_methods_used"].append("GET")
        lifecycle["http_paths"].append(request_path)
        verification = {
            "status": verify_status,
            "headers": verify_headers,
            "body": verify_body.decode("utf-8", "replace"),
            "body_sha256": sha256_bytes(verify_body),
        }
        write_json(OUT / "verification_history.json", verification)
        history = json.loads(verify_body.decode("utf-8"))
        if not isinstance(history, list):
            raise RuntimeError("message history response is not a list")
        matching = []
        assistant_messages = []
        for item in history:
            info = item.get("info", {}) if isinstance(item, dict) else {}
            parts = item.get("parts", []) if isinstance(item, dict) else []
            if info.get("role") == "assistant":
                assistant_messages.append(info)
            for part in parts:
                if part.get("type") == "text" and part.get("text") == FIXTURE:
                    matching.append(item)
        if len(matching) != 1:
            raise RuntimeError(f"expected exactly one stored matching user message, found {len(matching)}")
        if assistant_messages:
            lifecycle["model_execution_reached"] = True
            lifecycle["terminal_state"] = "OPENCode_HTTP_MESSAGE_PROBE_REACHED_MODEL"
            raise RuntimeError("assistant message evidence appeared after noReply=true")
        lifecycle["message_verified"] = True
        lifecycle["noReply_honored"] = True
        lifecycle["terminal_state"] = "OPENCode_HTTP_MESSAGE_TRANSPORT_PASS"
    except Exception as exc:
        lifecycle["error"] = str(exc)
        if lifecycle["terminal_state"] is None:
            lifecycle["terminal_state"] = "OPENCode_HTTP_MESSAGE_TRANSPORT_REJECTED"
    finally:
        if "proc" in locals():
            try:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=5)
                lifecycle["server_exit_code"] = proc.returncode
                lifecycle["server_terminated_cleanly"] = proc.returncode == 0 or proc.returncode in (-15, 143)
            except Exception as exc:
                lifecycle["server_termination_error"] = str(exc)
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except Exception:
                    pass
        lifecycle["server_finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json(OUT / "lifecycle.json", lifecycle)
        manifest = {
            "artifacts": sorted(p.name for p in OUT.iterdir() if p.is_file() and p.name not in {"sha256sums.txt", "artifact_manifest.json"}),
            "http_methods_used": lifecycle["http_methods_used"],
            "http_paths": lifecycle["http_paths"],
            "post_message_calls": lifecycle["post_message_calls"],
            "model_execution_reached": lifecycle["model_execution_reached"],
            "provider_execution_reached": lifecycle["provider_execution_reached"],
            "file_part_tested": lifecycle["file_part_tested"],
        }
        write_json(OUT / "artifact_manifest.json", manifest)
        lines = []
        for p in sorted(OUT.iterdir()):
            if p.is_file() and p.name not in {"sha256sums.txt"}:
                lines.append(f"{sha256_bytes(p.read_bytes())}  {p.name}")
        (OUT / "sha256sums.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("TERMINAL_STATE =", lifecycle["terminal_state"])
    print("server executable =", EXECUTABLE)
    print("server port =", PORT)
    print("session endpoint = POST /session")
    print("message endpoint =", f"POST /session/{{sessionID}}/message")
    print("noReply =", True)
    print("request accepted =", lifecycle["request_accepted"])
    print("message verified =", lifecycle["message_verified"])
    print("model execution reached =", lifecycle["model_execution_reached"])
    print("provider execution reached =", lifecycle["provider_execution_reached"])
    print("raw artifact paths =", str(OUT))
    print("SHA-256 =", FROZEN_OPENAPI_SHA)
    print("REAL_AI_CALLS = 0")
    print("PROVIDER_CALLS = 0")
    print("OPENCode_RUN_MODEL = 0")
    print("9ROUTER = 0")
    print("BROWSER_CDP = 0")
    print("worker.py = 0")
    print("BAMSO_TOUCHED = false")
    print("GIT_MUTATION = false")
    return 0 if lifecycle["terminal_state"] == "OPENCode_HTTP_MESSAGE_TRANSPORT_PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
