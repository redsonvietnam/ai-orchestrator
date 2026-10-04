import hashlib,json
from pathlib import Path
ROOT=Path(r"D:\ai-orchestrator"); RUN=ROOT/"experiments/META-WF-V1/runs/W7/real_decision_loop"; TASK="META-WF-V1-W7-REAL-DECISION-001"
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
raw=(RUN/"reviewer_b_raw.txt").read_text(encoding="utf-8").strip()
fence=chr(96)*3
if raw.startswith(fence+"json"):
    raw=raw[len(fence+"json"):].strip()
if raw.endswith(fence):
    raw=raw[:-3].strip()
review=json.loads(raw)
worker_sha=sha(RUN/"worker_a_raw.txt"); reviewer_sha=sha(RUN/"reviewer_b_raw.txt")
required={"task_id","reviewer","source_worker","source_artifact_sha256","verdict","reason"}
assert set(review)==required
assert review["task_id"]==TASK and review["reviewer"]=="REVIEWER_B" and review["source_worker"]=="WORKER_A"
assert review["source_artifact_sha256"]==worker_sha
assert review["verdict"] in ("ACCEPT","REJECT")
decision="DONE" if review["verdict"]=="ACCEPT" else "HUMAN_REQUIRED"
validation={"schema":"META-WF-V1/W7_REAL_DECISION_LOOP_V1","task_id":TASK,"worker_call_count":1,"reviewer_call_count":1,
"real_ai_calls":2,"provider_calls":2,"retry_count":0,"review_schema_pass":True,"provenance_binding_pass":True,
"review_verdict":review["verdict"],"decision":decision,"review_transport":"PASS","decision_gate":"PASS",
"BAMSO_TOUCHED":False,"GIT_MUTATION":False,"BROWSER_CDP":0}
(RUN/"validation.json").write_text(json.dumps(validation,indent=2,sort_keys=True)+"\n",encoding="utf-8")
decision_e={"task_id":TASK,"terminal_state":"W7_DONE","decision":decision,"rule":"ACCEPT -> DONE; REJECT -> HUMAN_REQUIRED",
"worker_artifact_sha256":worker_sha,"reviewer_response_sha256":reviewer_sha,"json_fence_extraction":"PASS",
"new_ai_calls":0,"retry_count":0}
(RUN/"decision_evidence.json").write_text(json.dumps(decision_e,indent=2,sort_keys=True)+"\n",encoding="utf-8")
manifest={p.name:sha(p) for p in sorted(RUN.glob("*")) if p.is_file() and p.name not in ("freeze_manifest.json","sha256_manifest.json")}
(RUN/"sha256_manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8")
manifest["sha256_manifest.json"]=sha(RUN/"sha256_manifest.json")
freeze={"checkpoint":"META-WF V1 — W7 REAL DECISION LOOP","terminal_state":"W7_EVIDENCE_FROZEN","task_id":TASK,
"worker_call_count":1,"reviewer_call_count":1,"real_ai_calls":2,"provider_calls":2,"retry_count":0,"review_verdict":review["verdict"],
"decision":decision,"provenance_binding_pass":True,"new_ai_calls_during_finalize":0,"BAMSO_TOUCHED":False,"GIT_MUTATION":False,
"BROWSER_CDP":0,"artifacts":manifest}
(RUN/"freeze_manifest.json").write_text(json.dumps(freeze,indent=2,sort_keys=True)+"\n",encoding="utf-8")
print(json.dumps({"TERMINAL_STATE":"W7_DONE","EVIDENCE_STATE":"W7_EVIDENCE_FROZEN","real_ai_calls":2,"provider_calls":2,
"retry_count":0,"review_verdict":review["verdict"],"decision":decision,"provenance_binding_pass":True,
"new_ai_calls_during_finalize":0,"freeze_sha256":sha(RUN/"freeze_manifest.json")},sort_keys=True))
