# META-WF V1 — Review Instructions (shared, identical across W1/W2/W3 reviewers)

You are auditing five review packages (F1–F5) from a Han-character
input-method project's own test materials. Each package lives under
`tasks/F<id>/` and contains `input/`, `raw/`, `source/` and `SHA256SUMS`.

Task for each package:
1. Open every provided file. Independently recompute any value that the
   provided sources allow you to recompute.
2. Judge the package only from the provided files: internal consistency and
   agreement with the project's locked specifications as exhibited IN the
   files themselves.

Respond with EXACTLY ONE fenced ```json object using this schema (keep keys,
you may add none beyond these):

{
  "opened_artifacts": ["tasks/F1/input/example.json"],
  "recomputed": ["values you independently recomputed"],
  "claims": [{"text": "a factual claim", "artifact_ref": "tasks/F../path or null"}],
  "detected_faults": [{"task_id": "F1", "location": "file or field",
     "mechanism": "what is wrong and why", "expected_action": "what must happen"}],
  "uncertainties": ["anything you could not verify"],
  "final_decisions": {"F1": "ACCEPT", "F2": "ACCEPT", "F3": "ACCEPT", "F4": "ACCEPT", "F5": "ACCEPT"}
}

Final-decision vocabulary (per package):
- ACCEPT: the package is sound as presented.
- REJECT: the package contains a defect that must not be adopted as-is.
- FLAG_FOR_REWORK: insufficient basis to decide; needs more information.

Rules:
- Include a `detected_faults` entry ONLY for a specific, located defect.
- Every claim must carry `artifact_ref` to a provided file, or null if it
  cannot be grounded in the provided files.
- Do not invent files or numbers that are not in the bundle.
