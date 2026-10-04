# META-WF V1 — Comparison Report

No winner declared. Waiting for HUMAN GATE #2.

## RAW OBSERVATIONS
- **W1** responses:
  - chatgpt: status=missing, chars=None
  - claude: status=missing, chars=None
  - claims total=0, unsupported=0, opened tasks=[]
- **W2** responses:
  - chatgpt: status=missing, chars=None
  - claude: status=missing, chars=None
  - chatgpt_cross: status=missing, chars=None
  - claims total=0, unsupported=0, opened tasks=[]
- **W3** responses:
  - chatgpt_blind: status=schema_missing, chars=75
  - claude_blind: status=schema_missing, chars=54
  - chatgpt_cross: status=schema_missing, chars=56
  - claims total=0, unsupported=0, opened tasks=[]
- **W0**: UNAVAILABLE (no human baseline, no LLM simulation).

## COMPUTED METRICS

### Primary

| metric | W1 | W2 | W3 |
|---|---|---|---|
| fault_detection_rate | 0.0 | 0.0 | 0.0 |
| false_accept_rate | 0.0 | 0.0 | 0.0 |
| final_decision_accuracy | 0.0 | 0.0 | 0.0 |
| critical_fault_missed | 3 | 3 | 3 |

### Secondary

| metric | W1 | W2 | W3 |
|---|---|---|---|
| artifact_access_rate | 0.0 | 0.0 | 0.0 |
| unsupported_claim_rate | 0.0 | 0.0 | 0.0 |
| rounds | 2 | 3 | 3 |
| model_calls | 0 | 0 | 3 |
| claude_calls | 0 | 0 | 1 |
| raw_character_volume_proxy | 0 | 0 | 379 |
| wall_clock_seconds | None | None | 300.0 |
| human_interventions | None | None | 0 |

- verifier_agreement_rate: 1.0
- reproducibility: True
- access_symmetry: {'W2': 'UNVERIFIED', 'W3': 'PASS'}
- per-fault verdicts (scorer): W1=F1:MISSED,F2:MISSED,F3:MISSED,F4:MISSED,F5:MISSED; W2=F1:MISSED,F2:MISSED,F3:MISSED,F4:MISSED,F5:MISSED; W3=F1:MISSED,F2:MISSED,F3:MISSED,F4:MISSED,F5:MISSED

## VERIFIER RECOMPUTATION

- verifier_output_sha256: b9c586abf5a8c5eec933b9f90941af28cf6673b675d76c08d7b9355eb95f088f
- verifier_output_run2_sha256: b9c586abf5a8c5eec933b9f90941af28cf6673b675d76c08d7b9355eb95f088f
- agreement cells agree: 15/15

## LIMITATIONS

- Ground-truth isolation: procedural, not cryptographic/security isolation (ACCEPT_PROCEDURAL_FOR_V1).
- Token volume = raw character/message volume proxy (NOT_PROVIDER_TOKEN_COUNT).
- FALSE_ACCEPT automatic rule: ACCEPT decisions only; endorsement without ACCEPT token scored MISSED.
- final_decision vocabulary normalization: REJECT_* => REJECT; FLAG_FOR_REWORK counts incorrect (documented prereg vocabulary mismatch).
- Verdict DETECTED_CORRECT/WRONG classification uses pre-hashed keyword rules (verdict_rules.json), a deterministic heuristic.
- W0 human baseline unavailable; no human reference curve.
- Browser transport is UI-level; T0 results bound transport validity (A5: BLOCK_W3 on fail).
- Ground truth says every task contains exactly one fault; false-positive behavior beyond ACCEPT decisions not fully automated.

## UNRESOLVED ISSUES

- Human review of raw responses pending at GATE_2.
- Replay anchoring comparison pending human interpretation (non-scoring).

## ORCHESTRATOR_INTERPRETATION

**NON_AUTHORITATIVE** — no interpretation provided pre-GATE_2; metrics above speak for themselves. No winner declared.
