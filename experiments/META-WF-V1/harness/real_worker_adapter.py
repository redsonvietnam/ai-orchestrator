#!/usr/bin/env python3
"""Deterministic, provider-neutral real-worker contract adapter.

Default mode is dry-run and never imports or invokes worker.py/providers/browser.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request as HTTPRequest, urlopen
from pathlib import Path

VALID_STATUS = "ok"
DRY_RUN = "dry_run"
OPENCODE_HTTP = "opencode_http"


class ContractError(RuntimeError):
    pass


class OpenCodeHTTPTransport:
    """Minimal OpenCode HTTP transport; the model-triggering POST is never retried."""

    def __init__(self, executable=None, host="127.0.0.1", port=4099, timeout=10.0):
        self.executable = executable or shutil.which("opencode")
        self.host = host
        self.port = port
        self.timeout = timeout
        self.process = None
        self.base_url = "http://" + host + ":" + str(port)
        self.message_posts = 0

    def _request(self, method, path, body=None):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = HTTPRequest(
            self.base_url + path, data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method=method,
        )
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def start(self):
        if self.process is not None:
            raise ContractError("OpenCode server already started")
        if not self.executable:
            raise ContractError("OpenCode executable not found")
        self.process = subprocess.Popen(
            [self.executable, "serve", "--hostname", self.host, "--port", str(self.port)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
        )
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise ContractError("OpenCode server exited: " + str(self.process.returncode))
            try:
                health = self._request("GET", "/global/health")
                if health.get("healthy") is True or health.get("status") in {"ok", "healthy"}:
                    return
            except (HTTPError, URLError, OSError, ValueError):
                time.sleep(0.05)
        raise ContractError("OpenCode health check timed out")

    def stop(self):
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=self.timeout)
        self.process = None

    def execute(self, prompt, provider, model, agent):
        if self.process is None:
            raise ContractError("OpenCode server is not started")
        session = self._request("POST", "/session", {})
        session_id = session.get("id") or session.get("sessionID")
        if not session_id:
            raise ContractError("session ID missing")
        body = {
            "model": {"providerID": provider, "modelID": model},
            "agent": agent,
            "parts": [{"type": "text", "text": prompt}],
        }
        response = self._request("POST", "/session/" + session_id + "/message", body)
        self.message_posts += 1
        if not isinstance(response, dict):
            raise ContractError("OpenCode response must be a JSON object")
        parts = response.get("parts")
        if not isinstance(parts, list):
            raise ContractError("OpenCode response parts must be a list")
        text_parts = [
            part.get("text")
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)
        ]
        if not text_parts:
            raise ContractError("OpenCode response contained no valid text part")
        return "\n".join(text_parts), response


def extract_response_text(value):
    texts = []
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            texts.append(value["text"])
        for key in ("parts", "content", "message", "data"):
            if key in value:
                texts.extend(extract_response_text(value[key]))
    elif isinstance(value, list):
        for item in value:
            texts.extend(extract_response_text(item))
    return "\n".join(texts)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Request:
    task_id: str
    prompt_file: str
    input_sha256: str
    worker: str
    provider: str
    model: str
    out: str


@dataclass(frozen=True)
class Contract:
    task_id: str
    worker: str
    provider: str
    model: str
    status: str
    started_at: str
    finished_at: str
    response_artifact: str
    response_sha256: str
    input_sha256: str
    execution_mode: str


def load_request(args: argparse.Namespace) -> Request:
    if not args.task_id or not args.worker or not args.provider or not args.model:
        raise ContractError("worker/provider identity incomplete")
    source = Path(args.prompt_file).resolve()
    if not source.is_file():
        raise ContractError(f"input artifact missing: {source}")
    actual = sha256(source)
    if actual != args.input_sha256:
        raise ContractError(f"input SHA mismatch: expected {args.input_sha256}, actual {actual}")
    return Request(
        args.task_id, str(source), args.input_sha256,
        args.worker, args.provider, args.model, str(Path(args.out).resolve())
    )


def synthetic_response(req: Request) -> bytes:
    return (
        "META-WF V1 SYNTHETIC WORKER RESPONSE\n"
        "execution_mode=dry_run\n"
        "NO_REAL_AI_EXECUTION\n"
        f"task_id={req.task_id}\n"
        f"input_sha256={req.input_sha256}\n"
    ).encode("utf-8")


def validate(meta: dict, req: Request) -> Contract:
    required = {
        "task_id", "worker", "provider", "model", "status", "started_at",
        "finished_at", "response_artifact", "response_sha256",
        "input_sha256", "execution_mode",
    }
    missing = sorted(required - meta.keys())
    if missing:
        raise ContractError(f"metadata missing: {missing}")
    if meta["task_id"] != req.task_id or meta["worker"] != req.worker:
        raise ContractError("task/worker mismatch")
    if meta["provider"] != req.provider or meta["model"] != req.model:
        raise ContractError("provider/model mismatch")
    if meta["input_sha256"] != req.input_sha256:
        raise ContractError("metadata input SHA mismatch")
    if meta["status"] != VALID_STATUS:
        raise ContractError(f"invalid status: {meta['status']}")
    if meta["execution_mode"] == DRY_RUN:
        if meta.get("real_execution", False) is True:
            raise ContractError("dry-run masquerades as real execution")
    elif meta["execution_mode"] == OPENCODE_HTTP:
        if meta.get("real_execution", False) is not True:
            raise ContractError("OpenCode HTTP execution missing real_execution=true")
    else:
        raise ContractError(f"unsupported execution_mode: {meta['execution_mode']}")
    response = Path(meta["response_artifact"]).resolve()
    if not response.is_file():
        raise ContractError(f"output artifact missing: {response}")
    actual = sha256(response)
    if actual != meta["response_sha256"]:
        raise ContractError(f"output SHA mismatch: expected {meta['response_sha256']}, actual {actual}")
    return Contract(**{key: meta[key] for key in required})


def run(args: argparse.Namespace) -> Contract:
    req = load_request(args)
    out = Path(req.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    response = synthetic_response(req)
    real_execution = False
    if args.execution_mode == OPENCODE_HTTP:
        transport = OpenCodeHTTPTransport(port=args.port, timeout=args.timeout)
        try:
            transport.start()
            prompt = Path(req.prompt_file).read_text(encoding="utf-8")
            text, _raw_response = transport.execute(prompt, req.provider, req.model, args.agent)
            if not text:
                raise ContractError("OpenCode response contained no text")
            response = text.encode("utf-8")
            real_execution = True
        finally:
            transport.stop()
    elif args.execution_mode != DRY_RUN:
        raise ContractError(f"unsupported execution_mode: {args.execution_mode}")
    out.write_bytes(response)
    meta = {
        **asdict(req),
        "status": VALID_STATUS,
        "started_at": timestamp(args.started_at),
        "finished_at": timestamp(args.finished_at),
        "response_artifact": str(out),
        "response_sha256": sha256(out),
        "input_sha256": req.input_sha256,
        "execution_mode": args.execution_mode,
        "real_execution": real_execution,
    }
    metadata_path = out.with_suffix(".metadata.json")
    metadata_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    contract = validate(meta, req)

    hook = {
        "schema": "META-WF-V1/REAL_WORKER_ADAPTER_V1",
        "state_sequence": [
            "REAL_WORKER_READY",
            "REAL_WORKER_SUBMITTED",
            "REAL_WORKER_ARTIFACT_VALIDATED",
        ],
        "submitted": True,
        "validated": True,
        "contract": asdict(contract),
    }
    hook_path = out.parent / "transition.json"
    hook_path.write_text(json.dumps(hook, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return contract


def self_test() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        source = root / "input.txt"
        source.write_text("META-WF V1 self-test input\\n", encoding="utf-8")
        req = Request(
            "SELFTEST", str(source), sha256(source),
            "real-worker-adapter", "synthetic-provider", "synthetic-model",
            str(root / "response.txt"),
        )
        args = argparse.Namespace(
            task_id=req.task_id, prompt_file=req.prompt_file,
            input_sha256=req.input_sha256, worker=req.worker,
            provider=req.provider, model=req.model, out=req.out,
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:01Z",
            execution_mode=DRY_RUN, port=4099, timeout=1.0, agent="explore",
        )
        contract = run(args)
        assert contract.execution_mode == DRY_RUN
        assert contract.status == VALID_STATUS

        original = Path(req.out).read_bytes()
        Path(req.out).write_bytes(original + b"TAMPER")
        bad = asdict(contract)
        try:
            validate(bad, req)
        except ContractError as exc:
            assert "output SHA mismatch" in str(exc)
        else:
            raise AssertionError("tamper gate did not fail")

        Path(req.out).write_bytes(original)
        missing = dict(bad)
        missing["response_artifact"] = str(root / "missing.txt")
        try:
            validate(missing, req)
        except ContractError as exc:
            assert "output artifact missing" in str(exc)
        else:
            raise AssertionError("missing-artifact gate did not fail")

        invalid = dict(bad)
        invalid["status"] = "INVALID"
        try:
            validate(invalid, req)
        except ContractError as exc:
            assert "invalid status" in str(exc)
        else:
            raise AssertionError("invalid-status gate did not fail")

        dry_real = dict(bad)
        dry_real["real_execution"] = True
        try:
            validate(dry_real, req)
        except ContractError as exc:
            assert "masquerades as real execution" in str(exc)
        else:
            raise AssertionError("dry-run masquerade gate did not fail")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id")
    ap.add_argument("--prompt-file")
    ap.add_argument("--input-sha256")
    ap.add_argument("--worker")
    ap.add_argument("--provider")
    ap.add_argument("--model")
    ap.add_argument("--out")
    ap.add_argument("--started-at", default="2026-01-01T00:00:00Z")
    ap.add_argument("--finished-at", default="2026-01-01T00:00:01Z")
    ap.add_argument("--execution-mode", choices=[DRY_RUN, OPENCODE_HTTP], default=DRY_RUN)
    ap.add_argument("--port", type=int, default=4099)
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--agent", default="explore")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    try:
        if args.self_test:
            self_test()
            print(json.dumps({
                "status": "REAL_WORKER_ADAPTER_TEST_PASS",
                "tests": [
                    "adapter_dry_run", "hash_tamper_detection",
                    "missing_artifact_gate", "invalid_status_gate",
                    "dry_run_masquerade_gate",
                ],
                "external_ai_calls": 0,
                "worker_py_called": False,
            }, sort_keys=True))
            return 0
        required = ["task_id", "prompt_file", "input_sha256", "worker", "provider", "model", "out"]
        missing = [name for name in required if not getattr(args, name)]
        if missing:
            raise ContractError(f"missing CLI arguments: {missing}")
        contract = run(args)
        print(json.dumps({"status": "WORKER_SUBMITTED", "validated": True, "contract": asdict(contract)}, sort_keys=True))
        return 0
    except (ContractError, OSError, ValueError, AssertionError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
