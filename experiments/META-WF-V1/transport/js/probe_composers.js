const qa = (s) => Array.from(document.querySelectorAll(s));
return qa('div[contenteditable="true"]').map((e) => {
  const r = e.getBoundingClientRect();
  const cs = getComputedStyle(e);
  return {
    aria: e.getAttribute("aria-label"), dataId: e.getAttribute("data-id"),
    rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
    visible: cs.display !== "none" && cs.visibility !== "hidden" && r.width > 0 && r.height > 0,
    textLen: (e.innerText || "").length,
    textHead: (e.innerText || "").slice(0, 50),
  };
});
