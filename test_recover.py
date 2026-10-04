import sys
sys.path.insert(0, r"D:\ai-orchestrator")
from worker import _extract_failed_generation, _recover_tool_call
from pydantic import BaseModel


class FakeOut(BaseModel):
    memory: str | None = None
    action: list[dict]


e1 = Exception(
    """Error code: 400 - {'error': {'message': 'Tool choice is none, but model called a tool', 'type': 'invalid_request_error', 'code': 'tool_use_failed', 'failed_generation': '{"name": "browser.action", "arguments": {"input":{"index":1231,"text":"hello","clear":true}}}'}}"""
)
e2 = Exception(
    'litellm.BadRequestError: GroqException - {"error":{"message":"Tool choice is none, but model called a tool","type":"invalid_request_error","code":"tool_use_failed","failed_generation":"{\\"name\\": \\"click\\", \\"arguments\\": {\\"index\\":1238}}"}}'
)
e3 = Exception("'failed_generation': '{\"name\": \"browser.send_keys\", \"arguments\": {\"keys\":\"Enter\"}}'")
e4 = Exception("some other error without marker")

for tag, e in [("groq-sdk", e1), ("litellm", e2), ("send_keys", e3)]:
    fg = _extract_failed_generation(str(e))
    print(tag, "extracted:", repr(fg)[:140])
    rec = _recover_tool_call(e, FakeOut)
    print(tag, "recovered:", rec.completion if rec else None)

print("negative:", _recover_tool_call(e4, FakeOut))
