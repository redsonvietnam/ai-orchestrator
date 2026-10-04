const qa = (s) => Array.from(document.querySelectorAll(s));
const turns = qa('[data-testid^="conversation-turn"]');
return {
  turnCount: turns.length,
  turns: turns.slice(-4).map((t) => ({
    tid: t.getAttribute("data-testid"),
    hasMarkdown: !!t.querySelector(".markdown"),
    mdText: (t.querySelector(".markdown")?.innerText || "").slice(0, 90),
    direct: (t.innerText || "").slice(0, 90),
    userTid: !!t.querySelector('[data-testid="user-turn"]'),
    innerTestids: Array.from(t.querySelectorAll("[data-testid]")).slice(0, 6)
      .map((e) => e.getAttribute("data-testid")),
  })),
  resultStreaming: !!document.querySelector(".result-streaming"),
  stopBtns: qa("button").filter((b) => (b.getAttribute("aria-label") || "").toLowerCase().includes("dừng")
    || (b.getAttribute("aria-label") || "").toLowerCase().includes("stop"))
    .map((b) => b.getAttribute("aria-label")),
  buttonsNow: qa("button[data-testid]").map((b) => b.getAttribute("data-testid")).slice(0, 20),
};
