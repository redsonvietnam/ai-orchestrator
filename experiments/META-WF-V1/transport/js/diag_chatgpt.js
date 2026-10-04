const q = (s) => document.querySelector(s);
const qa = (s) => Array.from(document.querySelectorAll(s));
const texts = qa('[data-testid="assistant-message"], [data-testid="assistant-turn"], article')
  .map((e) => (e.innerText || "").slice(0, 100));
const stops = qa('button').filter((b) => (b.getAttribute("aria-label") || "").toLowerCase().includes("stop"))
  .map((b) => ({ label: b.getAttribute("aria-label"), tid: b.getAttribute("data-testid"), disabled: b.disabled }));
return {
  href: location.href,
  resultStreaming: !!q('.result-streaming') || !!q('[data-testid="result-streaming"]'),
  streamingAttr: qa('[class*="streaming"], [data-testid*="stream"]').slice(0, 8).map((e) => ({
    tag: e.tagName, cls: (e.className || "").toString().slice(0, 60), tid: e.getAttribute("data-testid"),
  })),
  stops,
  lastCount: texts.length,
  lastTexts: texts.slice(-3),
  assistantTurns: qa('[data-testid="assistant-turn"]').length,
  userTurns: qa('[data-testid="user-turn"], [data-testid="user-message"]').length,
  composerText: (q('[contenteditable="true"][data-id="root"]') || q('div[contenteditable="true"]'))?.innerText?.slice(0, 60),
};
