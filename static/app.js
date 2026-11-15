/* Submask single-page app, no external dependencies. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const api = async (url, opts = {}) => {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
};
const toast = (msg, isErr) => {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "show" + (isErr ? " err" : "");
  setTimeout(() => (el.className = ""), 3600);
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let SCHEMA = null;          // 最新 schema 快照
let INFERRED = [];          // 推断候选
let GRAPH = { nodes: [], edges: [] };
let CONFIG = { rules: {}, masking: {}, settings: {} };

/* ---------------- tabs ---------------- */
$$(".tab").forEach((btn) =>
  btn.addEventListener("click", () => {
    $$(".tab").forEach((b) => b.classList.toggle("active", b === btn));
    $$(".panel").forEach((p) =>
      p.classList.toggle("active", p.id === `tab-${btn.dataset.tab}`));
    if (btn.dataset.tab === "graph") drawGraph();
    if (btn.dataset.tab === "jobs") loadJobs();
  }));

/* ---------------- 数据源 ---------------- */
$("#ds-demo").addEventListener("click", () => {
  // 与 scripts/generate_demo.py 默认输出一致 (相对于服务工作目录)
  $("#ds-path").value = "data/demo_source.db";
});

$("#ds-connect").addEventListener("click", async () => {
  const path = $("#ds-path").value.trim();
  if (!path) return toast("请填写数据库路径", true);
  try {
    SCHEMA = await api("/api/datasource", { method: "POST", body: { path } });
    renderSchema();
    await Promise.all([loadGraph(), loadConfig()]);
    renderRules();
    renderMasking();
    $("#ds-status").textContent =
      `已连接 ${path}，共 ${Object.keys(SCHEMA.tables).length} 张表`;
    toast("数据源连接成功");
  } catch (e) { toast(e.message, true); }
});

function renderSchema() {
  $("#ds-tables-card").hidden = false;
  const tnames = Object.keys(SCHEMA.tables);
  $("#ds-table-count").textContent = `${tnames.length} 表`;
  $("#ds-fk-count").textContent = `${SCHEMA.declared_fks.length} 声明外键`;
  $("#ds-tables tbody").innerHTML = tnames.map((t) => {
    const info = SCHEMA.tables[t];
    const cols = info.columns.map((c) => c.name).join(", ");
    return `<tr><td class="mono">${esc(t)}</td><td>${info.row_count}</td>
      <td class="mono">${esc(info.pk.join(", ") || "—")}</td>
      <td class="wrap-cell" title="${esc(cols)}">${esc(cols)}</td></tr>`;
  }).join("");
}

async function loadSchemaSilent() {
  try { SCHEMA = await api("/api/schema"); } catch { /* 未配置 */ }
}

/* ---------------- 关系图 / 推断 ---------------- */
async function loadGraph() {
  try { GRAPH = await api("/api/graph"); } catch { GRAPH = { nodes: [], edges: [] }; }
  const decl = GRAPH.edges.filter((e) => e.origin === "declared").length;
  const inf = GRAPH.edges.filter((e) => e.origin === "inferred").length;
  $("#graph-declared").textContent = `声明 ${decl}`;
  $("#graph-inferred").textContent = `推断确认 ${inf}`;
}

$("#infer-btn").addEventListener("click", async () => {
  try {
    INFERRED = await api("/api/infer", { method: "POST" });
    renderInference();
    $("#infer-hint").textContent =
      `推断出 ${INFERRED.length} 个候选，勾选后点击“保存勾选结果”`;
  } catch (e) { toast(e.message, true); }
});

$("#confirm-btn").addEventListener("click", async () => {
  const edges = $$("#infer-table tbody input:checked").map((cb) => ({
    table: cb.dataset.table, column: cb.dataset.column,
    ref_table: cb.dataset.refTable, ref_column: cb.dataset.refColumn,
  }));
  try {
    await api("/api/edges/confirm", { method: "POST", body: { edges } });
    await loadGraph();
    drawGraph();
    toast(`已保存 ${edges.length} 条推断外键`);
  } catch (e) { toast(e.message, true); }
});

function renderInference() {
  const confirmedKeys = new Set(
    GRAPH.edges.filter((e) => e.origin === "inferred")
      .map((e) => `${e.table}.${e.column}->${e.ref_table}.${e.ref_column}`));
  $("#infer-table tbody").innerHTML = INFERRED.map((c) => {
    const key = `${c.table}.${c.column}->${c.ref_table}.${c.ref_column}`;
    const cls = c.confidence >= 0.95 ? "hi" : c.confidence >= 0.85 ? "mid" : "lo";
    return `<tr>
      <td><input type="checkbox" data-table="${esc(c.table)}"
        data-column="${esc(c.column)}" data-ref-table="${esc(c.ref_table)}"
        data-ref-column="${esc(c.ref_column)}"
        ${confirmedKeys.has(key) ? "checked" : ""}></td>
      <td class="conf ${cls}">${c.confidence.toFixed(2)}</td>
      <td class="mono">${esc(c.table)}.${esc(c.column)}</td><td>→</td>
      <td class="mono">${esc(c.ref_table)}.${esc(c.ref_column)}</td>
      <td>${c.matched_values}/${c.distinct_values} (${(c.containment * 100).toFixed(0)}%)</td>
      <td>推断</td></tr>`;
  }).join("") || `<tr><td colspan="7" class="hint">先点击“推断未声明外键”</td></tr>`;
}

/* ---------------- 简单力导向布局 + 拖拽 ---------------- */
const SVG_W = 960, SVG_H = 560;
let nodePos = new Map();

function drawGraph() {
  const svg = $("#graph-svg");
  if (!GRAPH.nodes.length) {
    svg.innerHTML = `<text x="20" y="40" class="edge-label">
      暂无关系数据，请先连接数据源并确认推断外键</text>`;
    return;
  }
  // 环形布局初始化
  const n = GRAPH.nodes.length;
  const idx = new Map(GRAPH.nodes.map((t, i) => [t, i]));
  GRAPH.nodes.forEach((t, i) => {
    if (!nodePos.has(t)) {
      const ang = (i / n) * Math.PI * 2;
      nodePos.set(t, {
        x: SVG_W / 2 + Math.cos(ang) * Math.min(380, 40 + n * 7),
        y: SVG_H / 2 + Math.sin(ang) * Math.min(220, 30 + n * 4),
      });
    }
  });
  // 力导向松弛（确定性迭代次数）
  const pos = nodePos;
  const adj = new Map(GRAPH.nodes.map((t) => [t, []]));
  GRAPH.edges.forEach((e) => {
    adj.get(e.table)?.push(e.ref_table);
    adj.get(e.ref_table)?.push(e.table);
  });
  for (let iter = 0; iter < 220; iter++) {
    const force = new Map(GRAPH.nodes.map((t) => [t, { x: 0, y: 0 }]));
    // 斥力
    for (let i = 0; i < GRAPH.nodes.length; i++) {
      for (let j = i + 1; j < GRAPH.nodes.length; j++) {
        const a = pos.get(GRAPH.nodes[i]), b = pos.get(GRAPH.nodes[j]);
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy || 1;
        const f = 2600 / d2;
        const d = Math.sqrt(d2);
        dx /= d; dy /= d;
        force.get(GRAPH.nodes[i]).x += dx * f;
        force.get(GRAPH.nodes[i]).y += dy * f;
        force.get(GRAPH.nodes[j]).x -= dx * f;
        force.get(GRAPH.nodes[j]).y -= dy * f;
      }
    }
    // 弹簧
    GRAPH.edges.forEach((e) => {
      const a = pos.get(e.table), b = pos.get(e.ref_table);
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1;
      const f = (d - 130) * 0.02;
      force.get(e.table).x += dx / d * f;
      force.get(e.table).y += dy / d * f;
      force.get(e.ref_table).x -= dx / d * f;
      force.get(e.ref_table).y -= dy / d * f;
    });
    GRAPH.nodes.forEach((t) => {
      const p = pos.get(t), fv = force.get(t);
      p.x = Math.max(70, Math.min(SVG_W - 70, p.x + fv.x * 0.15));
      p.y = Math.max(36, Math.min(SVG_H - 30, p.y + fv.y * 0.15));
    });
  }

  const inferredTables = new Set(
    GRAPH.edges.filter((e) => e.origin === "inferred").flatMap((e) => [e.table]));
  let html = `<defs><marker id="arrow" markerWidth="9" markerHeight="9"
      refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L8,3 L0,6 Z" fill="#8aa4d6"/></marker></defs>`;
  GRAPH.edges.forEach((e) => {
    const a = pos.get(e.table), b = pos.get(e.ref_table);
    const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
    html += `<path class="edge ${e.origin === "inferred" ? "inferred" : ""}"
      d="M${a.x},${a.y} L${b.x},${b.y}"/>
      <text class="edge-label" x="${mx}" y="${my - 3}">${esc(e.column)}</text>`;
  });
  GRAPH.nodes.forEach((t) => {
    const p = pos.get(t);
    const w = Math.max(78, t.length * 8.5 + 16);
    html += `<g class="node ${inferredTables.has(t) ? "inferred" : ""}"
      data-name="${esc(t)}" transform="translate(${p.x - w / 2},${p.y - 14})">
      <rect width="${w}" height="28" rx="7"></rect>
      <text x="${w / 2}" y="18" text-anchor="middle">${esc(t)}</text></g>`;
  });
  svg.innerHTML = html;
  enableDrag(svg);
}

function enableDrag(svg) {
  let drag = null;
  svg.querySelectorAll(".node").forEach((g) => {
    g.addEventListener("mousedown", (ev) => {
      drag = { name: g.dataset.name, g };
      ev.preventDefault();
    });
  });
  window.addEventListener("mousemove", (ev) => {
    if (!drag) return;
    const rect = svg.getBoundingClientRect();
    const x = (ev.clientX - rect.left) * (SVG_W / rect.width);
    const y = (ev.clientY - rect.top) * (SVG_H / rect.height);
    nodePos.set(drag.name, {
      x: Math.max(70, Math.min(SVG_W - 70, x)),
      y: Math.max(36, Math.min(SVG_H - 30, y)),
    });
    drawGraph();
  });
  window.addEventListener("mouseup", () => (drag = null));
}

/* ---------------- 抽取规则 ---------------- */
async function loadConfig() {
  try { CONFIG = await api("/api/config"); }
  catch { CONFIG = { rules: {}, masking: {}, settings: {} }; }
  $("#date-shift").value = CONFIG.settings.date_shift_days ?? 180;
  $("#salt").value = CONFIG.settings.salt ?? "submask-v1";
}

function renderRules() {
  if (!SCHEMA) return;
  const rules = CONFIG.rules || {};
  $("#rules-table tbody").innerHTML = Object.keys(SCHEMA.tables).map((t) => {
    const r = rules[t] || { mode: "reach", where: "", percent: 100 };
    return `<tr data-table="${esc(t)}">
      <td class="mono">${esc(t)}</td>
      <td><select class="r-mode">
        <option value="reach" ${r.mode === "reach" ? "selected" : ""}>reach 闭包带入</option>
        <option value="seed" ${r.mode === "seed" ? "selected" : ""}>seed 种子条件</option>
        <option value="percent" ${r.mode === "percent" ? "selected" : ""}>percent 比例抽样</option>
      </select></td>
      <td><input class="r-where" type="text" style="min-width:220px"
        placeholder="level_id &gt;= 3 AND status='active'"
        value="${esc(r.where || "")}"></td>
      <td><input class="r-percent" type="number" min="1" max="100"
        value="${r.percent ?? 100}" style="width:90px"></td></tr>`;
  }).join("");
}

$("#save-settings").addEventListener("click", async () => {
  CONFIG.settings = {
    ...(CONFIG.settings || {}),
    date_shift_days: Number($("#date-shift").value || 0),
    salt: $("#salt").value.trim() || "submask-v1",
  };
  try { await api("/api/config", { method: "POST", body: { settings: CONFIG.settings } });
    toast("设置已保存"); } catch (e) { toast(e.message, true); }
});

$("#save-rules").addEventListener("click", async () => {
  const rules = {};
  $$("#rules-table tbody tr").forEach((tr) => {
    rules[tr.dataset.table] = {
      mode: tr.querySelector(".r-mode").value,
      where: tr.querySelector(".r-where").value.trim() || null,
      percent: Number(tr.querySelector(".r-percent").value || 100),
    };
  });
  CONFIG.rules = rules;
  try { await api("/api/config", { method: "POST", body: { rules } });
    toast("抽取规则已保存"); } catch (e) { toast(e.message, true); }
});

/* ---------------- 脱敏策略 ---------------- */
const MASK_STRATEGIES = ["", "name", "phone", "id_card", "bank_card", "email", "date"];
const SENSITIVE_HINT = /name|phone|mobile|id_card|bank|email|receiver|date|time/i;

function renderMasking() {
  if (!SCHEMA) return;
  const masking = CONFIG.masking || {};
  $("#masking-grid").innerHTML = Object.entries(SCHEMA.tables).map(([t, info]) => {
    const sel = masking[t] || {};
    const rows = info.columns
      .filter((c) => SENSITIVE_HINT.test(c.name))
      .map((c) => `<div class="mask-row">
        <span class="mono" title="${esc(c.type)}">${esc(c.name)}</span>
        <select data-table="${esc(t)}" data-column="${esc(c.name)}" class="m-sel">
          ${MASK_STRATEGIES.map((s) =>
            `<option value="${s}" ${sel[c.name] === s ? "selected" : ""}>${s || "不处理"}</option>`
          ).join("")}</select></div>`).join("");
    if (!rows) return "";
    return `<div class="mask-card"><h4 class="mono">${esc(t)}</h4>${rows}</div>`;
  }).join("");
}

$("#save-masking").addEventListener("click", async () => {
  const masking = {};
  $$(".m-sel").forEach((sel) => {
    if (!sel.value) return;
    (masking[sel.dataset.table] ||= {})[sel.dataset.column] = sel.value;
  });
  CONFIG.masking = masking;
  try { await api("/api/config", { method: "POST", body: { masking } });
    toast("脱敏配置已保存"); } catch (e) { toast(e.message, true); }
});

/* ---------------- 作业 ---------------- */
let pollTimer = null;

$("#run-job").addEventListener("click", async () => {
  try {
    const { job_id } = await api("/api/jobs", { method: "POST" });
    $("#job-spin").textContent = `作业 ${job_id} 运行中…`;
    clearInterval(pollTimer);
    pollTimer = setInterval(loadJobs, 1500);
    toast("作业已启动");
  } catch (e) { toast(e.message, true); }
});
$("#refresh-jobs").addEventListener("click", loadJobs);

async function loadJobs() {
  let jobs;
  try { jobs = await api("/api/jobs"); } catch (e) { return; }
  const running = jobs.some((j) => j.status === "running");
  if (!running) { clearInterval(pollTimer); $("#job-spin").textContent = ""; }
  $("#jobs-table tbody").innerHTML = jobs.map((j) => {
    const d = j.detail || {};
    const v = d.validation || {};
    const fk = v.foreign_key_errors ?? "—";
    const fmt = v.format_errors ?? "—";
    return `<tr>
      <td class="mono">${esc(j.job_id)}</td>
      <td>${esc(j.started_at)}</td><td>${esc(j.finished_at || "")}</td>
      <td><span class="pill ${j.status}">${j.status}</span></td>
      <td>${fk}</td><td>${fmt}</td>
      <td>${j.report_path ? `<button class="ghost" data-job="${esc(j.job_id)}">查看报告</button>` : "—"}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="7" class="hint">暂无作业</td></tr>`;
  $$("#jobs-table button[data-job]").forEach((b) =>
    b.addEventListener("click", () => showReport(b.dataset.job)));
}

async function showReport(jobId) {
  try {
    const r = await api(`/api/jobs/${jobId}/report`);
    $("#report-card").hidden = false;
    $("#report-job-id").textContent = r.job_id;
    const v = r.validation;
    const totalRows = r.tables.reduce((s, t) => s + t.extracted_rows, 0);
    const maskCols = Object.values(r.masking).reduce((s, cols) => s + Object.keys(cols).length, 0);
    $("#report-summary").innerHTML = `
      <div class="kpi"><b>${r.tables.length}</b><small>涉及表</small></div>
      <div class="kpi"><b>${totalRows}</b><small>抽取总行数</small></div>
      <div class="kpi"><b>${maskCols}</b><small>脱敏列数</small></div>
      <div class="kpi"><b>${r.date_shift_days}</b><small>日期平移天数</small></div>
      <div class="kpi"><b style="color:${v.zero_error ? "var(--ok)" : "var(--bad)"}">
        ${v.foreign_key_errors + v.format_errors}</b><small>校验错误数</small></div>`;
    $("#report-tables tbody").innerHTML = r.tables.map((t) => `<tr>
      <td class="mono">${esc(t.table)}</td><td>${t.source_rows}</td>
      <td>${t.seed_rows}</td><td>${t.closure_added}</td>
      <td>${t.extracted_rows}</td><td>${t.percent}%</td>
      <td>${t.reached ? '<span class="badge ok">已抽取</span>'
                      : '<span class="badge bad">未可达</span>'}</td></tr>`).join("");
    $("#report-masking tbody").innerHTML = Object.entries(r.masking)
      .flatMap(([t, cols]) => Object.entries(cols).map(([c, m]) =>
        `<tr><td class="mono">${esc(t)}.${esc(c)}</td>
         <td><span class="pill reach">${esc(m.strategy)}</span></td>
         <td>${m.rows_masked}</td><td>${m.distinct_fake_values}</td></tr>`)).join("")
      || `<tr><td colspan="4" class="hint">未配置脱敏</td></tr>`;
    $("#report-validation").textContent = JSON.stringify(v, null, 2);
  } catch (e) { toast(e.message, true); }
}

/* ---------------- 初始化 ---------------- */
(async function init() {
  await loadSchemaSilent();
  await loadConfig();
  if (SCHEMA) {
    renderSchema();
    renderRules();
    renderMasking();
    await loadGraph();
    $("#ds-status").textContent =
      `已加载上次数据源，共 ${Object.keys(SCHEMA.tables).length} 张表`;
  }
  loadJobs();
})();
