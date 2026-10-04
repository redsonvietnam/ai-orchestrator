# META-WF V1 — controlled workflow experiment (HANSTROKE fault detection)

STATUS: **HUMAN GATE #1 — STOPPED (awaiting approval, nothing executed)**

## What exists (frozen now)
- `prereg/TASKS.yaml` — workflows W0-W3, access symmetry, barrier, transport gate
- `prereg/GROUND_TRUTH.yaml` — 5 faults (NOT delivered to reviewers)
- `prereg/METRICS.yaml`, `prereg/SCORING.yaml` — frozen metrics/verdicts
- `prereg/PREREG.sha256` — freeze hashes
- `tasks/F1..F5/` — input/ raw/ source/ + SHA256SUMS (real HANSTROKE data;
  faults injected/reconstructed per GT; delivered bundle = input+raw+source+SHA256SUMS)
- `harness/build_tasks.py` (fixture builder, rerunnable, asserts real-data chains)
- `harness/verify_prereg.py` — PASS: sums, prereg hashes, GT isolation, 5 chains
- `transport/T0_SPEC.md` — transport test spec (run post-gate, pre-scoring)

## Not yet built (after gate #1, before any dispatch)
- `harness/score.py` (Python scorer) — frozen pre-run
- `verifier/verify.mjs` (Node.js independent verifier) — frozen pre-run
- `runs/`, `reports/` — created during execution

## Commands
    python -X utf8 D:\ai-orchestrator\experiments\META-WF-V1\harness\build_tasks.py   # rebuild fixtures
    python -X utf8 D:\ai-orchestrator\experiments\META-WF-V1\harness\verify_prereg.py # integrity check

## Hard scope
No HANSTROKE production edits; no human-screen run; no winner declaration;
no metric/threshold changes after execution starts; no Gemini/Grok.
