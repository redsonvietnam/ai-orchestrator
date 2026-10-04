const turns = document.querySelectorAll('[data-testid^="conversation-turn"]');
const out = [];
for (let i = Math.max(0, turns.length - 3); i < turns.length; i++) {
  const t = turns[i];
  const md = t.querySelector(".markdown");
  out.push({
    tid: t.getAttribute("data-testid"),
    hasMd: !!md,
    mdText: (md ? md.innerText : (t.innerText || "")).trim().slice(0, 120),
    mdLen: md ? md.innerText.length : 0,
  });
}
return out;
