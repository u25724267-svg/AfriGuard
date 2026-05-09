"""HTTP status API for monitoring AfriGuard pipeline runs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.config.generation import load_generation_config
from src.config.languages import list_language_names
from src.taxonomy.harm_registry import get_registry
from src.storage.db import (
    AnnotationORM,
    CandidateResponseORM,
    DatasetItemORM,
    GeneratedPromptORM,
    GenerationCostORM,
    PipelineRunORM,
    PipelineStageRunORM,
    SessionLocal,
)

app = FastAPI(title="AfriGuard Pipeline Monitor", version="0.1.0")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AfriGuard Monitor</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b1020;
      --panel: #111827;
      --panel-2: #0f172a;
      --line: #273244;
      --text: #e5edf7;
      --muted: #93a4b8;
      --accent: #38bdf8;
      --accent-2: #22c55e;
      --danger: #fb7185;
    }
    * { box-sizing: border-box; }
    body {
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      margin: 0;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(56,189,248,.12), transparent 32rem),
        linear-gradient(180deg, #0b1020, #0a0f1c);
    }
    main { max-width: 1320px; margin: 0 auto; padding: 28px; }
    h1 { font-size: 28px; margin: 0 0 4px; letter-spacing: 0; }
    h2 { font-size: 16px; margin: 0 0 12px; }
    .topbar { display: flex; justify-content: space-between; align-items: end; gap: 18px; margin-bottom: 18px; }
    .run-controls { display: flex; align-items: end; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .run-controls label { display: grid; gap: 4px; font-size: 12px; color: var(--muted); min-width: 320px; }
    .muted { color: var(--muted); }
    .tabs { display: flex; flex-wrap: wrap; gap: 8px; margin: 20px 0; }
    .tab {
      border: 1px solid var(--line);
      background: rgba(17,24,39,.78);
      color: var(--muted);
      border-radius: 7px;
      padding: 8px 12px;
    }
    .tab.active { color: var(--text); border-color: rgba(56,189,248,.8); background: rgba(56,189,248,.14); }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 18px 0; }
    .card { border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: rgba(17,24,39,.84); box-shadow: 0 8px 28px rgba(0,0,0,.18); }
    .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
    .value { font-size: 22px; font-weight: 700; margin-top: 4px; }
    .bar { height: 14px; border-radius: 999px; background: #1e293b; overflow: hidden; margin: 8px 0 16px; border: 1px solid var(--line); }
    .fill { height: 100%; width: 0%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width .3s ease; }
    .sections { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 18px; margin-top: 18px; }
    .wide { grid-column: 1 / -1; overflow-x: auto; }
    .filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: end; margin: 8px 0 12px; }
    .filters label { display: grid; gap: 4px; font-size: 12px; color: var(--muted); }
    input, select, button {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 10px;
      font: inherit;
      background: #0b1220;
      color: var(--text);
    }
    button { background: #0ea5e9; color: #04111d; border-color: #38bdf8; cursor: pointer; font-weight: 700; }
    .text-cell { min-width: 420px; max-width: 620px; white-space: pre-wrap; line-height: 1.45; }
    details { background: rgba(15,23,42,.8); border: 1px solid var(--line); border-radius: 7px; padding: 8px 10px; }
    summary { cursor: pointer; color: var(--accent); }
    section { min-width: 0; }
    table { width: 100%; border-collapse: collapse; margin-top: 12px; }
    th, td { border-bottom: 1px solid var(--line); padding: 9px; text-align: left; font-size: 13px; vertical-align: top; }
    th { color: #cbd5e1; background: rgba(15,23,42,.9); position: sticky; top: 0; }
    tr:hover td { background: rgba(56,189,248,.045); }
    code { background: #0b1220; border: 1px solid var(--line); padding: 2px 5px; border-radius: 4px; }
    [data-tab-panel] { display: none; }
    [data-tab-panel].active { display: grid; }
  </style>
</head>
<body>
<main>
  <div class="topbar">
    <div>
      <h1>AfriGuard Pipeline Monitor</h1>
      <div class="muted" id="summary">Loading...</div>
    </div>
    <div class="run-controls">
      <label>Run View <select id="run-select"></select></label>
      <button onclick="refresh()">Refresh</button>
      <div class="muted">Auto-refresh: 5s</div>
    </div>
  </div>
  <div class="grid">
    <div class="card"><div class="label">Run Status</div><div class="value" id="status">-</div></div>
    <div class="card"><div class="label">Current Stage</div><div class="value" id="stage">-</div></div>
    <div class="card"><div class="label">Prompts</div><div class="value" id="prompts">-</div></div>
    <div class="card"><div class="label">Candidates</div><div class="value" id="candidates">-</div></div>
    <div class="card"><div class="label">Reviewed</div><div class="value" id="reviewed">-</div></div>
    <div class="card"><div class="label">Dataset Items</div><div class="value" id="dataset-items">-</div></div>
    <div class="card"><div class="label">Cost</div><div class="value" id="cost">-</div></div>
  </div>
  <div class="label">Prompt Progress</div>
  <div class="bar"><div class="fill" id="prompt-fill"></div></div>
  <div class="label">Candidate Progress</div>
  <div class="bar"><div class="fill" id="candidate-fill"></div></div>
  <nav class="tabs">
    <button class="tab active" data-tab="overview">Overview</button>
    <button class="tab" data-tab="breakdowns">Breakdowns</button>
    <button class="tab" data-tab="generated">Generated Content</button>
  </nav>
  <div class="sections active" data-tab-panel="overview">
    <section class="wide">
      <h2>Language Dashboard</h2>
      <table>
        <thead>
          <tr>
            <th>Language</th>
            <th>Prompts</th>
            <th>Prompt %</th>
            <th>Severity</th>
            <th>Categories</th>
            <th>Candidates</th>
            <th>Status</th>
            <th>Response Type</th>
            <th>Models</th>
          </tr>
        </thead>
        <tbody id="language-dashboard"></tbody>
      </table>
    </section>
    <section>
      <h2>Stages</h2>
      <table><thead><tr><th>Stage</th><th>Status</th><th>Attempts</th><th>Completed</th><th>Error</th></tr></thead><tbody id="stages"></tbody></table>
    </section>
  </div>
  <div class="sections" data-tab-panel="breakdowns">
    <section>
      <h2>Prompt Statuses</h2>
      <table><thead><tr><th>Status</th><th>Count</th></tr></thead><tbody id="prompt-statuses"></tbody></table>
    </section>
    <section>
      <h2>Candidate Statuses</h2>
      <table><thead><tr><th>Status</th><th>Count</th></tr></thead><tbody id="candidate-statuses"></tbody></table>
    </section>
    <section>
      <h2>Prompt Languages</h2>
      <table><thead><tr><th>Language</th><th>Count</th></tr></thead><tbody id="prompt-languages"></tbody></table>
    </section>
    <section>
      <h2>Prompt Categories</h2>
      <table><thead><tr><th>Category</th><th>Count</th></tr></thead><tbody id="prompt-categories"></tbody></table>
    </section>
    <section>
      <h2>Candidate Models</h2>
      <table><thead><tr><th>Model</th><th>Count</th></tr></thead><tbody id="candidate-models"></tbody></table>
    </section>
    <section>
      <h2>Response Types</h2>
      <table><thead><tr><th>Type</th><th>Count</th></tr></thead><tbody id="response-types"></tbody></table>
    </section>
    <section>
      <h2>Cost By Model</h2>
      <table><thead><tr><th>Model</th><th>USD</th></tr></thead><tbody id="cost-models"></tbody></table>
    </section>
  </div>
  <div class="sections" data-tab-panel="generated">
    <section class="wide">
      <h2>Recent Prompts</h2>
      <div class="filters">
        <label>Language <select id="prompt-filter-language"></select></label>
        <label>Category <select id="prompt-filter-category"></select></label>
        <label>Severity <select id="prompt-filter-severity"></select></label>
        <label>Limit <input id="prompt-filter-limit" type="number" min="1" max="100" value="10"></label>
        <button onclick="loadGeneratedContent()">Refresh</button>
      </div>
      <table><thead><tr><th>Created</th><th>Run</th><th>Language</th><th>Category</th><th>Severity</th><th>Mode</th><th>Pipeline</th><th>Source</th><th>Model</th><th>Prompt</th></tr></thead><tbody id="recent-prompts"></tbody></table>
    </section>
    <section class="wide">
      <h2>Recent Candidate Responses</h2>
      <div class="filters">
        <label>Language <select id="candidate-filter-language"></select></label>
        <label>Category <select id="candidate-filter-category"></select></label>
        <label>Severity <select id="candidate-filter-severity"></select></label>
        <label>Status <select id="candidate-filter-status"></select></label>
        <label>Type <select id="candidate-filter-type"></select></label>
        <label>Limit <input id="candidate-filter-limit" type="number" min="1" max="100" value="10"></label>
        <button onclick="loadGeneratedContent()">Refresh</button>
      </div>
      <table><thead><tr><th>Created</th><th>Run</th><th>Language</th><th>Category</th><th>Severity</th><th>Type</th><th>Status</th><th>Model</th><th>Response</th></tr></thead><tbody id="recent-candidates"></tbody></table>
    </section>
  </div>
  <p class="muted">JSON API: <code>/api/runs/latest</code>, <code>/api/runs/&lt;run_id&gt;/prompts</code>, or <code>/api/runs/&lt;run_id&gt;/candidates</code>. Refreshes every 5 seconds.</p>
</main>
<script>
document.querySelectorAll('.tab').forEach(button => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('[data-tab-panel]').forEach(panel => panel.classList.remove('active'));
    button.classList.add('active');
    document.querySelector(`[data-tab-panel="${button.dataset.tab}"]`)?.classList.add('active');
  });
});

let metadataLoaded = false;

async function refresh() {
  if (!metadataLoaded) await loadMetadata();
  else await loadRuns();
  const selected = value('run-select') || 'latest';
  const endpoint = selected === 'all' ? '/api/runs/all' : selected === 'latest' ? '/api/runs/latest' : `/api/runs/${encodeURIComponent(selected)}`;
  const res = await fetch(endpoint);
  const data = await res.json();
  document.getElementById('summary').textContent = `${data.run_id === 'all' ? 'All runs' : `Run ${data.run_id}`} | updated ${data.updated_at || '-'}`;
  document.getElementById('status').textContent = data.status || '-';
  document.getElementById('stage').textContent = data.current_stage || 'none';
  document.getElementById('prompts').textContent = `${data.prompts.generated}/${data.prompts.target}`;
  document.getElementById('candidates').textContent = `${data.candidates.generated}/${data.candidates.target}`;
  document.getElementById('reviewed').textContent = `${data.review.annotations_total}`;
  document.getElementById('dataset-items').textContent = `${data.dataset_items.total}`;
  document.getElementById('cost').textContent = `$${data.cost.total_usd.toFixed(4)}`;
  document.getElementById('prompt-fill').style.width = `${data.prompts.percent}%`;
  document.getElementById('candidate-fill').style.width = `${data.candidates.percent}%`;
  document.getElementById('stages').innerHTML = data.stages.map(s =>
    `<tr><td>${s.stage_name}</td><td>${s.status}</td><td>${s.attempts}</td><td>${s.completed_at || '-'}</td><td>${s.error || ''}</td></tr>`
  ).join('');
  document.getElementById('candidate-statuses').innerHTML = Object.entries(data.candidates.by_status).map(([k,v]) =>
    `<tr><td>${k}</td><td>${v}</td></tr>`
  ).join('');
  document.getElementById('language-dashboard').innerHTML = languageRows(data.by_language_detail);
  document.getElementById('prompt-statuses').innerHTML = tableRows(data.prompts.by_status);
  document.getElementById('prompt-languages').innerHTML = tableRows(data.prompts.by_language);
  document.getElementById('prompt-categories').innerHTML = tableRows(data.prompts.by_harm_category_labeled);
  document.getElementById('candidate-models').innerHTML = tableRows(data.candidates.by_model);
  document.getElementById('response-types').innerHTML = tableRows(data.candidates.by_response_type);
  document.getElementById('cost-models').innerHTML = tableRows(data.cost.by_model);
  window.currentRunId = data.run_id;
  window.contentRunId = selected === 'latest' ? data.run_id : selected;
  loadGeneratedContent();
}
function tableRows(obj) {
  const entries = Object.entries(obj || {}).sort((a, b) => String(a[0]).localeCompare(String(b[0])));
  if (!entries.length) return '<tr><td colspan="2">None yet</td></tr>';
  return entries.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
}
function compactCounts(obj) {
  const entries = Object.entries(obj || {}).sort((a, b) => String(a[0]).localeCompare(String(b[0])));
  if (!entries.length) return '-';
  return entries.map(([k, v]) => `${k}: ${v}`).join(', ');
}
function languageRows(rows) {
  if (!rows || !rows.length) return '<tr><td colspan="9">None yet</td></tr>';
  return rows.map(row => `
    <tr>
      <td>${row.language}</td>
      <td>${row.prompts.generated}/${row.prompts.target}</td>
      <td>${row.prompts.percent}%</td>
      <td>${compactCounts(row.prompts.by_severity_labeled)}</td>
      <td>${compactCounts(row.prompts.by_harm_category_labeled)}</td>
      <td>${row.candidates.generated}/${row.candidates.target}</td>
      <td>${compactCounts(row.candidates.by_status)}</td>
      <td>${compactCounts(row.candidates.by_response_type)}</td>
      <td>${compactCounts(row.candidates.by_model)}</td>
    </tr>
  `).join('');
}
async function loadMetadata() {
  const res = await fetch('/api/metadata');
  const meta = await res.json();
  await loadRuns();
  fillSelect('prompt-filter-language', meta.languages, 'All languages');
  fillSelect('candidate-filter-language', meta.languages, 'All languages');
  fillSelect('prompt-filter-category', meta.categories, 'All categories');
  fillSelect('candidate-filter-category', meta.categories, 'All categories');
  fillSelect('prompt-filter-severity', meta.severities, 'All severities');
  fillSelect('candidate-filter-severity', meta.severities, 'All severities');
  fillSelect('candidate-filter-status', meta.candidate_statuses, 'All statuses');
  fillSelect('candidate-filter-type', meta.response_types, 'All types');
  metadataLoaded = true;
}
async function loadRuns() {
  const res = await fetch('/api/runs');
  const data = await res.json();
  const select = document.getElementById('run-select');
  const previous = select.value || 'latest';
  const runOptions = (data.runs || []).map(run => {
    const promptText = run.prompt_rows ? ` | ${run.prompt_rows} prompts` : '';
    const candidateText = run.candidate_rows ? ` | ${run.candidate_rows} candidates` : '';
    return `<option value="${escapeAttr(run.run_id)}">${escapeHtml(run.run_id)} (${escapeHtml(run.status || 'untracked')}${promptText}${candidateText})</option>`;
  }).join('');
  select.innerHTML = `
    <option value="latest">Latest run</option>
    <option value="all">All runs</option>
    ${runOptions}
  `;
  select.value = [...select.options].some(option => option.value === previous) ? previous : 'latest';
  select.onchange = () => refresh();
}
function fillSelect(id, options, allLabel) {
  const select = document.getElementById(id);
  if (!select) return;
  select.innerHTML = `<option value="">${allLabel}</option>` + (options || []).map(option => {
    const value = option.value ?? option;
    const label = option.label ?? option;
    return `<option value="${escapeAttr(value)}">${escapeHtml(label)}</option>`;
  }).join('');
}
function value(id) {
  return (document.getElementById(id)?.value || '').trim();
}
function params(prefix) {
  const p = new URLSearchParams();
  const language = value(`${prefix}-filter-language`);
  const category = value(`${prefix}-filter-category`);
  const severity = value(`${prefix}-filter-severity`);
  const limit = value(`${prefix}-filter-limit`);
  if (language) p.set('language', language);
  if (category) p.set('harm_category', category);
  if (severity) p.set('severity', severity);
  if (limit) p.set('limit', limit);
  if (prefix === 'candidate') {
    const status = value('candidate-filter-status');
    const type = value('candidate-filter-type');
    if (status) p.set('status', status);
    if (type) p.set('response_type', type);
  }
  return p.toString();
}
function shortText(text) {
  if (!text) return '';
  return text.length > 360 ? `${text.slice(0, 360)}...` : text;
}
function expandableText(text) {
  const safe = escapeHtml(text || '');
  if (!text || text.length <= 360) return safe;
  return `<details><summary>${escapeHtml(text.slice(0, 220))}...</summary><div>${safe}</div></details>`;
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
}
function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, '&#96;');
}
function sourceCell(item) {
  if (!item.source_dataset) return '-';
  const label = `${item.source_dataset}:${item.source_prompt_id || '-'}`;
  if (!item.source_prompt_text) return escapeHtml(label);
  return `<details><summary>${escapeHtml(label)}</summary><div class="text-cell">${escapeHtml(item.source_prompt_text)}</div></details>`;
}
async function loadGeneratedContent() {
  if (!window.contentRunId) return;
  const promptQuery = params('prompt');
  const candidateQuery = params('candidate');
  const [promptRes, candidateRes] = await Promise.all([
    fetch(`/api/runs/${encodeURIComponent(window.contentRunId)}/prompts?${promptQuery}`),
    fetch(`/api/runs/${encodeURIComponent(window.contentRunId)}/candidates?${candidateQuery}`),
  ]);
  const prompts = await promptRes.json();
  const candidates = await candidateRes.json();
  document.getElementById('recent-prompts').innerHTML = (prompts.items || []).map(item => `
    <tr>
      <td>${item.created_at || '-'}</td>
      <td><code>${escapeHtml(item.run_id)}</code></td>
      <td>${item.language}</td>
      <td>${item.harm_category_label}</td>
      <td>${item.severity_label}</td>
      <td>${item.generation_mode || 'native'}</td>
      <td>${item.prompt_pipeline || '-'}</td>
      <td>${sourceCell(item)}</td>
      <td>${item.model_used}</td>
      <td class="text-cell">${expandableText(item.prompt_text)}</td>
    </tr>
  `).join('') || '<tr><td colspan="10">None yet</td></tr>';
  document.getElementById('recent-candidates').innerHTML = (candidates.items || []).map(item => `
    <tr>
      <td>${item.created_at || '-'}</td>
      <td><code>${escapeHtml(item.run_id)}</code></td>
      <td>${item.language}</td>
      <td>${item.harm_category_label}</td>
      <td>${item.severity_label}</td>
      <td>${item.response_type}</td>
      <td>${item.status}</td>
      <td>${item.model_used}</td>
      <td class="text-cell">${expandableText(item.response_text)}</td>
    </tr>
  `).join('') || '<tr><td colspan="9">None yet</td></tr>';
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


@app.get("/api/runs/latest")
def latest_run(db: Session = Depends(get_db)) -> dict[str, Any]:
    run = (
        db.query(PipelineRunORM)
        .order_by(PipelineRunORM.updated_at.desc())
        .first()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="No pipeline runs found")
    return _run_status(db, run)


@app.get("/api/runs")
def list_runs(limit: int = Query(default=30, ge=1, le=200), db: Session = Depends(get_db)) -> dict[str, Any]:
    prompt_counts = dict(
        db.query(GeneratedPromptORM.run_id, func.count(GeneratedPromptORM.id))
        .group_by(GeneratedPromptORM.run_id)
        .all()
    )
    candidate_counts = dict(
        db.query(CandidateResponseORM.run_id, func.count(CandidateResponseORM.id))
        .group_by(CandidateResponseORM.run_id)
        .all()
    )
    known_run_ids = set(prompt_counts) | set(candidate_counts)

    runs = (
        db.query(PipelineRunORM)
        .order_by(PipelineRunORM.updated_at.desc())
        .limit(limit)
        .all()
    )
    items = []
    seen = set()
    for run in runs:
        seen.add(run.id)
        items.append(
            {
                "run_id": run.id,
                "status": run.status,
                "current_stage": run.current_stage,
                "updated_at": _iso(run.updated_at),
                "prompt_rows": int(prompt_counts.get(run.id, 0) or 0),
                "candidate_rows": int(candidate_counts.get(run.id, 0) or 0),
            }
        )

    for run_id in sorted(known_run_ids - seen):
        items.append(
            {
                "run_id": run_id,
                "status": "untracked",
                "current_stage": None,
                "updated_at": None,
                "prompt_rows": int(prompt_counts.get(run_id, 0) or 0),
                "candidate_rows": int(candidate_counts.get(run_id, 0) or 0),
            }
        )

    return {"runs": items[:limit]}


@app.get("/api/runs/all")
def all_runs_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    return _all_runs_status(db)


@app.get("/api/runs/{run_id}")
def run_status(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = db.get(PipelineRunORM, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No pipeline run found for {run_id}")
    return _run_status(db, run)


@app.get("/api/metadata")
def metadata() -> dict[str, Any]:
    registry = get_registry()
    return {
        "languages": [
            {"value": language, "label": language.replace("_", " ").title()}
            for language in list_language_names()
        ],
        "categories": [
            {"value": category.id, "label": f"{category.id} - {category.name}"}
            for category in registry.list_categories()
        ],
        "severities": [
            {"value": registry.get_severity(code).code, "label": f"{code} - {registry.get_severity(code).name}"}
            for code in registry.list_severity_codes()
        ],
        "candidate_statuses": [
            "raw",
            "passed_filter",
            "filtered_language",
            "filtered_quality",
            "filtered_similarity",
            "filtered_duplicate",
            "sampled_for_review",
            "approved",
            "rejected",
            "flagged",
        ],
        "response_types": ["safe", "unsafe"],
    }


@app.get("/api/runs/{run_id}/prompts")
def run_prompts(
    run_id: str,
    language: str | None = None,
    harm_category: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if run_id != "all":
        _require_or_content(db, run_id)
    query = db.query(GeneratedPromptORM)
    if run_id != "all":
        query = query.filter(GeneratedPromptORM.run_id == run_id)
    if language:
        query = query.filter(GeneratedPromptORM.language == language)
    if harm_category:
        query = query.filter(GeneratedPromptORM.harm_category == harm_category)
    if severity:
        query = query.filter(GeneratedPromptORM.severity == severity)
    if status:
        query = query.filter(GeneratedPromptORM.status == status)

    rows = query.order_by(GeneratedPromptORM.created_at.desc()).limit(limit).all()
    return {
        "run_id": run_id,
        "count": len(rows),
        "items": [_prompt_record(row) for row in rows],
    }


@app.get("/api/runs/{run_id}/candidates")
def run_candidates(
    run_id: str,
    language: str | None = None,
    harm_category: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    response_type: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if run_id != "all":
        _require_or_content(db, run_id)
    query = db.query(CandidateResponseORM)
    if run_id != "all":
        query = query.filter(CandidateResponseORM.run_id == run_id)
    if language:
        query = query.filter(CandidateResponseORM.language == language)
    if harm_category:
        query = query.filter(CandidateResponseORM.harm_category == harm_category)
    if severity:
        query = query.filter(CandidateResponseORM.severity == severity)
    if status:
        query = query.filter(CandidateResponseORM.status == status)
    if response_type:
        query = query.filter(CandidateResponseORM.response_type == response_type)

    rows = query.order_by(CandidateResponseORM.created_at.desc()).limit(limit).all()
    return {
        "run_id": run_id,
        "count": len(rows),
        "items": [_candidate_record(row) for row in rows],
    }


def _run_status(db: Session, run: PipelineRunORM) -> dict[str, Any]:
    metadata = dict(run.metadata_ or {})
    prompt_only = bool(metadata.get("prompt_only"))
    target_prompts = _target_prompt_count(run)
    prompt_rows = _count_prompt_rows(db, run.id)
    generated_prompts = prompt_rows if prompt_only else _count_prompts(db, run.id)
    generated_candidates = _count_candidates(db, run.id)
    target_candidates = target_prompts * load_generation_config().candidates_per_prompt
    total_cost = _total_cost(db, run.id)

    return {
        "run_id": run.id,
        "status": run.status,
        "current_stage": run.current_stage,
        "language": run.requested_language or "all",
        "version": run.dataset_version,
        "n_prompts": run.n_prompts,
        "started_at": _iso(run.started_at),
        "updated_at": _iso(run.updated_at),
        "age_seconds": _age_seconds(run.started_at),
        "prompts": {
            "rows": prompt_rows,
            "generated": generated_prompts,
            "pending_or_failed": max(0, prompt_rows - generated_prompts),
            "target": target_prompts,
            "percent": _percent(generated_prompts, target_prompts),
            "by_status": _group_count(db, GeneratedPromptORM.status, GeneratedPromptORM.run_id == run.id),
            "by_language": _group_count(db, GeneratedPromptORM.language, GeneratedPromptORM.run_id == run.id),
            "by_harm_category": _group_count(db, GeneratedPromptORM.harm_category, GeneratedPromptORM.run_id == run.id),
            "by_harm_category_labeled": _labeled_category_counts(
                _group_count(db, GeneratedPromptORM.harm_category, GeneratedPromptORM.run_id == run.id)
            ),
            "by_severity": _group_count(db, GeneratedPromptORM.severity, GeneratedPromptORM.run_id == run.id),
            "by_severity_labeled": _labeled_severity_counts(
                _group_count(db, GeneratedPromptORM.severity, GeneratedPromptORM.run_id == run.id)
            ),
            "by_model": _group_count(db, GeneratedPromptORM.model_used, GeneratedPromptORM.run_id == run.id),
        },
        "candidates": {
            "generated": generated_candidates,
            "target": target_candidates,
            "percent": _percent(generated_candidates, target_candidates),
            "by_status": _group_count(db, CandidateResponseORM.status, CandidateResponseORM.run_id == run.id),
            "by_language": _group_count(db, CandidateResponseORM.language, CandidateResponseORM.run_id == run.id),
            "by_harm_category": _group_count(db, CandidateResponseORM.harm_category, CandidateResponseORM.run_id == run.id),
            "by_harm_category_labeled": _labeled_category_counts(
                _group_count(db, CandidateResponseORM.harm_category, CandidateResponseORM.run_id == run.id)
            ),
            "by_severity": _group_count(db, CandidateResponseORM.severity, CandidateResponseORM.run_id == run.id),
            "by_severity_labeled": _labeled_severity_counts(
                _group_count(db, CandidateResponseORM.severity, CandidateResponseORM.run_id == run.id)
            ),
            "by_response_type": _group_count(db, CandidateResponseORM.response_type, CandidateResponseORM.run_id == run.id),
            "by_model": _group_count(db, CandidateResponseORM.model_used, CandidateResponseORM.run_id == run.id),
        },
        "cost": {
            "total_usd": total_cost,
            "by_model": _cost_by_model(db, run.id),
            "calls_by_job_type": _group_count(db, GenerationCostORM.job_type, GenerationCostORM.run_id == run.id),
            "tokens": _token_totals(db, run.id),
        },
        "review": _review_stats(db, run.id),
        "dataset_items": _dataset_item_stats(db, run.id),
        "by_language_detail": _language_detail(db, run),
        "prompt_matrix": _prompt_matrix(db, run.id),
        "candidate_matrix": _candidate_matrix(db, run.id),
        "stages": _stages(db, run.id),
        "error": run.error,
    }


def _all_runs_status(db: Session) -> dict[str, Any]:
    latest_updated = db.query(func.max(PipelineRunORM.updated_at)).scalar()
    prompt_rows = int(db.query(func.count(GeneratedPromptORM.id)).scalar() or 0)
    generated_candidates = int(db.query(func.count(CandidateResponseORM.id)).scalar() or 0)
    target_prompts = sum(_target_prompt_count(db_run) for db_run in db.query(PipelineRunORM).all())
    target_prompts = max(target_prompts, prompt_rows)
    target_candidates = max(generated_candidates, target_prompts * load_generation_config().candidates_per_prompt)

    return {
        "run_id": "all",
        "status": "aggregate",
        "current_stage": "all",
        "language": "all",
        "version": None,
        "n_prompts": None,
        "started_at": None,
        "updated_at": _iso(latest_updated),
        "age_seconds": None,
        "prompts": {
            "rows": prompt_rows,
            "generated": prompt_rows,
            "pending_or_failed": 0,
            "target": target_prompts,
            "percent": _percent(prompt_rows, target_prompts),
            "by_status": _group_count(db, GeneratedPromptORM.status),
            "by_language": _group_count(db, GeneratedPromptORM.language),
            "by_harm_category": _group_count(db, GeneratedPromptORM.harm_category),
            "by_harm_category_labeled": _labeled_category_counts(_group_count(db, GeneratedPromptORM.harm_category)),
            "by_severity": _group_count(db, GeneratedPromptORM.severity),
            "by_severity_labeled": _labeled_severity_counts(_group_count(db, GeneratedPromptORM.severity)),
            "by_model": _group_count(db, GeneratedPromptORM.model_used),
        },
        "candidates": {
            "generated": generated_candidates,
            "target": target_candidates,
            "percent": _percent(generated_candidates, target_candidates),
            "by_status": _group_count(db, CandidateResponseORM.status),
            "by_language": _group_count(db, CandidateResponseORM.language),
            "by_harm_category": _group_count(db, CandidateResponseORM.harm_category),
            "by_harm_category_labeled": _labeled_category_counts(_group_count(db, CandidateResponseORM.harm_category)),
            "by_severity": _group_count(db, CandidateResponseORM.severity),
            "by_severity_labeled": _labeled_severity_counts(_group_count(db, CandidateResponseORM.severity)),
            "by_response_type": _group_count(db, CandidateResponseORM.response_type),
            "by_model": _group_count(db, CandidateResponseORM.model_used),
        },
        "cost": {
            "total_usd": _total_cost(db),
            "by_model": _cost_by_model(db),
            "calls_by_job_type": _group_count(db, GenerationCostORM.job_type),
            "tokens": _token_totals(db),
        },
        "review": _review_stats(db),
        "dataset_items": _dataset_item_stats(db),
        "by_language_detail": _all_language_detail(db),
        "prompt_matrix": [],
        "candidate_matrix": [],
        "stages": [],
        "error": None,
    }


def _require_run(db: Session, run_id: str) -> PipelineRunORM:
    run = db.get(PipelineRunORM, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No pipeline run found for {run_id}")
    return run


def _require_or_content(db: Session, run_id: str) -> None:
    if db.get(PipelineRunORM, run_id):
        return
    prompt_exists = (
        db.query(GeneratedPromptORM.id)
        .filter(GeneratedPromptORM.run_id == run_id)
        .first()
    )
    if prompt_exists:
        return
    candidate_exists = (
        db.query(CandidateResponseORM.id)
        .filter(CandidateResponseORM.run_id == run_id)
        .first()
    )
    if candidate_exists:
        return
    raise HTTPException(status_code=404, detail=f"No run content found for {run_id}")


def _prompt_record(row: GeneratedPromptORM) -> dict[str, Any]:
    params = row.generation_params or {}
    return {
        "id": row.id,
        "language": row.language,
        "language_code": row.language_code,
        "harm_category": row.harm_category,
        "harm_category_label": _category_label(row.harm_category),
        "harm_category_name": row.harm_category_name,
        "severity": row.severity,
        "severity_label": _severity_label(row.severity),
        "subcategory": row.subcategory,
        "prompt_text": row.prompt_text,
        "status": row.status,
        "model_used": row.model_used,
        "generation_mode": params.get("generation_mode", "native"),
        "prompt_pipeline": params.get("prompt_pipeline"),
        "response_strategy": params.get("response_strategy"),
        "prompt_only": params.get("prompt_only"),
        "source_dataset": params.get("source_dataset"),
        "source_split": params.get("source_split"),
        "source_prompt_id": params.get("source_prompt_id"),
        "source_prompt_hash": params.get("source_prompt_hash"),
        "source_prompt_text": params.get("source_prompt_text"),
        "source_license": params.get("source_license"),
        "adaptation_method": params.get("adaptation_method"),
        "generation_params": params,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "cost_usd": row.cost_usd,
        "created_at": _iso(row.created_at),
        "run_id": row.run_id,
    }


def _candidate_record(row: CandidateResponseORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "prompt_id": row.prompt_id,
        "language": row.language,
        "language_code": row.language_code,
        "harm_category": row.harm_category,
        "harm_category_label": _category_label(row.harm_category),
        "severity": row.severity,
        "severity_label": _severity_label(row.severity),
        "candidate_index": row.candidate_index,
        "response_text": row.response_text,
        "response_type": row.response_type,
        "detected_language": row.detected_language,
        "language_score": row.language_score,
        "quality_score": row.quality_score,
        "similarity_score": row.similarity_score,
        "status": row.status,
        "filter_reason": row.filter_reason,
        "model_used": row.model_used,
        "generation_params": row.generation_params or {},
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "cost_usd": row.cost_usd,
        "created_at": _iso(row.created_at),
        "run_id": row.run_id,
    }


def _target_prompt_count(run: PipelineRunORM) -> int:
    metadata = dict(run.metadata_ or {})
    explicit_target = metadata.get("target_prompt_count")
    if explicit_target is not None:
        try:
            return int(explicit_target)
        except (TypeError, ValueError):
            pass

    n_prompts = run.n_prompts or 0
    if n_prompts <= 0:
        return 0

    languages = [run.requested_language] if run.requested_language else metadata.get("languages")
    if not languages:
        languages = list_language_names()
    categories = metadata.get("categories") or _active_harm_categories()
    severities = metadata.get("severities") or ["S1", "S2", "S3", "S4"]
    return len(languages) * len(categories) * len(severities) * n_prompts


def _active_harm_categories() -> list[str]:
    config_path = Path(__file__).resolve().parents[2] / "configs" / "pipeline.yaml"
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return list(data.get("active_harm_categories", []))


def _count_prompts(db: Session, run_id: str) -> int:
    return int(
        db.query(func.count(GeneratedPromptORM.id))
        .filter(GeneratedPromptORM.run_id == run_id, GeneratedPromptORM.status == "generated")
        .scalar()
        or 0
    )


def _count_prompt_rows(db: Session, run_id: str) -> int:
    return int(
        db.query(func.count(GeneratedPromptORM.id))
        .filter(GeneratedPromptORM.run_id == run_id)
        .scalar()
        or 0
    )


def _count_candidates(db: Session, run_id: str) -> int:
    return int(
        db.query(func.count(CandidateResponseORM.id))
        .filter(CandidateResponseORM.run_id == run_id)
        .scalar()
        or 0
    )


def _group_count(db: Session, column, criterion=None) -> dict[str, int]:
    query = db.query(column, func.count())
    if criterion is not None:
        query = query.filter(criterion)
    rows = query.group_by(column).all()
    return {str(key or "unknown"): int(count or 0) for key, count in rows}


def _total_cost(db: Session, run_id: str | None = None) -> float:
    query = db.query(func.sum(GenerationCostORM.cost_usd))
    if run_id is not None:
        query = query.filter(GenerationCostORM.run_id == run_id)
    total = query.scalar()
    return round(float(total or 0.0), 6)


def _cost_by_model(db: Session, run_id: str | None = None) -> dict[str, float]:
    query = db.query(GenerationCostORM.model_id, func.sum(GenerationCostORM.cost_usd))
    if run_id is not None:
        query = query.filter(GenerationCostORM.run_id == run_id)
    rows = query.group_by(GenerationCostORM.model_id).all()
    return {str(model or "unknown"): round(float(cost or 0.0), 6) for model, cost in rows}


def _token_totals(db: Session, run_id: str | None = None) -> dict[str, int]:
    query = db.query(
        func.sum(GenerationCostORM.prompt_tokens),
        func.sum(GenerationCostORM.completion_tokens),
        func.count(GenerationCostORM.id),
    )
    if run_id is not None:
        query = query.filter(GenerationCostORM.run_id == run_id)
    row = query.one()
    input_tokens = int(row[0] or 0)
    output_tokens = int(row[1] or 0)
    return {
        "input": input_tokens,
        "output": output_tokens,
        "total": input_tokens + output_tokens,
        "api_calls": int(row[2] or 0),
    }


def _review_stats(db: Session, run_id: str | None = None) -> dict[str, Any]:
    query = (
        db.query(AnnotationORM)
        .join(CandidateResponseORM, AnnotationORM.candidate_id == CandidateResponseORM.id)
    )
    if run_id is not None:
        query = query.filter(CandidateResponseORM.run_id == run_id)
    decision_criteria = [AnnotationORM.candidate_id == CandidateResponseORM.id]
    language_criteria = [AnnotationORM.candidate_id == CandidateResponseORM.id]
    if run_id is not None:
        decision_criteria.append(CandidateResponseORM.run_id == run_id)
        language_criteria.append(CandidateResponseORM.run_id == run_id)
    return {
        "annotations_total": int(query.count() or 0),
        "by_decision": _joined_group_count(
            db,
            AnnotationORM.decision,
            *decision_criteria,
        ),
        "by_language": _joined_group_count(
            db,
            AnnotationORM.language,
            *language_criteria,
        ),
    }


def _dataset_item_stats(db: Session, run_id: str | None = None) -> dict[str, Any]:
    criterion = DatasetItemORM.run_id == run_id if run_id is not None else None
    total_query = db.query(func.count(DatasetItemORM.id))
    if criterion is not None:
        total_query = total_query.filter(criterion)
    total = int(total_query.scalar() or 0)
    return {
        "total": total,
        "by_type": _group_count(db, DatasetItemORM.item_type, criterion),
        "by_language": _group_count(db, DatasetItemORM.language, criterion),
    }


def _language_detail(db: Session, run: PipelineRunORM) -> list[dict[str, Any]]:
    languages = [run.requested_language] if run.requested_language else list_language_names()
    categories = _active_harm_categories()
    severities = ["S1", "S2", "S3", "S4"]
    prompt_target = len(categories) * len(severities) * (run.n_prompts or 0)
    candidate_target = prompt_target * load_generation_config().candidates_per_prompt

    rows: list[dict[str, Any]] = []
    for language in languages:
        prompt_criterion = (
            (GeneratedPromptORM.run_id == run.id)
            & (GeneratedPromptORM.language == language)
        )
        candidate_criterion = (
            (CandidateResponseORM.run_id == run.id)
            & (CandidateResponseORM.language == language)
        )
        prompt_generated = int(
            db.query(func.count(GeneratedPromptORM.id))
            .filter(prompt_criterion, GeneratedPromptORM.status == "generated")
            .scalar()
            or 0
        )
        candidate_generated = int(
            db.query(func.count(CandidateResponseORM.id))
            .filter(candidate_criterion)
            .scalar()
            or 0
        )
        rows.append(
            {
                "language": language,
                "prompts": {
                    "generated": prompt_generated,
                    "target": prompt_target,
                    "percent": _percent(prompt_generated, prompt_target),
                    "by_status": _group_count(db, GeneratedPromptORM.status, prompt_criterion),
                    "by_harm_category": _group_count(db, GeneratedPromptORM.harm_category, prompt_criterion),
                    "by_harm_category_labeled": _labeled_category_counts(
                        _group_count(db, GeneratedPromptORM.harm_category, prompt_criterion)
                    ),
                    "by_severity": _group_count(db, GeneratedPromptORM.severity, prompt_criterion),
                    "by_severity_labeled": _labeled_severity_counts(
                        _group_count(db, GeneratedPromptORM.severity, prompt_criterion)
                    ),
                    "by_model": _group_count(db, GeneratedPromptORM.model_used, prompt_criterion),
                },
                "candidates": {
                    "generated": candidate_generated,
                    "target": candidate_target,
                    "percent": _percent(candidate_generated, candidate_target),
                    "by_status": _group_count(db, CandidateResponseORM.status, candidate_criterion),
                    "by_harm_category": _group_count(db, CandidateResponseORM.harm_category, candidate_criterion),
                    "by_harm_category_labeled": _labeled_category_counts(
                        _group_count(db, CandidateResponseORM.harm_category, candidate_criterion)
                    ),
                    "by_severity": _group_count(db, CandidateResponseORM.severity, candidate_criterion),
                    "by_severity_labeled": _labeled_severity_counts(
                        _group_count(db, CandidateResponseORM.severity, candidate_criterion)
                    ),
                    "by_response_type": _group_count(db, CandidateResponseORM.response_type, candidate_criterion),
                    "by_model": _group_count(db, CandidateResponseORM.model_used, candidate_criterion),
                },
            }
        )
    return rows


def _all_language_detail(db: Session) -> list[dict[str, Any]]:
    prompt_languages = {
        row[0]
        for row in db.query(GeneratedPromptORM.language).distinct().all()
        if row[0]
    }
    candidate_languages = {
        row[0]
        for row in db.query(CandidateResponseORM.language).distinct().all()
        if row[0]
    }
    rows: list[dict[str, Any]] = []
    for language in sorted(prompt_languages | candidate_languages):
        prompt_criterion = GeneratedPromptORM.language == language
        candidate_criterion = CandidateResponseORM.language == language
        prompt_generated = int(
            db.query(func.count(GeneratedPromptORM.id)).filter(prompt_criterion).scalar() or 0
        )
        candidate_generated = int(
            db.query(func.count(CandidateResponseORM.id)).filter(candidate_criterion).scalar() or 0
        )
        rows.append(
            {
                "language": language,
                "prompts": {
                    "generated": prompt_generated,
                    "target": prompt_generated,
                    "percent": 100.0 if prompt_generated else 0.0,
                    "by_status": _group_count(db, GeneratedPromptORM.status, prompt_criterion),
                    "by_harm_category": _group_count(db, GeneratedPromptORM.harm_category, prompt_criterion),
                    "by_harm_category_labeled": _labeled_category_counts(
                        _group_count(db, GeneratedPromptORM.harm_category, prompt_criterion)
                    ),
                    "by_severity": _group_count(db, GeneratedPromptORM.severity, prompt_criterion),
                    "by_severity_labeled": _labeled_severity_counts(
                        _group_count(db, GeneratedPromptORM.severity, prompt_criterion)
                    ),
                    "by_model": _group_count(db, GeneratedPromptORM.model_used, prompt_criterion),
                },
                "candidates": {
                    "generated": candidate_generated,
                    "target": candidate_generated,
                    "percent": 100.0 if candidate_generated else 0.0,
                    "by_status": _group_count(db, CandidateResponseORM.status, candidate_criterion),
                    "by_harm_category": _group_count(db, CandidateResponseORM.harm_category, candidate_criterion),
                    "by_harm_category_labeled": _labeled_category_counts(
                        _group_count(db, CandidateResponseORM.harm_category, candidate_criterion)
                    ),
                    "by_severity": _group_count(db, CandidateResponseORM.severity, candidate_criterion),
                    "by_severity_labeled": _labeled_severity_counts(
                        _group_count(db, CandidateResponseORM.severity, candidate_criterion)
                    ),
                    "by_response_type": _group_count(db, CandidateResponseORM.response_type, candidate_criterion),
                    "by_model": _group_count(db, CandidateResponseORM.model_used, candidate_criterion),
                },
            }
        )
    return rows


def _prompt_matrix(db: Session, run_id: str) -> list[dict[str, Any]]:
    rows = (
        db.query(
            GeneratedPromptORM.language,
            GeneratedPromptORM.harm_category,
            GeneratedPromptORM.severity,
            GeneratedPromptORM.status,
            func.count(),
        )
        .filter(GeneratedPromptORM.run_id == run_id)
        .group_by(
            GeneratedPromptORM.language,
            GeneratedPromptORM.harm_category,
            GeneratedPromptORM.severity,
            GeneratedPromptORM.status,
        )
        .order_by(
            GeneratedPromptORM.language,
            GeneratedPromptORM.harm_category,
            GeneratedPromptORM.severity,
            GeneratedPromptORM.status,
        )
        .all()
    )
    return [
        {
            "language": language,
            "harm_category": harm_category,
            "harm_category_label": _category_label(harm_category),
            "severity": severity,
            "severity_label": _severity_label(severity),
            "status": status,
            "count": int(count or 0),
        }
        for language, harm_category, severity, status, count in rows
    ]


def _candidate_matrix(db: Session, run_id: str) -> list[dict[str, Any]]:
    rows = (
        db.query(
            CandidateResponseORM.language,
            CandidateResponseORM.harm_category,
            CandidateResponseORM.severity,
            CandidateResponseORM.response_type,
            CandidateResponseORM.status,
            func.count(),
        )
        .filter(CandidateResponseORM.run_id == run_id)
        .group_by(
            CandidateResponseORM.language,
            CandidateResponseORM.harm_category,
            CandidateResponseORM.severity,
            CandidateResponseORM.response_type,
            CandidateResponseORM.status,
        )
        .order_by(
            CandidateResponseORM.language,
            CandidateResponseORM.harm_category,
            CandidateResponseORM.severity,
            CandidateResponseORM.response_type,
            CandidateResponseORM.status,
        )
        .all()
    )
    return [
        {
            "language": language,
            "harm_category": harm_category,
            "harm_category_label": _category_label(harm_category),
            "severity": severity,
            "severity_label": _severity_label(severity),
            "response_type": response_type,
            "status": status,
            "count": int(count or 0),
        }
        for language, harm_category, severity, response_type, status, count in rows
    ]


def _joined_group_count(db: Session, column, join_criterion, *filter_criteria) -> dict[str, int]:
    query = (
        db.query(column, func.count())
        .select_from(AnnotationORM)
        .join(CandidateResponseORM, join_criterion)
    )
    if filter_criteria:
        query = query.filter(*filter_criteria)
    rows = query.group_by(column).all()
    return {str(key or "unknown"): int(count or 0) for key, count in rows}


def _category_label(category_id: str | None) -> str:
    if not category_id:
        return "unknown"
    try:
        category = get_registry().get_category(category_id)
        return f"{category.id} - {category.name}"
    except Exception:
        return str(category_id)


def _severity_label(severity_code: str | None) -> str:
    if not severity_code:
        return "unknown"
    try:
        severity = get_registry().get_severity(severity_code)
        return f"{severity.code} - {severity.name}"
    except Exception:
        return str(severity_code)


def _labeled_category_counts(counts: dict[str, int]) -> dict[str, int]:
    return {_category_label(code): count for code, count in counts.items()}


def _labeled_severity_counts(counts: dict[str, int]) -> dict[str, int]:
    return {_severity_label(code): count for code, count in counts.items()}


def _stages(db: Session, run_id: str) -> list[dict[str, Any]]:
    rows = (
        db.query(PipelineStageRunORM)
        .filter(PipelineStageRunORM.run_id == run_id)
        .order_by(PipelineStageRunORM.started_at.asc())
        .all()
    )
    return [
        {
            "stage_name": row.stage_name,
            "status": row.status,
            "attempts": row.attempts,
            "started_at": _iso(row.started_at),
            "completed_at": _iso(row.completed_at),
            "updated_at": _iso(row.updated_at),
            "error": row.error,
        }
        for row in rows
    ]


def _percent(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(min(100.0, 100 * value / total), 1)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _age_seconds(started_at: datetime | None) -> int | None:
    if not started_at:
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return int((datetime.now(tz=timezone.utc) - started_at).total_seconds())
