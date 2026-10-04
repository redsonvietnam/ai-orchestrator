#!/usr/bin/env python3
# harness/score.py — prereg-designated scorer entrypoint (SCORING.yaml).
# Thin shim: delegates to the hash-locked implementation verifier/score.py
# with identical argv. Never edits verdict/report files itself.
import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "verifier" / "score.py"
if not TARGET.exists():
    sys.exit(f"missing scorer implementation: {TARGET}")
sys.argv[0] = str(TARGET)
runpy.run_path(str(TARGET), run_name="__main__")
