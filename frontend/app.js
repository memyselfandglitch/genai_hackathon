const $ = (id) => document.getElementById(id);

const SAMPLES = [
  "Create a daily brief for today and protect a deep-work block.",
  "Check my Google Calendar this afternoon and flag conflicts.",
  "Add a follow-up item to my Google Tasks.",
  "What are my open tasks?",
  "List my calendar for today and flag any conflicts.",
  "What did I write in my notes about the board?",
  "Suggest a one-hour slot tomorrow morning for deep work.",
];

function showLoading(on) {
  $("loading").classList.toggle("hidden", !on);
  $("loading").setAttribute("aria-hidden", on ? "false" : "true");
  $("send").disabled = on;
}

function showBanner(message, isError) {
  const el = $("banner");
  if (!message) {
    el.className = "banner hidden";
    el.textContent = "";
    return;
  }
  el.className = "banner" + (isError ? " error" : "");
  el.textContent = message;
}

function setStatusPill(status, isError) {
  const pill = $("statusPill");
  pill.textContent = status || "—";
  pill.className = "pill " + (isError ? "pill-err" : status === "ok" ? "pill-ok" : "pill-idle");
}

async function loadMeta() {
  const host = $("meta");
  try {
    const r = await fetch("/api/meta");
    const m = await r.json();
    const chips = [
      `<span class="chip">Python <code>${escapeHtml(m.python_version)}</code></span>`,
      m.python_ok_for_mcp_sdk
        ? `<span class="chip ok">MCP SDK OK</span>`
        : `<span class="chip bad">Python &lt; 3.10 — MCP SDK N/A</span>`,
      `<span class="chip">${m.mcp_package_installed ? "mcp pkg ✓" : "mcp pkg —"}</span>`,
      `<span class="chip">ADK <code>${escapeHtml(m.adk_app_name)}</code></span>`,
      `<span class="chip">Model <code>${escapeHtml(m.gemini_model)}</code></span>`,
      `<span class="chip">${m.google_workspace_connected ? "Workspace connected" : "Workspace mock mode"}</span>`,
      `<span class="chip">Calendar <code>${escapeHtml(m.google_calendar_mode || "mock")}</code></span>`,
      `<span class="chip">Tasks <code>${escapeHtml(m.google_tasks_mode || "mock")}</code></span>`,
    ];
    host.innerHTML = chips.join("");
  } catch {
    host.innerHTML = `<span class="chip bad">Could not reach /api/meta</span>`;
  }
}

function renderSamples() {
  const wrap = $("samples");
  wrap.innerHTML = SAMPLES.map(
    (q, i) =>
      `<button type="button" class="sample-chip" data-i="${i}">${escapeHtml(q)}</button>`
  ).join("");
  wrap.querySelectorAll(".sample-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      $("query").value = SAMPLES[Number(btn.dataset.i)];
      $("query").focus();
    });
  });
}

function renderActions(actions) {
  if (!actions || !actions.length) {
    return '<p class="placeholder">No tool calls for this turn.</p>';
  }
  return actions
    .map((a) => {
      if (a.type === "function_call") {
        return `<div class="entry call"><span class="badge">Call</span><strong>${escapeHtml(
          a.name || ""
        )}</strong><pre class="json">${escapeHtml(JSON.stringify(a.args || {}, null, 2))}</pre></div>`;
      }
      if (a.type === "function_response") {
        return `<div class="entry response"><span class="badge">Response</span><strong>${escapeHtml(
          a.name || ""
        )}</strong><pre class="json">${escapeHtml(JSON.stringify(a.response || {}, null, 2))}</pre></div>`;
      }
      return `<pre class="json">${escapeHtml(JSON.stringify(a, null, 2))}</pre>`;
    })
    .join("");
}

function renderTrace(trace, debugEnabled) {
  if (!debugEnabled) {
    return '<p class="placeholder">Turn on “Full trace” to see each model event.</p>';
  }
  if (!trace || !trace.length) {
    return '<p class="placeholder">No timeline entries (empty trace).</p>';
  }
  return trace
    .map((t) => {
      if (t.type === "event") {
        return `<div class="entry event"><span class="badge">Event · ${escapeHtml(
          t.author || ""
        )}</span><div class="prose-inline">${escapeHtml(t.text_preview || "")}</div></div>`;
      }
      if (t.type === "function_call") {
        return `<div class="entry call"><span class="badge">Tool</span><strong>${escapeHtml(
          t.name || ""
        )}</strong><pre class="json">${escapeHtml(JSON.stringify(t.args || {}, null, 2))}</pre></div>`;
      }
      if (t.type === "function_response") {
        return `<div class="entry response"><span class="badge">Result</span><strong>${escapeHtml(
          t.name || ""
        )}</strong><pre class="json">${escapeHtml(JSON.stringify(t.response || {}, null, 2))}</pre></div>`;
      }
      return `<pre class="json">${escapeHtml(JSON.stringify(t, null, 2))}</pre>`;
    })
    .join("");
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setResultHtml(html, isEmpty) {
  const el = $("result");
  el.innerHTML = html;
  el.className = "scroll-box prose" + (isEmpty ? " empty-state" : "");
  $("copyResult").disabled = isEmpty;
}

async function runQuery() {
  const userId = $("userId").value.trim() || "demo-user";
  const query = $("query").value.trim();
  const debug = $("debug").checked;
  if (!query) return;

  showBanner("");
  showLoading(true);
  setStatusPill("…", false);
  $("copyResult").disabled = true;

  setResultHtml('<p class="placeholder">Waiting…</p>', true);
  $("actions").innerHTML = '<p class="placeholder">…</p>';
  $("trace").innerHTML = '<p class="placeholder">…</p>';

  const url = new URL("/query", window.location.origin);
  if (debug) url.searchParams.set("debug", "true");

  try {
    const res = await fetch(url.toString(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, query }),
    });

    let data;
    try {
      data = await res.json();
    } catch {
      throw new Error("Response was not JSON");
    }

    const ok = data.status === "ok";
    setStatusPill(data.status || "error", !ok);

    const bodyHtml = [
      `<div class="status-line"><span class="pill ${ok ? "pill-ok" : "pill-err"}">${ok ? "ok" : "error"}</span></div>`,
      `<div class="reply-body">${escapeHtml(data.result || "")}</div>`,
      data.error
        ? `<div class="err-block">${escapeHtml(data.error)}</div>`
        : "",
    ].join("");

    setResultHtml(bodyHtml, !(data.result || data.error));
    $("actions").innerHTML = renderActions(data.actions);
    $("trace").innerHTML = renderTrace(data.trace, debug);

    if (!res.ok) {
      showBanner(`HTTP ${res.status}`, true);
    }
  } catch (e) {
    setStatusPill("error", true);
    showBanner(e instanceof Error ? e.message : "Request failed", true);
    setResultHtml(
      `<p class="placeholder" style="color:var(--err)">Could not reach the API. Is the server running?</p>`,
      false
    );
    $("actions").innerHTML = '<p class="placeholder">—</p>';
    $("trace").innerHTML = '<p class="placeholder">—</p>';
  } finally {
    showLoading(false);
  }
}

function clearAll() {
  $("query").value = "";
  setResultHtml('<p class="placeholder">Run a query to see the orchestrator response.</p>', true);
  $("actions").innerHTML = '<p class="placeholder">No tool calls yet.</p>';
  $("trace").innerHTML = '<p class="placeholder">Enable full trace to see each event.</p>';
  setStatusPill("—", false);
  showBanner("");
  $("copyResult").disabled = true;
}

async function copyResult() {
  const box = $("result");
  const text = box.innerText || "";
  if (!text.trim()) return;
  try {
    await navigator.clipboard.writeText(text);
    const btn = $("copyResult");
    const prev = btn.textContent;
    btn.textContent = "Copied!";
    setTimeout(() => (btn.textContent = prev), 1500);
  } catch {
    /* ignore */
  }
}

$("send").addEventListener("click", runQuery);
$("clear").addEventListener("click", clearAll);
$("copyResult").addEventListener("click", copyResult);
$("query").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
    e.preventDefault();
    runQuery();
  }
});

renderSamples();
loadMeta();
