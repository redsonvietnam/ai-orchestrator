const body = document.body.innerText || "";
const qa = (s) => Array.from(document.querySelectorAll(s));
return {
  bodyChars: body.length,
  hasCanary: body.includes("T0-CANARY-OK-8f3a2c"),
  hasApproveInBody: body.includes("APPROVE patch"),
  composerAll: qa('div[contenteditable="true"]').map((e) => ({
    dataId: e.getAttribute("data-id"), aria: e.getAttribute("aria-label"),
    text: (e.innerText || "").slice(0, 80),
  })),
  turns: qa('[data-testid^="conversation-turn"], article, [data-testid="assistant-turn"], [data-testid="user-turn"]').length,
  h2s: qa("h2, h1").map((e) => (e.innerText || "").slice(0, 60)).slice(0, 5),
  streamingEls: qa("*").filter((e) => (e.className || "").toString().includes("result-streaming")).length,
  promptTextarea: qa("textarea").map((e) => (e.value || "").slice(0, 60)),
};
