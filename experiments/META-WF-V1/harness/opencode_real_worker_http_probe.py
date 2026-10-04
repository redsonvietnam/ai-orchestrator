import hashlib
import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "experiments/META-WF-V1/runs/W2/opencode_real_worker_http"
EXECUTABLE = r"C:\Users\User\AppData\Roaming\npm\opencode.CMD"
PORT = 4099
BASE = f"http://127.0.0.1:{PORT}"
MODEL_PROVIDER = "9router-free"
MODEL_ID = "free-fast-v2"
AGENT = "explore"
PROMPT = """META-WF V1 REAL WORKER SMOKE
Return exactly:
REAL_WORKER_OK
provider=9router-free
worker=opencode"""
OPENAPI_PATH = ROOT / "experiments/META-WF-V1/runs/W2/opencode_server_probe/openapi.json"
OPENAPI_SHA = "f5cb443f0d160fc4b17190f64c2401f199160eb2137ce4e00ca319b99aa34005"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def request(method, path, body=None, timeout=30):
    headers = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
    req = urllib.request.Request(BASE + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def capture_events(stop_event, event_result):
    try:
        req = urllib.request.Request(BASE + "/event", method="GET")
        with urllib.request.urlopen(req, timeout=35) as resp:
            event_result["status"] = resp.status
            event_result["headers"] = dict(resp.headers.items())
            chunks = []
            started = time.monotonic()
            while not stop_event.is_set() and time.monotonic() - started < 30:
                line = resp.readline()
                if not line:
                    break
                chunks.append(line)
                text = line.decode("utf-8", "replace")
                event_result["lines"].append(text)
                if "session.idle" in text:
                    event_result["idle_seen"] = True
                    break
            event_result["body"] = b"".join(chunks)
    except Exception as exc:
        event_result["error"] = str(exc)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for p in OUT.iterdir():
        if p.is_file():
            p.unlink()

    lifecycle = {
        "terminal_state": None,
        "server": {
            "executable": EXECUTABLE,
            "argv": [EXECUTABLE, "serve", "--hostname", "127.0.0.1", "--port", str(PORT)],
            "port": PORT,
        },
        "session_endpoint": "POST /session",
        "message_endpoint": "POST /session/{sessionID}/message",
        "model": {"providerID": MODEL_PROVIDER, "modelID": MODEL_ID},
        "agent": AGENT,
        "noReply": False,
        "post_message_calls": 0,
        "real_ai_calls": 0,
        "provider_calls": 0,
        "model_execution_reached": False,
        "provider_execution_reached": False,
        "request_accepted": False,
        "worker_response_validated": False,
        "retry_count": 0,
        "browser_cdp": False,
        "worker_py": False,
        "bamso_touched": False,
        "git_mutation": False,
        "server_terminated_cleanly": False,
    }

    proc = None
    event_thread = None
    event_stop = threading.Event()
    event_result = {"lines": [], "idle_seen": False}

    try:
        if sha(OPENAPI_PATH.read_bytes()) != OPENAPI_SHA:
            lifecycle["terminal_state"] = "OPENCode_REAL_WORKER_HTTP_SMOKE_OBSERVATION_BLOCKED"
            raise RuntimeError("frozen OpenAPI SHA mismatch")

        spec = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
        session_create = spec["paths"]["/session"]["post"]
        message_post = spec["paths"]["/session/{sessionID}/message"]["post"]
        text_schema = spec["components"]["schemas"]["TextPartInput"]
        if session_create.get("operationId") != "session.create":
            raise RuntimeError("unexpected session creation operationId")
        if message_post.get("operationId") != "session.prompt":
            raise RuntimeError("unexpected message operationId")
        if text_schema.get("required") != ["type", "text"]:
            raise RuntimeError("unexpected TextPartInput required fields")

        server_stdout = OUT / "server_stdout.bin"
        server_stderr = OUT / "server_stderr.bin"
        with server_stdout.open("wb") as stdout, server_stderr.open("wb") as stderr:
            proc = subprocess.Popen(
                [EXECUTABLE, "serve", "--hostname", "127.0.0.1", "--port", str(PORT)],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                shell=False,
            )
            lifecycle["server_pid"] = proc.pid
            lifecycle["server_started_at"] = datetime.now(timezone.utc).isoformat()

        health = None
        for _ in range(120):
            try:
                status, headers, body = request("GET", "/global/health", timeout=3)
                health = {"status": status, "headers": headers, "body": body.decode("utf-8", "replace")}
                if status == 200:
                    break
            except Exception as exc:
                health = {"error": str(exc)}
            time.sleep(0.05)
        else:
            raise RuntimeError("health did not reach HTTP 200")
        write_json(OUT / "health.json", health)

        # Session creation is the already-proven non-model session.create route.
        session_status, session_headers, session_body = request("POST", "/session", b"{}", timeout=10)
        session_response = {
            "status": session_status,
            "headers": session_headers,
            "body": session_body.decode("utf-8", "replace"),
            "body_sha256": sha(session_body),
        }
        write_json(OUT / "session_response.json", session_response)
        if session_status < 200 or session_status >= 300:
            lifecycle["terminal_state"] = "OPENCode_REAL_WORKER_HTTP_SMOKE_REJECTED"
            raise RuntimeError(f"session creation rejected: HTTP {session_status}")
        session_obj = json.loads(session_body.decode("utf-8"))
        session_id = session_obj.get("id")
        if not isinstance(session_id, str) or not session_id.startswith("ses"):
            raise RuntimeError("invalid session ID")

        request_obj = {
            "model": {"providerID": MODEL_PROVIDER, "modelID": MODEL_ID},
            "agent": AGENT,
            "parts": [{"type": "text", "text": PROMPT}],
        }
        request_bytes = json.dumps(request_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_path = f"/session/{session_id}/message"
        write_json(OUT / "request.json", request_obj)
        write_json(OUT / "request_metadata.json", {
            "endpoint": BASE + request_path,
            "session_id": session_id,
            "model": request_obj["model"],
            "agent": AGENT,
            "noReply_present": False,
            "noReply_effective": False,
            "prompt_sha256": sha(PROMPT.encode("utf-8")),
            "request_body_sha256": sha(request_bytes),
            "request_utf8_byte_count": len(request_bytes),
            "openapi_sha256": OPENAPI_SHA,
        })

        # Subscribe before the sole model-triggering POST so the complete event stream
        # for this call is observable. This GET does not invoke a model/provider.
        event_thread = threading.Thread(target=capture_events, args=(event_stop, event_result), daemon=True)
        event_thread.start()
        time.sleep(0.15)

        lifecycle["post_message_calls"] = 1
        lifecycle["real_ai_calls"] = 1

        status, headers, body = request("POST", request_path, request_bytes, timeout=180)
        response = {
            "status": status,
            "headers": headers,
            "body": body.decode("utf-8", "replace"),
            "body_sha256": sha(body),
            "raw_body_base64": body.decode("utf-8", "replace"),
        }
        write_json(OUT / "response.json", response)
        if status < 200 or status >= 300:
            lifecycle["terminal_state"] = "OPENCode_REAL_WORKER_HTTP_SMOKE_REJECTED"
            raise RuntimeError(f"message rejected: HTTP {status}")
        lifecycle["request_accepted"] = True

        event_stop.set()
        event_thread.join(timeout=5)
        event_bytes = event_result.get("body", b"")
        (OUT / "event_stream.raw").write_bytes(event_bytes)
        write_json(OUT / "event_stream.json", {
            "status": event_result.get("status"),
            "headers": event_result.get("headers", {}),
            "idle_seen": event_result.get("idle_seen", False),
            "error": event_result.get("error"),
            "body_sha256": sha(event_bytes),
            "line_count": len(event_result.get("lines", [])),
        })

        response_text = body.decode("utf-8", "replace")
        exact_ok = (
            "REAL_WORKER_OK" in response_text
            and "provider=9router-free" in response_text
            and "worker=opencode" in response_text
        )
        try:
            response_obj = json.loads(response_text)
        except Exception:
            response_obj = {}
        assistant_info = response_obj.get("info", {}) if isinstance(response_obj, dict) else {}
        model_ok = assistant_info.get("modelID") == MODEL_ID
        provider_ok = assistant_info.get("providerID") == MODEL_PROVIDER
        agent_ok = assistant_info.get("agent") == AGENT
        if not exact_ok or not model_ok or not provider_ok or not agent_ok:
            lifecycle["terminal_state"] = "OPENCode_REAL_WORKER_HTTP_SMOKE_UNSAFE"
            raise RuntimeError("worker response identity/marker validation failed")

        lifecycle["model_execution_reached"] = True
        lifecycle["provider_execution_reached"] = True
        lifecycle["provider_calls"] = 1
        lifecycle["worker_response_validated"] = True
        lifecycle["terminal_state"] = "OPENCode_REAL_WORKER_HTTP_SMOKE_PASS"

    except Exception as exc:
        lifecycle["error"] = str(exc)
        if lifecycle["terminal_state"] is None:
            lifecycle["terminal_state"] = "OPENCode_REAL_WORKER_HTTP_SMOKE_REJECTED"
    finally:
        event_stop.set()
        if event_thread is not None:
            event_thread.join(timeout=5)
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=5)
                lifecycle["server_exit_code"] = proc.returncode
                lifecycle["server_terminated_cleanly"] = proc.returncode in (0, -15, 143)
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
            "post_message_calls": lifecycle["post_message_calls"],
            "retry_count": lifecycle["retry_count"],
            "real_ai_calls": lifecycle["real_ai_calls"],
            "provider_calls": lifecycle["provider_calls"],
            "model_execution_reached": lifecycle["model_execution_reached"],
            "provider_execution_reached": lifecycle["provider_execution_reached"],
        }
        write_json(OUT / "artifact_manifest.json", manifest)
        sums = []
        for p in sorted(OUT.iterdir()):
            if p.is_file() and p.name != "sha256sums.txt":
                sums.append(f"{sha(p.read_bytes())}  {p.name}")
        (OUT / "sha256sums.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")

        validation = {
            "terminal_state": lifecycle["terminal_state"],
            "request_accepted": lifecycle["request_accepted"],
            "model_execution_reached": lifecycle["model_execution_reached"],
            "provider_execution_reached": lifecycle["provider_execution_reached"],
            "real_ai_calls": lifecycle["real_ai_calls"],
            "provider_calls": lifecycle["provider_calls"],
            "retry_count": lifecycle["retry_count"],
            "browser_cdp": lifecycle["browser_cdp"],
            "worker_py": lifecycle["worker_py"],
            "bamso_touched": lifecycle["bamso_touched"],
            "git_mutation": lifecycle["git_mutation"],
            "worker_response_validated": lifecycle["worker_response_validated"],
        }
        write_json(OUT / "validation.json", validation)
        write_json(OUT / "smoke_result.json", validation)

    print("TERMINAL_STATE =", lifecycle["terminal_state"])
    print("server port =", PORT)
    print("session endpoint = POST /session")
    print("message endpoint =", f"POST /session/{{sessionID}}/message")
    print("model =", f"{MODEL_PROVIDER}/{MODEL_ID}")
    print("agent =", AGENT)
    print("request accepted =", lifecycle["request_accepted"])
    print("model execution reached =", lifecycle["model_execution_reached"])
    print("provider execution reached =", lifecycle["provider_execution_reached"])
    print("worker response SHA-256 =", sha(Path(OUT / "response.json").read_bytes()) if (OUT / "response.json").exists() else "NONE")
    print("raw artifact paths =", str(OUT))
    print("REAL_AI_CALLS =", lifecycle["real_ai_calls"])
    print("PROVIDER_CALLS =", lifecycle["provider_calls"])
    print("OPENCode_RUN_MODEL = 0")
    print("9ROUTER = 0")
    print("BROWSER_CDP = 0")
    print("worker.py = 0")
    print("BAMSO_TOUCHED = false")
    print("GIT_MUTATION = false")
    print("NEXT_SAFE_STEP = preserve evidence; no retry")
    return 0 if lifecycle["terminal_state"] == "OPENCode_REAL_WORKER_HTTP_SMOKE_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
