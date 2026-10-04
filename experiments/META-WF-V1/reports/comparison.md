# META-WF V1 — Comparison Report

No winner declared. Waiting for HUMAN GATE #2.

## RAW OBSERVATIONS
- **W1** responses:
  - chatgpt: status=ok:inline, chars=7250
  - claude: status=missing, chars=None
  - claims total=9, unsupported=0, opened tasks=['F1', 'F2', 'F3', 'F4', 'F5']
- **W2** responses:
  - chatgpt: status=missing, chars=None
  - claude: status=missing, chars=None
  - chatgpt_cross: status=missing, chars=None
  - claims total=0, unsupported=0, opened tasks=[]
- **W3** responses:
  - chatgpt_blind: status=missing, chars=None
  - claude_blind: status=missing, chars=None
  - chatgpt_cross: status=missing, chars=None
  - claims total=0, unsupported=0, opened tasks=[]
- **W0**: UNAVAILABLE (no human baseline, no LLM simulation).

## COMPUTED METRICS

### Primary

| metric | W1 | W2 | W3 |
|---|---|---|---|
| fault_detection_rate | 0.8 | 0.0 | 0.0 |
| false_accept_rate | 0.2 | 0.0 | 0.0 |
| final_decision_accuracy | 0.8 | 0.0 | 0.0 |
| critical_fault_missed | 0 | 3 | 3 |

### Secondary

| metric | W1 | W2 | W3 |
|---|---|---|---|
| artifact_access_rate | 1.0 | 0.0 | 0.0 |
| unsupported_claim_rate | 0.0 | 0.0 | 0.0 |
| rounds | 2 | 3 | 3 |
| model_calls | 1 | 0 | 0 |
| claude_calls | 0 | 0 | 0 |
| raw_character_volume_proxy | 39369 | 0 | 0 |
| wall_clock_seconds | None | None | None |
| human_interventions | None | None | None |

- verifier_agreement_rate: None
- reproducibility: None
- access_symmetry: {'W2': 'UNVERIFIED', 'W3': 'UNVERIFIED'}
- per-fault verdicts (scorer): W1=F1:DETECTED_CORRECT,F2:FALSE_ACCEPT,F3:DETECTED_CORRECT,F4:DETECTED_CORRECT,F5:DETECTED_CORRECT; W2=F1:MISSED,F2:MISSED,F3:MISSED,F4:MISSED,F5:MISSED; W3=F1:MISSED,F2:MISSED,F3:MISSED,F4:MISSED,F5:MISSED

## VERIFIER RECOMPUTATION

- verifier_output_sha256: None
- verifier_output_run2_sha256: None
- agreement cells agree: 0/0

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
