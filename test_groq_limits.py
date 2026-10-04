import os, json, urllib.request, urllib.error

key = os.environ["GROQ_API_KEY"]
big = ("The quick brown fox jumps over the lazy dog and runs across the field. " * 400)[:20000]


def call(m, tag):
    body = json.dumps({"model": m, "messages": [{"role": "user", "content": big}], "max_tokens": 8}).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36",
        },
    )
    try:
        r = json.load(urllib.request.urlopen(req, timeout=60))
        print(m, "[" + tag + "] OK tokens=", r["usage"]["prompt_tokens"])
    except urllib.error.HTTPError as e:
        print(m, "[" + tag + "] HTTP", e.code, e.read().decode()[:300])
    except Exception as e:
        print(m, "[" + tag + "] ERR", type(e).__name__, str(e)[:150])


for m in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]:
    call(m, "A")
    call(m, "B")
    call(m, "C")
