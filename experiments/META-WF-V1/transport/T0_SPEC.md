# META-WF V1 — Transport T0 (send-fidelity test)
Status: SPEC FROZEN — run post-gate, BEFORE W1/W2/W3 scoring (per TASKS.yaml).

Purpose: prove the dispatch path delivers prompts byte-identical and extracts
responses completely, before any result counts.

## Checks (all must pass)
1. **prompt_fidelity**: request.raw sha256 == prompt sent; UI composer content
   equals prompt after send (compare extracted DOM text, whitespace-normalized).
   Fail on any truncation, re-encoding, or silent pre/post text added by adapter.
2. **response_extraction**: capture until streaming indicator gone (ChatGPT
   `.result-streaming` absent; Claude no partial marker), then 2s stability
   window; response.raw + metadata.json written; prompt_sha256/response_sha256
   recorded; status=ok only if both hashes verify.
3. **session_identity**: verify target thread ids match recorded tabs
   (chatgpt.com/c/6ac01362-..., claude.ai/chat/8f292e1f-...); refuse dispatch
   if the active tab URL mismatches.
4. **fail_loud**: any mismatch/timeout => status=fail + reason; zero silent
   retries that alter content; scoring phase never starts on fail.

## Procedure
- Send canary prompt (fixed, content-hashed) + one fixture prompt (F5 bundle).
- Human confirms the canary in both UIs; hashes compared by harness/transport
  script; verdict written to transport/T0_RESULT.json.
- Verdict values: PASS | FAIL (no partial pass).
- On FAIL: BROWSER_ADAPTER_STATUS = NOT_FOR_CRITICAL, stop for human
  (alternative transport decision — gate A5).

## Security
Never log cookies/api keys/session secrets (raw request = prompt text only).
