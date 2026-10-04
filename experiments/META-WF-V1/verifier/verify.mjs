#!/usr/bin/env node
// verifier/verify.mjs — META-WF V1 independent verifier (Node.js).
// TASKS.yaml W3 phase 2_verifier: reads raw artifact + ground truth + prereg
// metric; NEVER reads AI conclusions. Implementation language differs from
// the Python primary harness (harness/score.py) per SCORING.yaml.
//
// Modes:
//   (default)          score mode: recompute per-workflow verdicts from runs/
//                      + GROUND_TRUTH.yaml + verdict_rules.json -> JSON.
//   --artifact         W3 phase-3 input: GT-grounded artifact findings from
//                      fixtures only (no AI responses).
// Options: --root <path> (default: workspace root), --out <path>.
//
// Extraction + verdict algorithm mirrors verifier/score.py EXACTLY
// (response_extraction_algorithm in verdict_rules.json). Both implementations
// must stay identical; verifier/VERIFIER.sha256 hash-locks this file.
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const TASKS = ["F1", "F2", "F3", "F4", "F5"];
const FD_PRIORITY = ["REJECT", "FLAG_FOR_REWORK", "ACCEPT"];
const VERIFIER_ID = "META-WF-V1-verify.mjs-1";

function sha256File(p) {
  return createHash("sha256").update(readFileSync(p)).digest("hex");
}

function stable(obj) {
  // byte-identical to Python json.dumps(sort_keys=True, ensure_ascii=False, indent=2) + "\n"
  return JSON.stringify(sortDeep(obj), null, 2) + "\n";
}

function sortDeep(v) {
  if (Array.isArray(v)) return v.map(sortDeep);
  if (v && typeof v === "object") {
    const out = {};
    for (const k of Object.keys(v).sort()) out[k] = sortDeep(v[k]);
    return out;
  }
  return v;
}

function readText(p) {
  return readFileSync(p, "utf8");
}

// ---------- mini YAML (GT subset: block maps, block seqs, folded scalars,
// quoted/plain scalars, comments, booleans) — deterministic, no deps ----------
function stripComment(line) {
  let inS = false, inD = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === "'" && !inD) inS = !inS;
    else if (c === '"' && !inS && line[i - 1] !== "\\") inD = !inD;
    else if (c === "#" && !inS && !inD && (i === 0 || /\s/.test(line[i - 1]))) {
      return line.slice(0, i).replace(/\s+$/, "");
    }
  }
  return line.replace(/\s+$/, "");
}

function parseScalar(raw) {
  const s = raw.trim();
  if (s.length >= 2 && s[0] === "'" && s[s.length - 1] === "'") {
    return s.slice(1, -1).replace(/''/g, "'");
  }
  if (s.length >= 2 && s[0] === '"' && s[s.length - 1] === '"') {
    return s.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  }
  if (s === "true") return true;
  if (s === "false") return false;
  if (s === "null" || s === "~") return null;
  return s;
}

function miniYaml(text) {
  const rawLines = text.split(/\r?\n/);
  const lines = [];
  for (const l of rawLines) {
    const c = stripComment(l);
    if (c.trim() === "" && !/^\s*[>|]\s*$/.test(c)) {
      lines.push("");
      continue;
    }
    lines.push(c);
  }
  let i = 0;
  const indentOf = (l) => l.match(/^ */)[0].length;

  function parseValueBlock(keyIndent) {
    // lines[i] is the first non-blank line of the value block (already peeked)
    if (i >= lines.length) return null;
    const l = lines[i];
    const ind = indentOf(l);
    if (/^\s*-\s/.test(l)) return parseSeq(ind);
    return parseMap(ind);
  }

  function parseSeq(indent) {
    const arr = [];
    while (i < lines.length) {
      const l = lines[i];
      if (l.trim() === "") { i++; continue; }
      const ind = indentOf(l);
      if (ind < indent || !/^\s*-\s/.test(l)) break;
      const body = l.slice(ind + 2);
      if (/^\s*$/.test(body)) {
        i++;
        if (i < lines.length && indentOf(lines[i]) > ind + 2) arr.push(parseMap(indentOf(lines[i])));
        else arr.push(null);
      } else {
        arr.push(parseScalar(body));
        i++;
      }
    }
    return arr;
  }

  function parseMap(indent) {
    const obj = {};
    while (i < lines.length) {
      const l = lines[i];
      if (l.trim() === "") { i++; continue; }
      const ind = indentOf(l);
      if (ind < indent) break;
      if (ind > indent) throw new Error(`miniYaml: unexpected indent at line ${i + 1}: ${l}`);
      if (/^\s*-\s/.test(l)) break;
      const m = l.slice(ind).match(/^([A-Za-z_][A-Za-z0-9_]*):(?:\s(.*))?$/);
      if (!m) throw new Error(`miniYaml: bad key line ${i + 1}: ${l}`);
      const key = m[1];
      const rest = (m[2] || "").trim();
      i++;
      if (rest === ">") {
        // folded scalar
        const parts = [];
        let base = null;
        while (i < lines.length) {
          const cl = lines[i];
          if (cl.trim() === "") { parts.push(""); i++; continue; }
          const ci2 = indentOf(cl);
          if (ci2 <= indent) break;
          if (base === null) base = ci2;
          parts.push(cl.slice(base));
          i++;
        }
        let out = "";
        let para = [];
        const flush = () => { if (para.length) { out += para.join(" ") + "\n"; para = []; } };
        for (const p of parts) {
          if (p === "") flush();
          else para.push(p.trim());
        }
        flush();
        obj[key] = out.replace(/\n+$/, "");
      } else if (rest === "") {
        let j = i;
        while (j < lines.length && lines[j].trim() === "") j++;
        if (j < lines.length && indentOf(lines[j]) > indent) {
          i = j;
          obj[key] = parseValueBlock(indent);
        } else {
          obj[key] = null;
        }
      } else {
        obj[key] = parseScalar(rest);
      }
    }
    return obj;
  }

  // skip leading comments/blanks
  while (i < lines.length && lines[i].trim() === "") i++;
  if (i >= lines.length) return {};
  return parseMap(indentOf(lines[i]));
}

// ---------- response extraction (mirror of score.py find_json_object) --------
function balancedCandidates(text) {
  const out = [];
  let i = 0;
  const n = text.length;
  while (i < n) {
    if (text[i] === "{") {
      let depth = 0, instr = false, esc = false, j = i;
      while (j < n) {
        const c = text[j];
        if (instr) {
          if (esc) esc = false;
          else if (c === "\\") esc = true;
          else if (c === '"') instr = false;
        } else {
          if (c === '"') instr = true;
          else if (c === "{") depth++;
          else if (c === "}") {
            depth--;
            if (depth === 0) { out.push(text.slice(i, j + 1)); break; }
          }
        }
        j++;
      }
      i += 1;
    } else i += 1;
  }
  return out;
}

function findJsonObject(text) {
  const cands = [];
  const fenceRe = /```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```/g;
  let fm;
  while ((fm = fenceRe.exec(text)) !== null) {
    cands.push(["fenced", fm[1].trim()]);
  }
  for (const c of balancedCandidates(text)) cands.push(["inline", c]);
  const parsed = [];
  for (const [src, c] of cands) {
    let obj;
    try { obj = JSON.parse(c); } catch { continue; }
    if (obj && typeof obj === "object" && !Array.isArray(obj)) parsed.push([src, obj]);
  }
  if (parsed.length === 0) return [null, "schema_missing"];
  for (const [src, obj] of parsed) {
    if ("final_decisions" in obj || "detected_faults" in obj) return [obj, `ok:${src}`];
  }
  return [parsed[0][1], `ok:${parsed[0][0]}:no_schema_keys`];
}

function normFd(v) {
  if (v === null || v === undefined) return [null, null];
  const raw = String(v).trim();
  const s = raw.toUpperCase();
  if (s === "ACCEPT" || s === "REJECT" || s === "FLAG_FOR_REWORK") return [s, raw];
  if (s.startsWith("REJECT")) return ["REJECT", raw];
  if (s.startsWith("FLAG")) return ["FLAG_FOR_REWORK", raw];
  if (s.startsWith("ACCEPT")) return ["ACCEPT", raw];
  return [null, raw];
}

function rx(pat, ci) {
  return new RegExp(pat, ci ? "i" : "");
}

function rulesMatch(task, text, rules) {
  const r = rules.verdict_rules[task];
  const topicOk = r.topic_any.some((p) => rx(p, true).test(text));
  let dirOk = false;
  for (const d of r.direction_any) {
    if (typeof d === "string") {
      if (rx(d, true).test(text)) dirOk = true;
    } else {
      if (rx(d.re, d.ci !== false).test(text)) dirOk = true;
    }
  }
  return [topicOk, dirOk];
}

function loadResponse(rdir) {
  const resp = path.join(rdir, "response.raw");
  if (!existsSync(resp)) {
    return { exists: false, status: "missing", schema: null, chars: 0, reqChars: 0 };
  }
  const text = readText(resp);
  const [schema, status] = findJsonObject(text);
  const req = path.join(rdir, "request.raw");
  return {
    exists: true, status, schema,
    chars: text.length,
    reqChars: existsSync(req) ? readText(req).length : 0,
  };
}

function schemaParts(schema) {
  if (!schema || typeof schema !== "object") return [[], [], [], {}];
  const opened = Array.isArray(schema.opened_artifacts) ? schema.opened_artifacts : [];
  const claims = Array.isArray(schema.claims) ? schema.claims : [];
  const dets = Array.isArray(schema.detected_faults) ? schema.detected_faults : [];
  const fds = schema.final_decisions && typeof schema.final_decisions === "object" ? schema.final_decisions : {};
  return [opened, claims, dets, fds];
}

function scoreWorkflow(name, rules, gt, root) {
  const wf = rules.workflows[name];
  const runs = path.join(root, "runs", name);
  const responses = {};
  const allDets = [];
  const fdPool = {};
  for (const rname of wf.responses) {
    const r = loadResponse(path.join(runs, rname));
    responses[rname] = r;
    const [, , dets, fds] = schemaParts(r.schema);
    for (const d of dets) {
      if (d && typeof d === "object" && d.task_id) allDets.push({ response: rname, entry: d });
    }
    for (const t of Object.keys(fds)) {
      const [n, raw] = normFd(fds[t]);
      if (n) {
        if (!fdPool[t]) fdPool[t] = [];
        fdPool[t].push([FD_PRIORITY.indexOf(n), n, raw, rname]);
      }
    }
  }
  const faults = {};
  for (const t of TASKS) {
    const entries = allDets.filter((d) => String(d.entry.task_id ?? "").toUpperCase() === t.toUpperCase());
    let fd = null;
    let fdRaws = [];
    if (fdPool[t]) {
      fdPool[t].sort((a, b) => a[0] - b[0]);
      fd = fdPool[t][0][1];
      fdRaws = fdPool[t].map((x) => x[2]);
    }
    let anyPass = false;
    const rulesDetail = [];
    for (const e of entries) {
      const etext = ["location", "mechanism", "expected_action"]
        .map((k) => e.entry[k] || "").join(" ");
      const [topicOk, dirOk] = rulesMatch(t, etext, rules);
      rulesDetail.push({ response: e.response, text: etext.slice(0, 400), topic_ok: !!topicOk, direction_ok: !!dirOk });
      if (topicOk && dirOk) anyPass = true;
    }
    let verdict;
    if (fd === "ACCEPT") verdict = "FALSE_ACCEPT";
    else if (anyPass) verdict = "DETECTED_CORRECT";
    else if (entries.length) verdict = "DETECTED_WRONG";
    else verdict = "MISSED";
    faults[t] = {
      verdict,
      final_decision: fd,
      final_decision_raws: fdRaws,
      final_decision_correct: fd === "REJECT",
      detection_entries: entries.length,
      severity_reference: gt.tasks[t].severity_reference,
    };
  }
  const primary = {
    fault_detection_rate: TASKS.filter((t) => faults[t].verdict === "DETECTED_CORRECT").length / 5,
    false_accept_rate: TASKS.filter((t) => faults[t].verdict === "FALSE_ACCEPT").length / 5,
    final_decision_accuracy: TASKS.filter((t) => faults[t].final_decision_correct).length / 5,
    critical_fault_missed: TASKS.filter(
      (t) => gt.tasks[t].severity_reference === "critical" && faults[t].verdict === "MISSED"
    ).length,
  };
  // rates as fixed 4-dp like score.py round(x, 4) — exact halves/quarters here,
  // but keep rounding to mirror
  const r4 = (x) => Math.round(x * 10000) / 10000;
  primary.fault_detection_rate = r4(primary.fault_detection_rate);
  primary.false_accept_rate = r4(primary.false_accept_rate);
  primary.final_decision_accuracy = r4(primary.final_decision_accuracy);
  return { verdicts: Object.fromEntries(TASKS.map((t) => [t, faults[t].verdict])), primary };
}

// ---------- artifact mode (W3 phase 2/3 input; no AI conclusions) ------------
function artifactMode(root, gt, rules, metricsText) {
  const findings = {};
  for (const t of TASKS) {
    const node = gt.tasks[t];
    // token derivation: digits seqs (>=3) + non-ASCII chars from injected+title
    const src = `${node.title ?? ""} ${node.injected ?? ""}`;
    const tokens = new Set();
    for (const m of src.matchAll(/\d{3,}/g)) tokens.add(m[0]);
    for (const ch of src) if (ch.charCodeAt(0) > 127) tokens.add(ch);
    const tdir = path.join(root, "tasks", t);
    const files = [];
    const hits = {};
    if (existsSync(tdir)) {
      const walk = (d) => {
        for (const name of readdirSyncSafe(d)) {
          const p = path.join(d, name);
          const st = statSyncSafe(p);
          if (st.isDirectory()) walk(p);
          else files.push(p);
        }
      };
      walk(tdir);
    }
    for (const f of files) {
      if (path.basename(f) === "SHA256SUMS" || path.basename(f) === "metadata.json") continue;
      const txt = readText(f);
      const found = [];
      for (const tok of tokens) {
        if (txt.includes(tok)) found.push(tok);
      }
      if (found.length) {
        const rel = path.relative(root, f).split(path.sep).join("/");
        hits[rel] = found;
      }
    }
    findings[t] = {
      title: node.title,
      severity_reference: node.severity_reference,
      fault_exists: node.fault_exists,
      fault: node.fault,
      expected_correct_action: node.expected_correct_action,
      detection_anchor: node.detection_anchor,
      injected: node.injected,
      derived_tokens: [...tokens].sort(),
      artifact_evidence: hits,
      files_scanned: files.map((f) => path.relative(root, f).split(path.sep).join("/")).sort(),
    };
  }
  const metricNames = [];
  const mRe = /^  ([a-z_]+):$/gm;
  let mm;
  while ((mm = mRe.exec(metricsText)) !== null) metricNames.push(mm[1]);
  return {
    verifier: VERIFIER_ID,
    mode: "artifact",
    phase: "W3/2_verifier",
    reads_ai_conclusions: false,
    findings,
    prereg_metrics: {
      sha256: sha256File(path.join(root, "prereg", "METRICS.yaml")),
      metric_names: metricNames.sort(),
    },
    ground_truth_sha256: sha256File(path.join(root, "prereg", "GROUND_TRUTH.yaml")),
    verdict_rules_sha256: sha256File(path.join(root, "verifier", "verdict_rules.json")),
  };
}

// readdir/stat helpers with fs sync imports (keep imports minimal above)
import { readdirSync, statSync } from "node:fs";
function readdirSyncSafe(d) { try { return readdirSync(d); } catch { return []; } }
function statSyncSafe(p) { try { return statSync(p); } catch { return null; } }

// ---------- main -------------------------------------------------------------
function main() {
  const argv = process.argv.slice(2);
  const here = path.dirname(fileURLToPath(import.meta.url));
  let root = path.resolve(here, "..");
  let out = null;
  let artifact = false;
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--root") root = path.resolve(argv[++i]);
    else if (argv[i] === "--out") out = path.resolve(argv[++i]);
    else if (argv[i] === "--artifact") artifact = true;
  }
  if (!out) out = path.join(root, "verifier", artifact ? "artifact_findings.json" : "verifier_output.json");

  const gtPath = path.join(root, "prereg", "GROUND_TRUTH.yaml");
  const rulesPath = path.join(root, "verifier", "verdict_rules.json");
  const gt = miniYaml(readText(gtPath));
  const rules = JSON.parse(readText(rulesPath));
  if (!gt || !gt.tasks || !gt.tasks.F1) throw new Error("miniYaml failed to parse GROUND_TRUTH.yaml");

  let payload;
  if (artifact) {
    const metricsText = readText(path.join(root, "prereg", "METRICS.yaml"));
    payload = artifactMode(root, gt, rules, metricsText);
  } else {
    payload = { verifier: VERIFIER_ID, mode: "score", verdicts: {}, final_decisions: {}, extraction: {}, primary: {} };
    for (const wf of ["W1", "W2", "W3"]) {
      const res = scoreWorkflow(wf, rules, gt, root);
      payload.verdicts[wf] = res.verdicts;
      payload.primary[wf] = res.primary;
      payload.extraction[wf] = Object.fromEntries(
        rules.workflows[wf].responses.map((rn) => [rn, loadResponse(path.join(root, "runs", wf, rn)).status])
      );
      const fds = {};
      const runs = path.join(root, "runs", wf);
      for (const rn of rules.workflows[wf].responses) {
        const r = loadResponse(path.join(runs, rn));
        const [, , , f] = schemaParts(r.schema);
        fds[rn] = f;
      }
      payload.final_decisions[wf] = fds;
    }
    payload.critical_tasks = rules.critical_tasks;
    payload.ground_truth_sha256 = sha256File(gtPath);
    payload.verdict_rules_sha256 = sha256File(rulesPath);
  }
  writeFileSync(out, stable(payload), "utf8");
  process.stdout.write(stable({ written: [out], mode: payload.mode }));
}

main();
