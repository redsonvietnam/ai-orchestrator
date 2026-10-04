import asyncio, os, json
import litellm

os.environ.setdefault("GROQ_API_KEY", os.environ["GROQ_API_KEY"])

SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "AgentOutput",
        "schema": {
            "type": "object",
            "properties": {
                "thoughts": {"type": "string"},
                "action": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            },
            "required": ["thoughts", "action"],
        },
    },
}

async def test(model):
    for attempt in range(2):
        try:
            r = await litellm.acompletion(
                model=model,
                messages=[{"role": "user", "content": "Return thoughts='ok' and one action that does nothing."}],
                response_format=SCHEMA,
                temperature=0.0,
                max_tokens=300,
            )
            print(f"{model} OK: {r.choices[0].message.content[:200]}")
            return
        except Exception as e:
            print(f"{model} FAIL try{attempt}: {type(e).__name__}: {str(e)[:300]}")
            await asyncio.sleep(1)

async def main():
    for m in ["groq/openai/gpt-oss-120b", "groq/openai/gpt-oss-20b", "groq/qwen/qwen3.8-27b"]:
        await test(m)

asyncio.run(main())
