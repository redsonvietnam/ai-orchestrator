import argparse
import asyncio
import json
import os
import re
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from browser_use import Agent, BrowserSession
from browser_use.llm.exceptions import ModelProviderError, ModelRateLimitError
from browser_use.llm.google import ChatGoogle
from browser_use.llm.groq.chat import ChatGroq
from browser_use.llm.litellm import ChatLiteLLM
from browser_use.llm.views import ChatInvokeCompletion

# Groq free-tier rolling 60s windows (measured): (budget_tokens, budget_counts_output)
GROQ_BUDGETS = {
    "groq/qwen/qwen3.8-27b": (7000, False),
    "groq/openai/gpt-oss-120b": (8000, True),
    "groq/openai/gpt-oss-20b": (8000, True),
}
_windows: dict[str, list[tuple[float, int]]] = {}


def _estimate_tokens(messages) -> int:
    chars = 0
    for m in messages:
        c = getattr(m, "content", None)
        if isinstance(c, str):
            chars += len(c)
        elif isinstance(c, list):
            for part in c:
                t = getattr(part, "text", None)
                if isinstance(t, str):
                    chars += len(t)
    return int(chars / 3.4) + 700


def _extract_failed_generation(s: str) -> str | None:
    """Pull the failed_generation payload out of a Groq 400 error string.

    Handles both JSON-escaped bodies (litellm) and Python-repr bodies (groq SDK).
    """
    i = s.find("failed_generation")
    if i < 0:
        return None
    j = s.find(":", i)
    if j < 0:
        return None
    k = j + 1
    while k < len(s) and s[k] in " \t":
        k += 1
    if k >= len(s) or s[k] not in "\"'":
        return None
    q = s[k]
    k += 1
    buf: list[str] = []
    while k < len(s):
        c = s[k]
        if c == "\\" and k + 1 < len(s):
            nxt = s[k + 1]
            if nxt in ('"', "'", "\\"):
                buf.append(nxt)
            else:
                # keep JSON escapes (\n etc.) intact for json.loads
                buf.append("\\")
                buf.append(nxt)
            k += 2
            continue
        if c == q:
            return "".join(buf)
        buf.append(c)
        k += 1
    return None


def _recover_tool_call(e: Exception, output_format):
    """Rebuild AgentOutput from a tool-call-shaped failed_generation.

    gpt-oss models intermittently emit {"name": <action>, "arguments": {...}}
    instead of the schema JSON; Groq rejects it with tool_use_failed, but the
    payload still carries the intended action.
    """
    if output_format is None or "tool_use_failed" not in str(e):
        return None
    fg = _extract_failed_generation(str(e))
    if not fg:
        return None
    try:
        env = json.loads(fg)
    except Exception:
        return None
    if not isinstance(env, dict) or "name" not in env:
        return None
    name = str(env.get("name") or "")
    args = env.get("arguments")
    if not isinstance(args, dict):
        args = {}
    if name == "browser.action":
        action = args
    else:
        action = {name.split(".")[-1]: args}
    for candidate in (
        {"memory": "Recovered action from malformed tool-call output.", "action": [action]},
        {"action": [action]},
    ):
        try:
            parsed = output_format.model_validate(candidate)
        except Exception:
            continue
        print(f"[recover] tool_use_failed -> action {list(action.keys())}", flush=True)
        return ChatInvokeCompletion(completion=parsed, usage=None, thinking=None, stop_reason=None)
    return None


class PacedMixin:
	"""Rolling-window rate pacing + 61s-backoff retries, shared by chat clients.

	Concrete dataclass subclasses must declare: budget_per_min, count_output, max_rate_retries.
	"""

	def _record(self, tokens: int) -> None:
		_windows.setdefault(self.model, []).append((time.monotonic(), tokens))

	def _window_wait(self, est: int) -> float:
		est = min(est, self.budget_per_min - 500)
		now = time.monotonic()
		log = [e for e in _windows.get(self.model, []) if now - e[0] < 60]
		_windows[self.model] = log
		used = sum(e[1] for e in log)
		if used + est <= self.budget_per_min:
			return 0.0
		return 60 - (now - log[0][0]) + 0.5

	async def _acquire(self, est: int) -> None:
		while True:
			wait = self._window_wait(est)
			if wait <= 0:
				return
			print(
				f"[pace] {self.model}: over budget, sleep {wait:.1f}s",
				flush=True,
			)
			await asyncio.sleep(max(1.0, min(wait, 30)))

	async def ainvoke(self, messages, output_format=None, **kwargs):
		est = _estimate_tokens(messages)
		for attempt in range(self.max_rate_retries):
			await self._acquire(est)
			try:
				resp = await super().ainvoke(messages, output_format=output_format, **kwargs)
			except ModelRateLimitError as e:
				# Rejected requests may still count toward the window: always
				# wait a full 60s+ window drain, never short escalating backoff.
				m = re.search(r"try again in ([\d.]+)s", str(e))
				wait = max(float(m.group(1)) if m else 0.0, 61.0)
				print(
					f"[pace] 429 {self.model}: sleep {wait:.1f}s (try {attempt+1}/{self.max_rate_retries})",
					flush=True,
				)
				await asyncio.sleep(wait)
				continue
			except ModelProviderError as e:
				recovered = _recover_tool_call(e, output_format)
				if recovered is not None:
					return recovered
				raise
			if resp.usage:
				tok = resp.usage.prompt_tokens + (
					resp.usage.completion_tokens if self.count_output else 0
				)
				self._record(tok)
			return resp
		raise ModelRateLimitError(
			message=f"rate limited after {self.max_rate_retries} retries", model=self.name
		)


@dataclass
class PacedChatLiteLLM(PacedMixin, ChatLiteLLM):
	budget_per_min: int = 7000
	count_output: bool = False
	max_rate_retries: int = 4


@dataclass
class PacedChatGroq(PacedMixin, ChatGroq):
	budget_per_min: int = 8000
	count_output: bool = True
	max_rate_retries: int = 4


class RotatingLLM:
    """Round-robin across models with separate rate-limit windows (e.g. Groq free tier)."""

    def __init__(self, llms):
        self.llms = llms
        self._i = 0

    @property
    def model(self) -> str:
        return self.llms[0].model

    @property
    def provider(self) -> str:
        return self.llms[0].provider

    @property
    def name(self) -> str:
        return self.llms[0].name

    def __getattr__(self, k):
        return getattr(self.llms[0], k)

    async def ainvoke(self, messages, output_format=None, **kwargs):
        est = _estimate_tokens(messages)
        order = [self.llms[(self._i + k) % len(self.llms)] for k in range(len(self.llms))]
        self._i = (self._i + 1) % len(self.llms)
        pick = next((l for l in order if l._window_wait(est) <= 2), order[0])
        return await pick.ainvoke(messages, output_format=output_format, **kwargs)


def make_llm(model):
    if model.startswith(("gemini", "gemma")):
        return ChatGoogle(model=model)
    models = [m.strip() for m in model.split(",") if m.strip()]
    llms = []
    for m in models:
        budget, count_output = GROQ_BUDGETS.get(m, (8000, True))
        if m.startswith("groq/"):
            llms.append(
                PacedChatGroq(
                    model=m[len("groq/"):],
                    budget_per_min=budget,
                    count_output=count_output,
                    max_retries=3,
                )
            )
        else:
            llms.append(
                PacedChatLiteLLM(model=m, budget_per_min=budget, count_output=count_output, max_retries=0)
            )
    return llms[0] if len(llms) == 1 else RotatingLLM(llms)


async def main():
    import subprocess as _sp
    import traceback as _tb

    _orig_popen = _sp.Popen

    def _traced_popen(*a, **k):
        args = a[0] if a else k.get("args")
        print(f">> Popen pid={os.getpid()} args={args}", flush=True)
        _tb.print_stack()
        return _orig_popen(*a, **k)

    _sp.Popen = _traced_popen
    print(f"worker start pid={os.getpid()}", flush=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--prompt-file", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=os.environ.get("BU_MODEL", "groq/openai/gpt-oss-120b,groq/openai/gpt-oss-20b"))
    ap.add_argument("--max-steps", type=int, default=80)
    args = ap.parse_args()

    prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    llm = make_llm(args.model)
    session = BrowserSession(cdp_url=f"http://127.0.0.1:{args.port}")
    task = (
        f"Navigate to {args.url}. Wait for the chat UI to fully load. "
        "Type the task below into the chat message box and submit it (press Enter). "
        "Wait until the AI response is fully complete. If the response is long, scroll down to read all of it. "
        "Then extract the ENTIRE assistant response text verbatim. "
        "Finish by calling the done action with the full extracted response text as the final result.\n\n"
        f"=== TASK TO SUBMIT ===\n{prompt}"
    )
    agent = Agent(
        task=task,
        llm=llm,
        browser_session=session,
        use_judge=False,
        enable_planning=False,
        use_vision=False,
        flash_mode=True,
        llm_timeout=420,
        step_timeout=540,
        max_failures=8,
        save_conversation_path=str(Path(args.out).with_suffix(".conv.json")),
    )
    try:
        history = await agent.run(max_steps=args.max_steps)
        result = history.final_result() or ""
    except Exception:
        traceback.print_exc()
        result = ""
    if not result:
        print(f"[{args.name}] WARNING: empty result, check conversation log", flush=True)
    Path(args.out).write_text(result, encoding="utf-8")
    print(f"[{args.name}] done, {len(result)} chars")


if __name__ == "__main__":
    asyncio.run(main())
