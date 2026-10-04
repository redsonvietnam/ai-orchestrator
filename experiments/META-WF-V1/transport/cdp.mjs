#!/usr/bin/env node
// transport/cdp.mjs — deterministic CDP adapter for META-WF V1 transport T0+.
// Chrome: --remote-debugging-port=9222 --user-data-dir=D:\\ai-orchestrator\\profile-claude
// No LLM click decisions: every step is a fixed script executed via Runtime.evaluate.
//
// Commands:
//   list
//   new <url>
//   navigate <urlPart> <url>
//   eval <urlPart> <scriptFile> [--out <file>]
//   probe-file-input <urlPart>
//   upload-files <urlPart> <absolutePath> [...]
//   screenshot <urlPart> [out.png]
//   halt <urlPart>
import { existsSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { realpathSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";

const CDP = "http://127.0.0.1:9222";

async function cdpGet(p) {
  const r = await fetch(CDP + p);
  if (!r.ok) throw new Error(`CDP GET ${p} -> ${r.status}`);
  return r.json();
}

async function tabs() {
  const list = await cdpGet("/json/list");
  return list.filter((t) => t.type === "page");
}

function findTab(urlPart) {
  if (urlPart.startsWith("id:")) {
    const want = urlPart.slice(3).toUpperCase();
    const t = tabsSyncCache.find((t) => t.id.toUpperCase() === want);
    if (!t) throw new Error(`no page tab with id: ${want}`);
    return t;
  }
  const t = tabsSyncCache.find((t) => t.url.includes(urlPart));
  if (!t) throw new Error(`no page tab matching: ${urlPart}\nURLs: ${tabsSyncCache.map((x) => x.url).join("\n")}`);
  return t;
}

let tabsSyncCache = [];

function openWs(wsUrl) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(wsUrl);
    let id = 0;
    const pending = new Map();
    const eventHandlers = new Map();

    socket.onopen = () => {
      const api = {
        send(method, params = {}) {
          return new Promise((res, rej) => {
            const mid = ++id;
            pending.set(mid, { res, rej });
            socket.send(JSON.stringify({ id: mid, method, params }));
          });
        },
        on(method, handler) {
          const set = eventHandlers.get(method) || new Set();
          set.add(handler);
          eventHandlers.set(method, set);
          return () => set.delete(handler);
        },
        close() { socket.close(); },
      };
      resolve(api);
    };

    socket.onerror = (e) => reject(new Error("ws error: " + (e.message || e)));
    socket.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && pending.has(msg.id)) {
        const { res, rej } = pending.get(msg.id);
        pending.delete(msg.id);
        if (msg.error) rej(new Error(msg.error.message));
        else res(msg.result);
        return;
      }
      if (msg.method && eventHandlers.has(msg.method)) {
        for (const handler of eventHandlers.get(msg.method)) handler(msg.params || {});
      }
    };
  });
}

async function evaluate(tab, expression) {
  const ws = await openWs(tab.webSocketDebuggerUrl);
  try {
    const r = await ws.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
    });
    if (r.exceptionDetails) {
      throw new Error("page exception: " + JSON.stringify(r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    }
    return r.result.value;
  } finally {
    ws.close();
  }
}

function sleepReject(ms, message) {
  return new Promise((_, reject) => setTimeout(() => reject(new Error(message)), ms));
}

async function waitForEvent(ws, method, timeoutMs = 5000) {
  return Promise.race([
    new Promise((resolve) => {
      const off = ws.on(method, (params) => {
        off();
        resolve(params);
      });
    }),
    sleepReject(timeoutMs, `CDP event timeout: ${method}`),
  ]);
}

function absoluteFileEvidence(paths) {
  if (!paths.length) throw new Error("at least one absolute file path is required");
  const files = paths.map((p) => {
    if (!p || !/^[A-Za-z]:[\\\\]/.test(p) && !p.startsWith("/")) {
      throw new Error(`file path is not absolute: ${p}`);
    }
    if (!existsSync(p)) throw new Error(`file does not exist: ${p}`);
    const s = statSync(p);
    if (!s.isFile()) throw new Error(`path is not a regular file: ${p}`);
    const canonical = realpathSync(p);
    return { requested_path: p, canonical_path: canonical, bytes: s.size };
  });
  return files;
}

async function clickAddFilesAndIntercept(ws) {
  await ws.send("Page.enable");
  await ws.send("DOM.enable");
  await ws.send("Page.setInterceptFileChooserDialog", { enabled: true });
  try {
    await ws.send("Runtime.evaluate", {
      expression: `(() => {
        const buttons = Array.from(document.querySelectorAll("button"));
        const add = buttons.find((x) => (x.getAttribute("aria-label") || "").trim() === "Add files, connectors, and more");
        if (!add) throw new Error("Add-files button not found");
        add.click();
        const item = Array.from(document.querySelectorAll('[role="menuitem"]'))
          .find((x) => (x.textContent || "").trim().includes("Add files or photos"));
        if (!item) throw new Error("Add files or photos control not found");
        item.click();
        return { clicked_add_files: true, clicked_file_menu: true };
      })()`,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
    });
    const chooser = await waitForEvent(ws, "Page.fileChooserOpened", 5000);
    if (!chooser.backendNodeId) throw new Error("file chooser event missing backendNodeId");
    const node = await ws.send("DOM.describeNode", { backendNodeId: chooser.backendNodeId, depth: 0 });
    const attrs = node.node?.attributes || [];
    const attrMap = {};
    for (let i = 0; i + 1 < attrs.length; i += 2) attrMap[attrs[i]] = attrs[i + 1];
    return {
      chooser,
      input: {
        backend_node_id: chooser.backendNodeId,
        node_name: node.node?.nodeName || null,
        type: attrMap.type || null,
        accept: attrMap.accept || null,
        multiple: Object.prototype.hasOwnProperty.call(attrMap, "multiple"),
      },
    };
  } finally {
    await ws.send("Page.setInterceptFileChooserDialog", { enabled: false }).catch(() => {});
  }
}

async function probeFileInput(tab) {
  const ws = await openWs(tab.webSocketDebuggerUrl);
  try {
    const evidence = await clickAddFilesAndIntercept(ws);
    return {
      target_id: tab.id,
      requested_file_paths: [],
      accepted_file_count: 0,
      mechanism: "CDP Page.setInterceptFileChooserDialog + Page.fileChooserOpened + DOM.describeNode",
      verification: {
        result: "PASS",
        selection_performed: false,
        input_control: evidence.input,
      },
    };
  } finally {
    ws.close();
  }
}

async function uploadFiles(tab, paths) {
  const requested = absoluteFileEvidence(paths);
  const ws = await openWs(tab.webSocketDebuggerUrl);
  try {
    await ws.send("Page.enable");
    await ws.send("DOM.enable");
    await ws.send("Page.setInterceptFileChooserDialog", { enabled: true });
    try {
      await ws.send("Runtime.evaluate", {
        expression: `(() => {
          const buttons = Array.from(document.querySelectorAll("button"));
          const add = buttons.find((x) => (x.getAttribute("aria-label") || "").trim() === "Add files, connectors, and more");
          if (!add) throw new Error("Add-files button not found");
          add.click();
          const item = Array.from(document.querySelectorAll('[role="menuitem"]'))
            .find((x) => (x.textContent || "").trim().includes("Add files or photos"));
          if (!item) throw new Error("Add files or photos control not found");
          item.click();
          return true;
        })()`,
        awaitPromise: true,
        returnByValue: true,
        userGesture: true,
      });
      const chooser = await waitForEvent(ws, "Page.fileChooserOpened", 5000);
      if (!chooser.backendNodeId) throw new Error("file chooser event missing backendNodeId");
      const node = await ws.send("DOM.describeNode", { backendNodeId: chooser.backendNodeId, depth: 0 });
      const attrs = node.node?.attributes || [];
      const attrMap = {};
      for (let i = 0; i + 1 < attrs.length; i += 2) attrMap[attrs[i]] = attrs[i + 1];
      if ((attrMap.type || "").toLowerCase() !== "file") throw new Error("file chooser backend node is not input[type=file]");
      const multiple = Object.prototype.hasOwnProperty.call(attrMap, "multiple");
      if (!multiple && requested.length > 1) throw new Error("Claude file control does not advertise multiple-file selection");
      await ws.send("DOM.setFileInputFiles", {
        backendNodeId: chooser.backendNodeId,
        files: requested.map((x) => x.canonical_path),
      });
      const verify = await ws.send("Runtime.evaluate", {
        expression: `(() => {
          const inputs = Array.from(document.querySelectorAll('input[type="file"]'));
          const input = inputs.find((x) => x.files && x.files.length);
          if (!input) return { found: false, count: 0, files: [] };
          return {
            found: true,
            count: input.files.length,
            files: Array.from(input.files, (f) => ({ name: f.name, size: f.size, type: f.type }))
          };
        })()`,
        awaitPromise: true,
        returnByValue: true,
      });
      const expected = requested.map((x) => ({ name: x.canonical_path.split(/[\\/]/).pop(), size: x.bytes }));
      const actual = (verify.result?.value?.files || []).map((f) => ({ name: f.name, size: f.size }));
      const exact = actual.length === expected.length && expected.every((e, i) => e.name === actual[i].name && e.size === actual[i].size);
      return {
        target_id: tab.id,
        input_control: {
          backend_node_id: chooser.backendNodeId,
          node_name: node.node?.nodeName || null,
          type: attrMap.type || null,
          accept: attrMap.accept || null,
          multiple,
        },
        requested_file_paths: requested,
        accepted_file_count: verify.result?.value?.count || 0,
        mechanism: "CDP DOM.setFileInputFiles via intercepted Page.fileChooserOpened",
        verification: { result: exact ? "PASS" : "FAIL", exact_name_size_match: exact, browser_files: actual },
      };
    } finally {
      await ws.send("Page.setInterceptFileChooserDialog", { enabled: false }).catch(() => {});
    }
  } finally {
    ws.close();
  }
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  tabsSyncCache = await tabs();

  if (cmd === "list") {
    console.log(JSON.stringify(tabsSyncCache.map((t) => ({ id: t.id, url: t.url, title: t.title })), null, 2));
    return;
  }

  if (cmd === "new") {
    const url = rest[0];
    const r = await fetch(`${CDP}/json/new?${encodeURIComponent(url)}`, { method: "PUT" });
    if (!r.ok) throw new Error(`json/new -> ${r.status}`);
    const t = await r.json();
    console.log(JSON.stringify({ id: t.id, url: t.url }));
    return;
  }

  if (cmd === "navigate") {
    const [urlPart, url] = rest;
    const tab = findTab(urlPart);
    const ws = await openWs(tab.webSocketDebuggerUrl);
    try {
      await ws.send("Page.navigate", { url });
      await sleep(1500);
    } finally {
      ws.close();
    }
    tabsSyncCache = await tabs();
    const t = findTab(urlPart);
    console.log(JSON.stringify({ id: t.id, url: t.url }));
    return;
  }

  if (cmd === "eval") {
    const urlPart = rest[0];
    const scriptFile = rest[1];
    const outIdx = rest.indexOf("--out");
    const outFile = outIdx >= 0 ? rest[outIdx + 1] : null;
    const src = readFileSync(scriptFile, "utf8");
    const expression = `(async () => {\n${src}\n})()`;
    const tab = findTab(urlPart);
    const val = await evaluate(tab, expression);
    if (outFile) {
      writeFileSync(outFile, typeof val === "string" ? val : JSON.stringify(val, null, 2) + "\n", "utf8");
      console.log(JSON.stringify({ out: outFile, type: typeof val, bytes: readFileSync(outFile).length }));
    } else {
      console.log(JSON.stringify(val, null, 2));
    }
    return;
  }

  if (cmd === "probe-file-input") {
    const tab = findTab(rest[0]);
    console.log(JSON.stringify(await probeFileInput(tab), null, 2));
    return;
  }

  if (cmd === "upload-files") {
    const tab = findTab(rest[0]);
    console.log(JSON.stringify(await uploadFiles(tab, rest.slice(1)), null, 2));
    return;
  }

  if (cmd === "screenshot") {
    const urlPart = rest[0];
    const outFile = rest[1] || "transport/t0/screenshot.png";
    const tab = findTab(urlPart);
    const ws = await openWs(tab.webSocketDebuggerUrl);
    try {
      const r = await ws.send("Page.captureScreenshot", { format: "png" });
      writeFileSync(outFile, Buffer.from(r.data, "base64"));
      console.log(JSON.stringify({ out: outFile, bytes: readFileSync(outFile).length }));
    } finally {
      ws.close();
    }
    return;
  }

  if (cmd === "halt") {
    const tab = findTab(rest[0]);
    const ws = await openWs(tab.webSocketDebuggerUrl);
    try {
      let termErr = null;
      try { await ws.send("Runtime.terminateExecution"); } catch (e) { termErr = String(e.message || e); }
      await ws.send("Page.reload", { ignoreCache: false });
      await sleep(2500);
      console.log(JSON.stringify({ id: tab.id, terminated: !termErr, termErr }));
    } finally {
      ws.close();
    }
    return;
  }

  console.error("usage: cdp.mjs list|new <url>|navigate <urlPart> <url>|eval <urlPart> <scriptFile> [--out f]|probe-file-input <urlPart>|upload-files <urlPart> <absolutePath> [...]|screenshot <urlPart> [out.png]|halt <urlPart>");
  process.exit(2);
}

main().catch((e) => { console.error(String(e.message || e)); process.exit(1); });
