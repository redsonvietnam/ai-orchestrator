# AI Tab Orchestrator (all-free stack)

Điều phối nhiều tab AI (Claude, ChatGPT, Gemini) cùng giải quyết một bài toán.

## Stack (100% free)

- **browser-use** (Apache 2.0) — driver điều khiển trình duyệt, multi-agent
- **Chrome + CDP** — mỗi AI worker chạy trên một Chrome instance riêng (port 9222/9223/9224, profile riêng)
- **Gemini free tier** — LLM "đôi tay" cho browser-use (không mất tiền, có giới hạn RPM)
- **CloakBrowser** (MIT, đã cài) — lớp stealth tùy chọn cho site có anti-bot

## Setup một lần

1. Lấy key Gemini FREE: https://aistudio.google.com/apikey
   ```powershell
   $env:GOOGLE_API_KEY = "key-cua-ban"
   ```
2. Khởi 3 cửa sổ Chrome automation (mỗi cửa sổ = 1 AI site, profile riêng):
   ```powershell
   .\.venv\Scripts\python.exe orchestrator.py --launch-only
   ```
3. **Đăng nhập thủ công 1 lần** vào Claude/ChatGPT/Gemini trong 3 cửa sổ Chrome automation đó (cookie lưu lại trong profile, dùng lại được).

## Chạy

```powershell
# Pipeline: Claude viết -> ChatGPT review -> Gemini chốt
.\.venv\Scripts\python.exe orchestrator.py "Viết hàm Python đảo ngược linked list"

# Swarm: cả 3 AI chạy song song, Gemini tổng hợp
.\.venv\Scripts\python.exe orchestrator.py --mode swarm "Giải thích CAP theorem"

# Bài toán dài: ghi file rồi chạy
.\.venv\Scripts\python.exe orchestrator.py --problem-file task.md
```

Kết quả: `runs/final.md` (câu trả lời cuối), `runs/board.json` (toàn bộ quá trình), `runs/*.response.txt` (response từng AI).

## Kiến trúc

```
orchestrator.py            điều phối, board.json là shared state
  ├─ Chrome :9222 (profile-claude)  ── worker.py (Agent + BrowserSession(cdp_url)) ── tab claude.ai  [ARCHITECT]
  ├─ Chrome :9223 (profile-chatgpt) ── worker.py                            ── tab chatgpt.com [REVIEWER]
  └─ Chrome :9224 (profile-gemini)  ── worker.py                            ── tab gemini.google.com [FINALIZER]
```

Mỗi worker là một process riêng (named daemon `BU_NAME=worker-<name>`) nên các tab chạy song song không tranh nhau.

## File

- `orchestrator.py` — orchestrator chính (pipeline / swarm)
- `worker.py` — 1 worker = 1 tab AI: đi tới chat site, gõ prompt, đọc response
- `smoke.py` — test khói driver

## Troubles

- Daemon lỗi → `browser-use doctor`; Chrome CDP phải đang chạy (orchestrator tự launch)
- Bị chặn bot trên claude.ai/chatgpt.com → chuyển worker sang CloakBrowser (launch cloakbrowser với `--remote-debugging-port=<port>`, trỏ worker vào port đó)
- Hết free quota Gemini → đổi `BU_MODEL` hoặc cài Ollama local (miễn phí, offline)
