import asyncio, os, json, traceback

if not os.environ.get("GROQ_API_KEY"): raise RuntimeError("GROQ_API_KEY environment variable is required")

import litellm
from browser_use.llm.litellm import ChatLiteLLM
from browser_use.llm.schema import SchemaOptimizer

try:
    from browser_use.agent.views import AgentOutput
except Exception as e:
    print("import AgentOutput failed:", e)
    traceback.print_exc()
    raise

print("supports_response_schema gpt-oss-120b:", litellm.supports_response_schema(model="openai/gpt-oss-120b", custom_llm_provider="groq"))
print("supports_response_schema gpt-oss-20b:", litellm.supports_response_schema(model="openai/gpt-oss-20b", custom_llm_provider="groq"))

schema = SchemaOptimizer.create_optimized_json_schema(AgentOutput)
print("schema keys:", list(schema.keys()))

from browser_use.llm.messages import UserMessage, SystemMessage

async def run(model):
    llm = ChatLiteLLM(model=model, max_retries=0)
    msgs = [
        SystemMessage(content="You are a browser automation agent. Respond ONLY with JSON matching the schema. Example: {\"thoughts\": \"...\", \"action\": [{\"click\": {\"index\": 5}}]}"),
        UserMessage(content="Click element index 1238 on the page. Page elements: [1238] button 'Submit'. " * 50),
    ]
    try:
        r = await llm.ainvoke(msgs, output_format=AgentOutput)
        print(f"{model} OK: {type(r.completion).__name__}")
    except Exception as e:
        print(f"{model} FAIL: {type(e).__name__}: {str(e)[:600]}")

async def main():
    litellm._turn_on_debug()
    await run("groq/openai/gpt-oss-120b")

asyncio.run(main())
