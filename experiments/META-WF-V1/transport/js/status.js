// status probe: title, final URL, composer presence, logged-in hints
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
for (let i = 0; i < 20; i++) {
  if (document.readyState === "complete") break;
  await sleep(500);
}
await sleep(2500);
const q = (s) => !!document.querySelector(s);
const chatgpt = location.href.includes("chatgpt.com");
const out = {
  href: location.href,
  title: document.title,
  readyState: document.readyState,
  bodyChars: (document.body.innerText || "").length,
  composer: chatgpt
    ? q('[contenteditable="true"][data-id="root"]') || q('[contenteditable="true"][aria-label*="Chat"]') || q('div[contenteditable="true"]')
    : q('[data-testid="chat-input"]') || q('div[contenteditable="true"].ProseMirror'),
  sendBtn: chatgpt ? q('button[data-testid="send-button"]') : q('button[aria-label="Send message"]') || q('button[data-testid="chat-input-send"]'),
  loginHint: (document.body.innerText || "").slice(0, 600),
};
return out;
