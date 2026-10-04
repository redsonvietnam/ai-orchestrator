import asyncio
import os

from browser_use import Agent, BrowserSession
from browser_use.llm.google import ChatGoogle


async def main():
    llm = ChatGoogle(model=os.environ.get("BU_MODEL", "gemini-2.5-flash"))
    session = BrowserSession(cdp_url="http://127.0.0.1:9222")
    agent = Agent(
        task=(
            "Navigate to https://example.com. Wait for the page to load. "
            "Extract the page title and the first paragraph of the page. "
            "Finish by calling the done action with exactly this format: "
            "TITLE=<title> | FIRST_PARA=<first paragraph>"
        ),
        llm=llm,
        browser_session=session,
    )
    history = await agent.run(max_steps=15)
    print("AGENT_RESULT:", history.final_result())


asyncio.run(main())
