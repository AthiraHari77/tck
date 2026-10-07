#!/usr/bin/env node
/**
 * generate_dashboard.js
 *
 * Node.js replacement for generate_dashboard.py.
 * Reads per-PR result folders + baseline CSV + queries upstream GitHub API.
 * Produces a FULLY SELF-CONTAINED HTML file — all CSS, SVG, and data embedded
 * as an inline JS variable. No external fetch() required at open time.
 * Safe to send as a Slack file attachment and open locally.
 *
 * Usage:
 *   node scripts/generate_dashboard.js \
 *     --pr-results-dir  pr-results \
 *     --baseline-csv    TestResults/Drools/999-SNAPSHOT/tck_results.csv \
 *     --upstream-repo   dmn-tck/tck \
 *     --token           $GITHUB_TOKEN \
 *     --output          docs/drools-dashboard.html
 */

'use strict';

const fs    = require('fs');
const path  = require('path');
const https = require('https');

// ── CLI args ──────────────────────────────────────────────────────────────────
const args = {};
process.argv.slice(2).forEach((v, i, a) => {
  if (v.startsWith('--')) args[v.slice(2)] = a[i + 1];
});

const PR_RESULTS_DIR = args['pr-results-dir'] || 'pr-results';
const BASELINE_CSV   = args['baseline-csv']   || 'TestResults/Drools/999-SNAPSHOT/tck_results.csv';
const UPSTREAM_REPO  = args['upstream-repo']  || 'dmn-tck/tck';
const TOKEN          = args['token']          || process.env.GITHUB_TOKEN || '';
const OUTPUT         = args['output']         || 'docs/drools-dashboard.html';

// ── GitHub API ────────────────────────────────────────────────────────────────
function ghGet(apiPath) {
  return new Promise((resolve, reject) => {
    const opts = {
      hostname: 'api.github.com',
      path: apiPath,
      headers: {
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'bamoe-tck-dashboard/1.0',
        ...(TOKEN ? { 'Authorization': `Bearer ${TOKEN}` } : {})
      }
    };
    https.get(opts, res => {
      let body = '';
      res.on('data', d => body += d);
      res.on('end', () => {
        try { resolve(JSON.parse(body)); }
        catch (e) { reject(new Error(`JSON parse on ${apiPath}: ${e.message}`)); }
      });
    }).on('error', reject);
  });
}

async function fetchOpenPRs(repo) {
  try {
    const data = await ghGet(`/repos/${repo}/pulls?state=open&per_page=50&sort=updated&direction=desc`);
    if (!Array.isArray(data)) return [];
    return data.map(p => ({
      number: p.number, title: p.title, url: p.html_url,
      author: p.user?.login || '', updatedAt: (p.updated_at || '').slice(0, 10),
      headSha: p.head?.sha || ''
    }));
  } catch (e) { console.warn('WARNING: Could not fetch PRs:', e.message); return []; }
}

async function fetchPRFiles(repo, number) {
  try {
    const data = await ghGet(`/repos/${repo}/pulls/${number}/files?per_page=100`);
    if (!Array.isArray(data)) return [];
    return data.map(f => f.filename);
  } catch (e) { return []; }
}

// ── CSV parsing ───────────────────────────────────────────────────────────────
function parseCSV(csvPath) {
  if (!fs.existsSync(csvPath)) return { suiteTotals: {}, failures: [], summary: { total: 0, pass: 0, fail: 0 } };
  const lines = fs.readFileSync(csvPath, 'utf8').split('\n');
  const failures = [];
  const suiteTotals = {};

  for (const line of lines) {
    if (!line.trim()) continue;
    const row = []; let cur = '', inQ = false;
    for (const ch of line) {
      if (ch === '"') { inQ = !inQ; }
      else if (ch === ',' && !inQ) { row.push(cur); cur = ''; }
      else cur += ch;
    }
    row.push(cur);
    if (row.length < 4) continue;

    const suitePath = row[0].replace(/^"|"$/g, '');
    const testName  = row[1].replace(/^"|"$/g, '');
    const caseId    = row[2].replace(/^"|"$/g, '');
    const status    = row[3].replace(/^"|"$/g, '');
    const message   = (row[4] || '').replace(/^"|"$/g, '');
    const parts     = suitePath.split('/');
    const level     = (parts[0] || '').replace('compliance-level-', 'L');
    const suite     = parts[1] || suitePath;

    if (!suiteTotals[suite]) suiteTotals[suite] = { pass: 0, fail: 0, total: 0, level };
    suiteTotals[suite].total++;
    if (status === 'SUCCESS') { suiteTotals[suite].pass++; }
    else {
      suiteTotals[suite].fail++;
      failures.push({ suite, level, caseId, testName, message: message.slice(0, 200),
        suitePath, key: `${suitePath}::${caseId}` });
    }
  }
  const total  = Object.values(suiteTotals).reduce((s, v) => s + v.total, 0);
  const passed = Object.values(suiteTotals).reduce((s, v) => s + v.pass,  0);
  const failed = Object.values(suiteTotals).reduce((s, v) => s + v.fail,  0);
  return { suiteTotals, failures, summary: { total, pass: passed, fail: failed } };
}

function loadPRResults(dir) {
  const results = {};
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir).sort()) {
    const prDir = path.join(dir, entry);
    if (!fs.statSync(prDir).isDirectory()) continue;
    const csvPath  = path.join(prDir, 'tck_results.csv');
    const metaPath = path.join(prDir, 'meta.json');
    if (!fs.existsSync(csvPath)) continue;
    const meta = fs.existsSync(metaPath) ? JSON.parse(fs.readFileSync(metaPath, 'utf8')) : {};
    const { suiteTotals, failures, summary } = parseCSV(csvPath);
    const prNum = parseInt(entry, 10);
    if (isNaN(prNum)) continue;
    results[prNum] = { meta, suiteTotals, failures, summary };
  }
  return results;
}

function getLevelTotals(csvPath) {
  if (!fs.existsSync(csvPath)) return {};
  const lines = fs.readFileSync(csvPath, 'utf8').split('\n');
  const levels = {};
  for (const line of lines) {
    if (!line.trim()) continue;
    const row = line.split(',');
    if (row.length < 4) continue;
    const suitePath = row[0].replace(/^"|"$/g, '');
    const status    = row[3].replace(/^"|"$/g, '');
    const lvl       = suitePath.split('/')[0] || 'unknown';
    if (!levels[lvl]) levels[lvl] = { pass: 0, total: 0 };
    levels[lvl].total++;
    if (status === 'SUCCESS') levels[lvl].pass++;
  }
  return levels;
}

// ── HTML escaping ─────────────────────────────────────────────────────────────
function esc(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── SVG donut ─────────────────────────────────────────────────────────────────
function donutSVG(pass, total) {
  const pct  = total ? pass / total : 1;
  const fail = total - pass;
  const r    = 46, circ = 2 * Math.PI * r;
  const pd   = pct * circ, fd = circ - pd;
  const label = total ? `${(pct * 100).toFixed(1)}%` : '—';
  return `<svg viewBox="0 0 180 155" width="100%" style="display:block">
  <circle cx="90" cy="70" r="${r}" fill="none" stroke="#e5e7eb" stroke-width="20"/>
  <circle cx="90" cy="70" r="${r}" fill="none" stroke="#059669" stroke-width="20"
    stroke-dasharray="${pd.toFixed(1)} ${fd.toFixed(1)}"
    stroke-dashoffset="${(circ/4).toFixed(1)}" transform="rotate(-90 90 70)"/>
  ${fail ? `<circle cx="90" cy="70" r="${r}" fill="none" stroke="#ef4444" stroke-width="20"
    stroke-dasharray="${fd.toFixed(1)} ${pd.toFixed(1)}"
    stroke-dashoffset="${(circ/4 - pd).toFixed(1)}" transform="rotate(-90 90 70)"/>` : ''}
  <text x="90" y="65" text-anchor="middle" font-size="15" font-weight="700" fill="#1f2328">${label}</text>
  <text x="90" y="81" text-anchor="middle" font-size="10" fill="#57606a">pass rate</text>
  <rect x="18" y="128" width="10" height="10" rx="2" fill="#059669"/>
  <text x="32" y="138" font-size="11" fill="#374151">Pass — ${pass.toLocaleString()}</text>
  <rect x="110" y="128" width="10" height="10" rx="2" fill="#ef4444"/>
  <text x="124" y="138" font-size="11" fill="#374151">Fail — ${fail.toLocaleString()}</text>
</svg>`;
}

// ── Main ──────────────────────────────────────────────────────────────────────
async function main() {
  const nowUtc = new Date().toISOString().replace('T', ' ').slice(0, 16) + ' UTC';
  console.log(`Generating dashboard → ${OUTPUT}`);

  const { suiteTotals: baselineSuites, failures: baselineFailures, summary: baselineSummary }
    = parseCSV(BASELINE_CSV);
  const baselineKeys = new Set(baselineFailures.map(f => f.key));
  const levelTotals  = getLevelTotals(BASELINE_CSV);
  const prResults    = loadPRResults(PR_RESULTS_DIR);
  console.log(`Loaded results for PRs: ${Object.keys(prResults).sort().join(', ') || 'none'}`);

  console.log(`Fetching open PRs from ${UPSTREAM_REPO}…`);
  const openPRs = await fetchOpenPRs(UPSTREAM_REPO);
  console.log(`Found ${openPRs.length} open PRs`);

  const prSuites = {};
  for (const pr of openPRs) {
    const files = await fetchPRFiles(UPSTREAM_REPO, pr.number);
    prSuites[pr.number] = files
      .filter(f => f.startsWith('TestCases/compliance-level-'))
      .map(f => f.split('/')[2]).filter(Boolean)
      .filter((v, i, a) => a.indexOf(v) === i);
  }

  // ── Build per-PR summaries ────────────────────────────────────────────────
  const openNums    = new Set(openPRs.map(p => p.number));
  const testedCount = openPRs.filter(p => prResults[p.number]).length;
  const prsWithNewFails = openPRs.filter(p => {
    const r = prResults[p.number];
    return r && r.failures.some(f => !baselineKeys.has(f.key));
  }).length;

  // ── HTML sections ─────────────────────────────────────────────────────────
  const { total: bTotal, pass: bPass, fail: bFail } = baselineSummary;
  const passRate = bTotal ? `${(bPass / bTotal * 100).toFixed(2)}%` : '—';

  // KPI
  const kpiHtml = `
<div class="kpi-row">
  <div class="kpi"><div class="kpi-value green">${bPass.toLocaleString()}</div><div class="kpi-label">Tests Passing</div></div>
  <div class="kpi"><div class="kpi-value red">${bFail.toLocaleString()}</div><div class="kpi-label">Tests Failing</div></div>
  <div class="kpi"><div class="kpi-value blue">${Object.values(baselineSuites).filter(v => v.fail > 0).length}</div><div class="kpi-label">Suites Affected</div></div>
  <div class="kpi"><div class="kpi-value orange">${passRate}</div><div class="kpi-label">Pass Rate</div></div>
</div>`;

  // Level bars
  let levelBarHtml = '';
  for (const lvl of Object.keys(levelTotals).sort()) {
    const v   = levelTotals[lvl];
    const pct = v.total ? v.pass / v.total * 100 : 100;
    const col = pct === 100 ? '#059669' : '#f59e0b';
    const lbl = lvl.replace('compliance-level-', 'Level-');
    levelBarHtml += `<div class="bar-wrap">
  <div class="bar-label">${esc(lbl)}</div>
  <div class="bar-track"><div class="bar-fill" style="width:${pct.toFixed(1)}%;background:${col}"></div></div>
  <div class="bar-val">${v.pass.toLocaleString()} / ${v.total.toLocaleString()}</div>
</div>`;
  }

  // Top failing suites
  let failSuiteHtml = '';
  const topFailing = Object.entries(baselineSuites)
    .filter(([, v]) => v.fail > 0).sort((a, b) => b[1].fail - a[1].fail).slice(0, 6);
  for (const [suite, v] of topFailing) {
    const pct = v.total ? v.pass / v.total * 100 : 100;
    const col = pct > 0 ? '#f59e0b' : '#ef4444';
    const lbl = suite.length > 22 ? suite.slice(0, 22) + '…' : suite;
    failSuiteHtml += `<div class="bar-wrap">
  <div class="bar-label" title="${esc(suite)}">${esc(lbl)}</div>
  <div class="bar-track"><div class="bar-fill" style="width:${pct.toFixed(1)}%;background:${col}"></div></div>
  <div class="bar-val">${v.pass.toLocaleString()} / ${v.total.toLocaleString()}</div>
</div>`;
  }

  // Summary card
  const latestDate = Object.values(prResults)
    .map(r => (r.meta.run_date || '').slice(0, 10)).filter(Boolean).sort().pop() || '';
  const vcBox = `<div class="vc-box">
  <div class="vc-head">Apache KIE Drools 999-SNAPSHOT${latestDate ? ` &nbsp;·&nbsp; Results: ${latestDate}` : ''}</div>
  <div class="vc-stat"><span>Total tests</span><strong>${bTotal.toLocaleString()}</strong></div>
  <div class="vc-stat"><span>Passing</span><strong class="green">${bPass.toLocaleString()}</strong></div>
  <div class="vc-stat"><span>Failing</span><strong class="red">${bFail.toLocaleString()}</strong></div>
  <div class="vc-stat"><span>Pass rate</span><strong>${passRate}</strong></div>
  <div class="vc-stat"><span>Suites with failures</span><strong>${Object.values(baselineSuites).filter(v=>v.fail>0).length}</strong></div>
  <div class="vc-stat"><span>Upstream repo</span>
    <a href="https://github.com/${UPSTREAM_REPO}" target="_blank" rel="noopener">${esc(UPSTREAM_REPO)}</a></div>
</div>`;

  // Attention banner
  const attentionPRs = openPRs.map(p => {
    const r = prResults[p.number];
    if (!r) return null;
    const newFails = r.failures.filter(f => !baselineKeys.has(f.key));
    return newFails.length ? { pr: p, newFails } : null;
  }).filter(Boolean);

  let attentionHtml = '';
  if (attentionPRs.length) {
    const items = attentionPRs.map(({ pr, newFails }) =>
      `<li><a href="${esc(pr.url)}" target="_blank" rel="noopener">#${pr.number} ${esc(pr.title)}</a>` +
      ` — <strong>${newFails.length} new failure${newFails.length !== 1 ? 's' : ''}</strong></li>`
    ).join('');
    attentionHtml = `<div class="warn-box">&#x26A0; <strong>Needs attention</strong> — ${attentionPRs.length} open PR(s) introduce new test failures:<ul>${items}</ul></div>`;
  }

  // PR status table
  let prRows = '';
  for (const pr of openPRs) {
    const res    = prResults[pr.number];
    const suites = prSuites[pr.number] || [];
    const chips  = suites.map(s => `<span class="badge badge-purple">${esc(s)}</span>`).join(' ');

    let rowCls, resultCell, scoreCell;
    if (!res) {
      rowCls     = 'pr-row-pending';
      resultCell = '<span class="badge badge-notested">not tested</span>';
      scoreCell  = '<span style="color:#9ca3af;font-size:12px;">—</span>';
    } else {
      const newFails = res.failures.filter(f => !baselineKeys.has(f.key));
      const exFails  = res.failures.filter(f =>  baselineKeys.has(f.key));
      const { total, pass } = res.summary;
      const pct = total ? Math.round(pass * 100 / total) : 0;
      const conflict = res.meta.merge_conflict || false;
      const ageMs    = res.meta.run_date ? Date.now() - new Date(res.meta.run_date).getTime() : 0;
      const ageDays  = Math.floor(ageMs / 86400000);

      if (newFails.length) {
        rowCls     = 'pr-row-fail';
        resultCell = `<span class="badge badge-new">&#x2717; ${newFails.length} new failure${newFails.length!==1?'s':''}</span>`;
        if (exFails.length) resultCell += ` <span class="badge badge-exist">+${exFails.length} pre-existing</span>`;
      } else if (exFails.length) {
        rowCls     = 'pr-row-warn';
        resultCell = `<span class="badge badge-warn">${exFails.length} pre-existing only</span>`;
      } else {
        rowCls     = 'pr-row-pass';
        resultCell = '<span class="badge badge-success">&#x2713; all pass</span>';
      }
      if (conflict) resultCell += ' <span class="badge badge-conflict">⚠ merge conflict</span>';
      if (ageDays > 7) resultCell += ` <span class="badge badge-stale">stale ${ageDays}d</span>`;
      scoreCell = `<span style="font-size:12px;"><strong style="color:#059669;">${pass.toLocaleString()}</strong>` +
        `<span style="color:#d1d5db;"> / </span>${total.toLocaleString()}</span>` +
        ` <span style="font-size:10px;color:#9ca3af;">(${pct}%)</span>`;
    }

    prRows += `<tr class="${rowCls}">
  <td><span class="pr-num">#${pr.number}</span></td>
  <td><a class="pr-title-link" href="${esc(pr.url)}" target="_blank" rel="noopener">${esc(pr.title)}</a>
    ${chips ? `<br>${chips}` : ''}
    <br><span class="pr-author-date">${esc(pr.author)} &middot; ${esc(pr.updatedAt)}</span></td>
  <td>${resultCell}</td>
  <td>${scoreCell}</td>
</tr>`;
  }
  const prTableHtml = openPRs.length
    ? `<div class="table-wrap"><table class="pr-status-table">
  <thead><tr><th style="width:52px">PR</th><th>Title</th><th>Drools result</th><th style="width:130px">Pass rate</th></tr></thead>
  <tbody>${prRows}</tbody>
</table></div>
<p class="footnote">Results tested as if each PR branch were synced with master (local merge before run).</p>`
    : '<p style="font-size:13px;color:#57606a;padding:8px 0;">No open upstream PRs.</p>';

  // Drilldown
  let drilldownHtml = '';
  for (const { pr, newFails } of attentionPRs) {
    const exFails  = (prResults[pr.number]?.failures || []).filter(f => baselineKeys.has(f.key));
    const conflict = prResults[pr.number]?.meta.merge_conflict || false;
    let notes = conflict ? '<span class="badge badge-conflict">⚠ merge conflict</span> ' : '';
    if (exFails.length) notes += `<span style="font-size:11px;color:#57606a;">${exFails.length} pre-existing excluded</span>`;
    const rows = newFails.sort((a, b) => `${a.level}${a.suite}${a.caseId}`.localeCompare(`${b.level}${b.suite}${b.caseId}`))
      .map(f => {
        const ghUrl = `https://github.com/dmn-tck/tck/tree/master/TestCases/${esc(f.suitePath)}`;
        return `<tr class="row-new">
  <td><span class="badge badge-gray">${esc(f.level)}</span></td>
  <td class="mono"><a href="${ghUrl}" target="_blank" rel="noopener">${esc(f.suite)}</a></td>
  <td class="mono">${esc(f.caseId)}</td>
  <td class="mono">${esc(f.testName)}</td>
  <td><code>${esc(f.message)}${f.message.length >= 200 ? '…' : ''}</code></td>
</tr>`;
      }).join('');
    drilldownHtml += `<div class="fail-pr-block">
  <div class="fail-pr-header">
    <a href="${esc(pr.url)}" target="_blank" rel="noopener">#${pr.number} ${esc(pr.title)}</a>
    <span class="badge badge-new">${newFails.length} new failure${newFails.length!==1?'s':''}</span>
    ${notes}
  </div>
  <div class="table-wrap"><table>
    <thead><tr><th>Level</th><th>Suite</th><th>Case ID</th><th>Test</th><th>Failure message</th></tr></thead>
    <tbody>${rows}</tbody>
  </table></div>
</div>`;
  }
  if (!drilldownHtml) drilldownHtml = '<p style="color:#057a55;font-size:13px;padding:8px 0;">&#x2705; No net-new failures across all tested open PRs.</p>';

  // Baseline table
  let baselineTableHtml = '';
  if (baselineFailures.length) {
    const bRows = baselineFailures
      .sort((a, b) => `${a.level}${a.suite}`.localeCompare(`${b.level}${b.suite}`))
      .map(f => {
        const ghUrl = `https://github.com/dmn-tck/tck/tree/master/TestCases/${esc(f.suitePath)}`;
        return `<tr>
  <td><span class="badge badge-gray">${esc(f.level)}</span> <a class="mono" href="${ghUrl}" target="_blank">${esc(f.suite)}</a></td>
  <td class="mono">${esc(f.caseId)}</td>
  <td class="mono">${esc(f.testName)}</td>
  <td><code>${esc(f.message)}${f.message.length >= 200 ? '…' : ''}</code></td>
</tr>`;
      }).join('');
    baselineTableHtml = `<div class="table-wrap"><table>
  <thead><tr><th>Suite</th><th>Case ID</th><th>Test</th><th>Failure message</th></tr></thead>
  <tbody>${bRows}</tbody>
</table></div>`;
  } else {
    baselineTableHtml = '<p style="color:#057a55;font-size:13px;padding:8px 0;">&#x2705; No baseline failures on master.</p>';
  }

  // ── Assemble full HTML ────────────────────────────────────────────────────
  const drilldownSection = attentionPRs.length ? `
<section>
  <div class="section-title">Net-New Failures Introduced by Open PRs
    <span class="badge badge-fail">${attentionPRs.reduce((s, x) => s + x.newFails.length, 0)} failures across ${attentionPRs.length} PR${attentionPRs.length!==1?'s':''}</span>
  </div>
  <p class="footnote" style="margin-bottom:10px;">Pre-existing baseline failures are excluded — only failures not on master are shown.</p>
  ${drilldownHtml}
</section>` : '';

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Drools TCK Dashboard — 999-SNAPSHOT</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "Segoe UI", system-ui, sans-serif; font-size: 14px; line-height: 1.6; background: #fff; color: #1f2328; padding: 24px 20px 56px; }
.page { max-width: 860px; margin: 0 auto; }
.header { border-bottom: 1px solid #e5e7eb; padding-bottom: 14px; margin-bottom: 22px; }
.header h1 { font-size: 19px; font-weight: 700; }
.header-meta { font-size: 12px; color: #57606a; margin-top: 5px; display: flex; flex-wrap: wrap; gap: 6px 18px; align-items: center; }
.header-meta a { color: #3b82d4; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; vertical-align: middle; white-space: nowrap; }
.badge-success { background: #d1fae5; color: #065f46; }
.badge-fail    { background: #fee2e2; color: #991b1b; }
.badge-warn    { background: #fef3c7; color: #92400e; }
.badge-info    { background: #dbeafe; color: #1e40af; }
.badge-purple  { background: #ede9fe; color: #5b21b6; }
.badge-gray    { background: #f3f4f6; color: #374151; }
.badge-new     { background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }
.badge-exist   { background: #fef3c7; color: #92400e; }
.badge-notested{ background: #f3f4f6; color: #57606a; border: 1px solid #e5e7eb; }
.badge-stale   { background: #fef9c3; color: #854d0e; border: 1px solid #fde047; }
.badge-conflict{ background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }
section { margin-bottom: 30px; }
.section-title { font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: #57606a; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }
.kpi-row { display: grid; grid-template-columns: repeat(4,1fr); gap: 10px; margin-bottom: 14px; }
.kpi { background: #f7f8fa; border: 1px solid #e5e7eb; border-radius: 6px; padding: 13px 12px; text-align: center; }
.kpi-value { font-size: 24px; font-weight: 700; line-height: 1.15; }
.kpi-label { font-size: 11px; color: #57606a; margin-top: 3px; }
.green { color: #065f46; } .red { color: #991b1b; } .orange { color: #92400e; } .blue { color: #1e40af; }
.charts-row { display: grid; grid-template-columns: 210px 1fr; gap: 12px; margin-bottom: 14px; align-items: start; }
.chart-box { background: #f7f8fa; border: 1px solid #e5e7eb; border-radius: 6px; padding: 14px 16px; }
.chart-title { font-size: 12px; font-weight: 600; color: #57606a; margin-bottom: 10px; }
.bar-wrap { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.bar-label { font-size: 12px; color: #57606a; white-space: nowrap; min-width: 90px; overflow: hidden; text-overflow: ellipsis; }
.bar-track { flex: 1; height: 12px; background: #e5e7eb; border-radius: 3px; overflow: hidden; }
.bar-fill  { height: 100%; border-radius: 3px; }
.bar-val   { font-size: 11px; color: #57606a; min-width: 56px; text-align: right; white-space: nowrap; }
.vc-box { background: #f7f8fa; border: 1px solid #e5e7eb; border-radius: 6px; padding: 12px 14px; margin-bottom: 8px; }
.vc-head { font-size: 12px; font-weight: 700; color: #57606a; margin-bottom: 8px; }
.vc-stat { display: flex; justify-content: space-between; align-items: baseline; font-size: 12px; padding: 3px 0; border-bottom: 1px solid #f0f1f3; gap: 8px; }
.vc-stat:last-child { border-bottom: none; }
.vc-stat span:first-child { color: #57606a; } .vc-stat a { color: #3b82d4; text-decoration: none; }
.warn-box { background: #fff7ed; border: 1px solid #fed7aa; border-left: 4px solid #f97316; border-radius: 6px; padding: 11px 14px; font-size: 13px; color: #9a3412; margin-bottom: 14px; }
.warn-box ul { margin-top: 6px; padding-left: 18px; }
.table-wrap { overflow-x: auto; border: 1px solid #e5e7eb; border-radius: 6px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
thead th { background: #f7f8fa; text-align: left; padding: 8px 10px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: #57606a; border-bottom: 1px solid #e5e7eb; white-space: nowrap; }
tbody tr { border-bottom: 1px solid #f0f1f3; }
tbody tr:last-child { border-bottom: none; }
tbody td { padding: 8px 10px; vertical-align: top; }
tbody tr:hover { background: #fafbfc; }
tbody tr.row-new td { background: #fff5f5; }
.mono { font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; }
code { font-family: "SFMono-Regular", Consolas, monospace; font-size: 11px; background: #f3f4f6; padding: 1px 4px; border-radius: 3px; word-break: break-all; }
.pr-status-table thead th { background: #f7f8fa; text-align: left; padding: 8px 10px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: #57606a; border-bottom: 1px solid #e5e7eb; white-space: nowrap; }
.pr-status-table tbody tr { border-bottom: 1px solid #f0f1f3; }
.pr-status-table tbody td { padding: 9px 10px; vertical-align: middle; }
.pr-row-fail td:first-child { box-shadow: inset 3px 0 0 #ef4444; }
.pr-row-warn td:first-child { box-shadow: inset 3px 0 0 #f59e0b; }
.pr-row-pass td:first-child { box-shadow: inset 3px 0 0 #059669; }
.pr-row-pending td:first-child { box-shadow: inset 3px 0 0 #d1d5db; }
.pr-num { font-size: 12px; font-weight: 700; color: #57606a; white-space: nowrap; }
.pr-title-link { font-weight: 500; color: #3b82d4; text-decoration: none; }
.pr-title-link:hover { text-decoration: underline; }
.pr-author-date { font-size: 11px; color: #9ca3af; }
.fail-pr-block { margin-bottom: 20px; }
.fail-pr-header { display: flex; align-items: baseline; gap: 10px; font-size: 12px; color: #57606a; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; margin-bottom: 8px; }
.fail-pr-header a { font-weight: 600; font-size: 13px; color: #3b82d4; text-decoration: none; }
.footnote { font-size: 11px; color: #57606a; margin-top: 7px; }
@media (max-width: 640px) { .kpi-row { grid-template-columns: repeat(2,1fr); } .charts-row { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="page">

<div class="header">
  <h1>Drools TCK Compatibility Dashboard</h1>
  <div class="header-meta">
    <span>Source: <a href="https://github.com/${UPSTREAM_REPO}" target="_blank" rel="noopener">github.com/${esc(UPSTREAM_REPO)}</a> · master</span>
    <span>Engine: <strong>Apache KIE Drools</strong> 999-SNAPSHOT</span>
    <span>Generated: <strong>${nowUtc}</strong></span>
  </div>
</div>

${attentionHtml}

<section>
  <div class="section-title">Overview — Apache KIE Drools 999-SNAPSHOT</div>
  ${kpiHtml}
  <div class="charts-row">
    <div class="chart-box"><div class="chart-title">Pass / Fail split</div>${donutSVG(bPass, bTotal)}</div>
    <div class="chart-box"><div class="chart-title">Results by compliance level</div>${levelBarHtml}${topFailing.length ? `<div style="height:6px"></div>${failSuiteHtml}` : ''}</div>
  </div>
  ${vcBox}
</section>

<section>
  <div class="section-title">
    Open Pull Requests
    <span class="badge badge-info">${openPRs.length} open</span>
    <span class="badge badge-gray">${testedCount} tested</span>
    ${prsWithNewFails ? `<span class="badge badge-fail">${prsWithNewFails} with new failures</span>` : ''}
  </div>
  ${prTableHtml}
</section>

${drilldownSection}

<section>
  <div class="section-title">Baseline Failures — Already on Master
    <span class="badge badge-warn">${baselineFailures.length} failures</span>
  </div>
  <p class="footnote" style="margin-bottom:10px;">These failures exist on the current master branch before any PR is applied. Pre-existing issues in Drools 999-SNAPSHOT, not counted against any open PR.</p>
  ${baselineTableHtml}
</section>

</div>
<footer style="text-align:center;font-size:12px;color:#9ca3af;border-top:1px solid #e5e7eb;margin-top:32px;padding-top:12px;max-width:860px;margin-left:auto;margin-right:auto;">
  Auto-generated · <a href="https://github.com/${UPSTREAM_REPO}" target="_blank" rel="noopener" style="color:#9ca3af;">github.com/${esc(UPSTREAM_REPO)}</a>
</footer>
</body>
</html>`;

  fs.mkdirSync(path.dirname(path.resolve(OUTPUT)), { recursive: true });
  fs.writeFileSync(OUTPUT, html, 'utf8');
  console.log(`✓ Dashboard written → ${OUTPUT} (${Math.round(html.length / 1024)} KB)`);
  console.log(`  Open PRs: ${openPRs.length} | Tested: ${testedCount} | With new failures: ${prsWithNewFails}`);
}

main().catch(e => { console.error(e); process.exit(1); });
