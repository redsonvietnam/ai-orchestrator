from __future__ import annotations
import hashlib, json, sys
from pathlib import Path
ROOT=Path(r"D:\ai-orchestrator"); HARNESS=ROOT/"experiments/META-WF-V1/harness"; RUN=ROOT/"experiments/META-WF-V1/runs/W7/real_decision_loop"
sys.path.insert(0,str(HARNESS))
from real_worker_adapter import OpenCodeHTTPTransport, ContractError
TASK="META-WF-V1-W7-REAL-DECISION-001"; PROVIDER="9router-free"; MODEL="free-fast-v2"; AGENT="explore"; PORT=4100
def sha(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()
def dump(p,x): p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(x,indent=2,ensure_ascii=False,sort_keys=True)+"\n",encoding="utf-8")
def call(transport,prompt,role):
    text,_=transport.execute(prompt,PROVIDER,MODEL,AGENT)
    (RUN/f"{role.lower()}_raw.txt").write_text(text,encoding="utf-8")
    return text
def main():
    RUN.mkdir(parents=True,exist_ok=True)
    worker_prompt=(f"TASK_ID={TASK}\nYou are WORKER_A in a controlled orchestration proof. "
                   "Return exactly one concise artifact with these three lines and nothing else:\n"
                   "WORKER_A_RESULT=PASS\nTASK_BINDING=VALID\nREVIEW_REQUIRED=true")
    transport=OpenCodeHTTPTransport(port=PORT,timeout=15.0)
    try:
        transport.start()
        worker_text=call(transport,worker_prompt,"WORKER_A")
        worker_sha=sha(worker_text)
        dump(RUN/"worker_a_metadata.json",{"task_id":TASK,"role":"WORKER_A","provider":PROVIDER,"model":MODEL,"sha256":worker_sha,"execution":"real"})
        reviewer_prompt=(f"TASK_ID={TASK}\nYou are REVIEWER_B. Validate the supplied Worker A artifact. "
                         "Return ONLY one JSON object with keys exactly: task_id, reviewer, source_worker, "
                         "source_artifact_sha256, verdict, reason. verdict must be ACCEPT or REJECT. "
                         "Accept only if the artifact contains all three exact required lines: "
                         "WORKER_A_RESULT=PASS, TASK_BINDING=VALID, REVIEW_REQUIRED=true.\n\n"
                         f"SOURCE_ARTIFACT_SHA256={worker_sha}\nSOURCE_ARTIFACT_BEGIN\n{worker_text}\nSOURCE_ARTIFACT_END")
        reviewer_text=call(transport,reviewer_prompt,"REVIEWER_B")
        reviewer_sha=sha(reviewer_text)
        dump(RUN/"reviewer_b_metadata.json",{"task_id":TASK,"role":"REVIEWER_B","provider":PROVIDER,"model":MODEL,"sha256":reviewer_sha,"execution":"real"})
    finally:
        transport.stop()
    try: review=json.loads(reviewer_text)
    except Exception as e: raise ContractError("REVIEW_SCHEMA_INVALID: "+str(e))
    required={"task_id","reviewer","source_worker","source_artifact_sha256","verdict","reason"}
    if set(review)!=required: raise ContractError("REVIEW_SCHEMA_INVALID_KEYS")
    if review["task_id"]!=TASK or review["reviewer"]!="REVIEWER_B" or review["source_worker"]!="WORKER_A": raise ContractError("REVIEW_BINDING_INVALID")
    if review["source_artifact_sha256"]!=worker_sha: raise ContractError("REVIEW_PROVENANCE_MISMATCH")
    if review["verdict"] not in ("ACCEPT","REJECT"): raise ContractError("REVIEW_VERDICT_INVALID")
    decision="DONE" if review["verdict"]=="ACCEPT" else "HUMAN_REQUIRED"
    validation={"schema":"META-WF-V1/W7_REAL_DECISION_LOOP_V1","task_id":TASK,"worker_call_count":1,"reviewer_call_count":1,
      "real_ai_calls":2,"provider_calls":2,"retry_count":0,"review_schema_pass":True,"provenance_binding_pass":True,
      "review_verdict":review["verdict"],"decision":decision,"BAMSO_TOUCHED":False,"GIT_MUTATION":False,"BROWSER_CDP":0}
    dump(RUN/"validation.json",validation)
    dump(RUN/"decision_evidence.json",{"task_id":TASK,"decision":decision,"terminal_state":"W7_DONE",
      "rule":"ACCEPT -> DONE; REJECT -> HUMAN_REQUIRED","worker_artifact_sha256":worker_sha,"reviewer_response_sha256":reviewer_sha})
    manifest={p.name:sha(p.read_text(encoding="utf-8")) for p in sorted(RUN.glob("*")) if p.is_file() and p.name!="freeze_manifest.json"}
    dump(RUN/"sha256_manifest.json",manifest)
    print(json.dumps({"TERMINAL_STATE":"W7_DONE","worker_call_count":1,"reviewer_call_count":1,"real_ai_calls":2,
      "provider_calls":2,"retry_count":0,"review_schema_pass":True,"provenance_binding_pass":True,
      "review_verdict":review["verdict"],"decision":decision,"BAMSO_TOUCHED":False,"GIT_MUTATION":False,"BROWSER_CDP":0},sort_keys=True))
if __name__=="__main__": main()
