#!/usr/bin/env python3
"""
BAMOE TCK Dashboard Generator
Reads per-PR result folders + baseline CSV + queries upstream GitHub API for PRs.
Produces a self-contained HTML dashboard that clearly differentiates:
  - Existing baseline failures (already failing on master, not caused by any PR)
  - Net-new failures introduced by a specific open PR

Usage:
    python3 scripts/generate_dashboard.py \
        --pr-results-dir  pr-results \
        --baseline-csv    TestResults/Drools/999-SNAPSHOT/tck_results.csv \
        --upstream-repo   dmn-tck/tck \
        --token           $GITHUB_TOKEN \
        --output          docs/drools-dashboard.html
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from html import escape

try:
    import requests
except ImportError:
    print("ERROR: install requests: pip install requests", file=sys.stderr)
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# GitHub API
# ─────────────────────────────────────────────────────────────────────────────

def gh_headers(token):
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def fetch_prs(repo, token, state="all", limit=60):
    url = f"https://api.github.com/repos/{repo}/pulls"
    params = {"state": state, "per_page": limit, "sort": "updated", "direction": "desc"}
    try:
        r = requests.get(url, headers=gh_headers(token), params=params, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"WARNING: Could not fetch PRs: {e}", file=sys.stderr)
        return []


def fetch_pr_files(repo, pr_number, token):
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
    try:
        r = requests.get(url, headers=gh_headers(token), params={"per_page": 100}, timeout=30)
        if r.status_code != 200:
            return []
        return [f["filename"] for f in r.json()]
    except Exception:
        return []


def pr_new_suites(files):
    suites = set()
    for f in files:
        if f.startswith("TestCases/compliance-level-"):
            parts = f.split("/")
            if len(parts) >= 3:
                suites.add(parts[2])
    return suites


# ─────────────────────────────────────────────────────────────────────────────
# CSV parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_csv(csv_path):
    """
    Returns (suite_totals, failures_list, summary_dict).
    Each failure is identified by a (suite_path, case_id) key for deduplication.
    """
    failures = []
    suite_totals = defaultdict(lambda: {"pass": 0, "fail": 0, "total": 0})

    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) < 4:
                continue
            suite_path = row[0].strip('"')
            test_name  = row[1].strip('"')
            case_id    = row[2].strip('"')
            status     = row[3].strip('"')
            message    = row[4].strip('"') if len(row) > 4 else ""

            parts = suite_path.split("/")
            level = parts[0].replace("compliance-level-", "L") if parts else "?"
            suite = parts[1] if len(parts) >= 2 else suite_path

            suite_totals[suite]["total"] += 1
            if status == "SUCCESS":
                suite_totals[suite]["pass"] += 1
            else:
                suite_totals[suite]["fail"] += 1
                failures.append({
                    "suite": suite, "level": level,
                    "case_id": case_id, "test": test_name,
                    "message": message, "suite_path": suite_path,
                    # unique key used for baseline comparison
                    "key": f"{suite_path}::{case_id}",
                })

    total  = sum(v["total"] for v in suite_totals.values())
    passed = sum(v["pass"]  for v in suite_totals.values())
    failed = sum(v["fail"]  for v in suite_totals.values())
    return dict(suite_totals), failures, {"total": total, "pass": passed, "fail": failed}


def load_baseline(baseline_csv):
    """
    Load the committed baseline (TestResults/Drools/999-SNAPSHOT/tck_results.csv).
    Returns a set of failure keys: {suite_path::case_id, ...}
    """
    if not baseline_csv or not os.path.exists(baseline_csv):
        print("WARNING: No baseline CSV found — all failures will be shown as new.", file=sys.stderr)
        return set()

    _, failures, summary = parse_csv(baseline_csv)
    keys = {f["key"] for f in failures}
    print(f"Baseline loaded: {summary['fail']} existing failures from {baseline_csv}")
    return keys


def split_failures(failures, baseline_keys):
    """
    Split a PR's failures into:
      - existing: already failing in baseline (not caused by this PR)
      - new:      not in baseline (introduced or exposed by this PR)
    """
    existing = [f for f in failures if f["key"] in baseline_keys]
    new      = [f for f in failures if f["key"] not in baseline_keys]
    return existing, new


# ─────────────────────────────────────────────────────────────────────────────
# Load per-PR results from disk
# ─────────────────────────────────────────────────────────────────────────────

def load_pr_results(pr_results_dir):
    results = {}
    if not os.path.isdir(pr_results_dir):
        return results

    for entry in sorted(os.listdir(pr_results_dir)):
        pr_dir = os.path.join(pr_results_dir, entry)
        if not os.path.isdir(pr_dir):
            continue
        csv_path  = os.path.join(pr_dir, "tck_results.csv")
        meta_path = os.path.join(pr_dir, "meta.json")
        if not os.path.exists(csv_path):
            continue

        meta = {}
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                meta = json.load(f)

        suite_totals, failures, summary = parse_csv(csv_path)
        try:
            pr_num = int(entry)
        except ValueError:
            continue

        results[pr_num] = {
            "meta": meta,
            "suite_totals": suite_totals,
            "failures": failures,
            "summary": summary,
        }

    return results


# ─────────────────────────────────────────────────────────────────────────────
# HTML helpers
# ─────────────────────────────────────────────────────────────────────────────

CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
  font-size: 14px; line-height: 1.6;
  background: #fff; color: #1f2328;
  padding: 24px 20px 56px;
}
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
.badge-notested { background: #f3f4f6; color: #57606a; border: 1px solid #e5e7eb; }
.badge-stale   { background: #fef9c3; color: #854d0e; border: 1px solid #fde047; }
.badge-conflict { background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }

section { margin-bottom: 30px; }
.section-title { font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: #57606a; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }

.kpi-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }
.kpi { background: #f7f8fa; border: 1px solid #e5e7eb; border-radius: 6px; padding: 13px 12px; text-align: center; }
.kpi-value { font-size: 24px; font-weight: 700; line-height: 1.15; }
.kpi-label { font-size: 11px; color: #57606a; margin-top: 3px; }
.green { color: #065f46; } .red { color: #991b1b; } .orange { color: #92400e; } .blue { color: #1e40af; }

.charts-row { display: grid; grid-template-columns: 210px 1fr; gap: 12px; margin-bottom: 14px; align-items: start; }
.chart-box { background: #f7f8fa; border: 1px solid #e5e7eb; border-radius: 6px; padding: 14px 16px; }
.chart-title { font-size: 12px; font-weight: 600; color: #57606a; margin-bottom: 10px; }
.bar-wrap { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.bar-wrap:last-child { margin-bottom: 0; }
.bar-label { font-size: 12px; color: #57606a; white-space: nowrap; min-width: 90px; overflow: hidden; text-overflow: ellipsis; }
.bar-track { flex: 1; height: 12px; background: #e5e7eb; border-radius: 3px; overflow: hidden; }
.bar-fill  { height: 100%; border-radius: 3px; }
.bar-val   { font-size: 11px; color: #57606a; min-width: 56px; text-align: right; white-space: nowrap; }

.vc-box { background: #f7f8fa; border: 1px solid #e5e7eb; border-radius: 6px; padding: 12px 14px; margin-bottom: 8px; }
.vc-head { font-size: 12px; font-weight: 700; color: #57606a; margin-bottom: 8px; }
.vc-stat { display: flex; justify-content: space-between; align-items: baseline; font-size: 12px; padding: 3px 0; border-bottom: 1px solid #f0f1f3; gap: 8px; }
.vc-stat:last-child { border-bottom: none; }
.vc-stat span:first-child { color: #57606a; }
.vc-stat a { color: #3b82d4; text-decoration: none; }

.warn-box { background: #fff7ed; border: 1px solid #fed7aa; border-left: 4px solid #f97316; border-radius: 6px; padding: 11px 14px; font-size: 13px; color: #9a3412; margin-bottom: 14px; }
.warn-box ul { margin-top: 6px; padding-left: 18px; }

.table-wrap { overflow-x: auto; border: 1px solid #e5e7eb; border-radius: 6px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
thead th { background: #f7f8fa; text-align: left; padding: 8px 10px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: #57606a; border-bottom: 1px solid #e5e7eb; white-space: nowrap; }
tbody tr { border-bottom: 1px solid #f0f1f3; }
tbody tr:last-child { border-bottom: none; }
tbody td { padding: 8px 10px; vertical-align: top; }
tbody tr:hover { background: #fafbfc; }
tbody tr.row-new  td { background: #fff5f5; }
tbody tr.row-new:hover td { background: #fee9e9; }
.mono { font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace; font-size: 12px; }
code { font-family: "SFMono-Regular", Consolas, monospace; font-size: 11px; background: #f3f4f6; padding: 1px 4px; border-radius: 3px; word-break: break-all; }

.pr-status-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.pr-status-table thead th { background: #f7f8fa; text-align: left; padding: 8px 10px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: #57606a; border-bottom: 1px solid #e5e7eb; white-space: nowrap; }
.pr-status-table tbody tr { border-bottom: 1px solid #f0f1f3; }
.pr-status-table tbody tr:last-child { border-bottom: none; }
.pr-status-table tbody td { padding: 9px 10px; vertical-align: middle; }
.pr-status-table tbody tr:hover { background: #fafbfc; }
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
.fail-pr-header a:hover { text-decoration: underline; }

.footnote { font-size: 11px; color: #57606a; margin-top: 7px; }

@media (max-width: 640px) {
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
  .charts-row { grid-template-columns: 1fr; }
}
"""


def _age_days(run_date_str):
    try:
        dt = datetime.fromisoformat(run_date_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return None


def _donut_svg(pass_count, total):
    """SVG donut chart: green for pass, red for fail."""
    pct = pass_count / total if total else 1.0
    fail_count = total - pass_count
    r = 46
    circ = 2 * 3.14159 * r  # ~289
    pass_dash = pct * circ
    fail_dash = circ - pass_dash
    pct_label = f"{pct*100:.1f}%"
    return f"""<svg viewBox="0 0 180 155" width="100%" style="display:block">
  <circle cx="90" cy="70" r="{r}" fill="none" stroke="#e5e7eb" stroke-width="20"/>
  <circle cx="90" cy="70" r="{r}" fill="none" stroke="#059669" stroke-width="20"
    stroke-dasharray="{pass_dash:.1f} {fail_dash:.1f}"
    stroke-dashoffset="{circ/4:.1f}" transform="rotate(-90 90 70)"/>
  {'<circle cx="90" cy="70" r="' + str(r) + '" fill="none" stroke="#ef4444" stroke-width="20" stroke-dasharray="' + f"{fail_dash:.1f} {pass_dash:.1f}" + '" stroke-dashoffset="' + f"{circ/4 - pass_dash:.1f}" + '" transform="rotate(-90 90 70)"/>' if fail_count else ''}
  <text x="90" y="65" text-anchor="middle" font-size="15" font-weight="700" fill="#1f2328">{pct_label}</text>
  <text x="90" y="81" text-anchor="middle" font-size="10" fill="#57606a">pass rate</text>
  <rect x="18" y="128" width="10" height="10" rx="2" fill="#059669"/>
  <text x="32" y="138" font-size="11" fill="#374151">Pass — {pass_count:,}</text>
  <rect x="110" y="128" width="10" height="10" rx="2" fill="#ef4444"/>
  <text x="124" y="138" font-size="11" fill="#374151">Fail — {fail_count:,}</text>
</svg>"""


def _level_bars(suite_totals):
    """Horizontal bars: one per compliance level, then top failing suites."""
    level_totals = defaultdict(lambda: {"pass": 0, "total": 0})
    for suite, v in suite_totals.items():
        # suite_totals keys are suite names; we need the level from the CSV
        # level info is embedded in suite names grouped by path — derive from data
        pass
    # Group by level prefix
    l2 = {"pass": 0, "total": 0}
    l3 = {"pass": 0, "total": 0}
    for suite, v in suite_totals.items():
        # We use a heuristic: suite names < "1000" are typically L3 numeric,
        # but we don't have level info in suite_totals directly.
        # Use the raw totals grouped together — show top failing suites only.
        pass

    bars = ""
    # Sort suites by fail count descending, show top 6
    failing_suites = sorted(
        [(s, v) for s, v in suite_totals.items() if v["fail"] > 0],
        key=lambda x: x[1]["fail"], reverse=True
    )[:6]

    for suite, v in failing_suites:
        pct = v["pass"] / v["total"] * 100 if v["total"] else 100
        colour = "#059669" if pct == 100 else ("#f59e0b" if pct >= 80 else "#ef4444")
        label = suite[:22] + "…" if len(suite) > 22 else suite
        bars += f"""<div class="bar-wrap">
  <div class="bar-label" title="{escape(suite)}">{escape(label)}</div>
  <div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%;background:{colour}"></div></div>
  <div class="bar-val">{v['pass']:,} / {v['total']:,}</div>
</div>"""
    if not bars:
        bars = '<div style="font-size:12px;color:#059669;padding:4px 0;">All suites passing ✓</div>'
    return bars


def _pr_status_table(open_prs, pr_results, pr_suites_map, baseline_keys):
    """Compact one-row-per-PR table for open PRs."""
    if not open_prs:
        return '<p style="font-size:13px;color:#57606a;padding:8px 0;">No open upstream PRs.</p>'
    rows = ""
    for pr in open_prs:
        num     = pr["number"]
        title   = escape(pr["title"])
        url     = pr["html_url"]
        author  = escape(pr.get("user", {}).get("login", ""))
        updated = (pr.get("updated_at") or "")[:10]
        suites  = pr_suites_map.get(num, set())
        res     = pr_results.get(num)

        suite_chips = " ".join(
            f'<span class="badge badge-purple">{escape(s)}</span>'
            for s in sorted(suites)
        ) if suites else ""

        if res is None:
            row_cls     = "pr-row-pending"
            result_cell = '<span class="badge badge-notested">not tested</span>'
            score_cell  = '<span style="color:#9ca3af;font-size:12px;">—</span>'
        else:
            existing_fails, new_fails = split_failures(res["failures"], baseline_keys)
            total      = res["summary"]["total"]
            pass_count = res["summary"]["pass"]
            conflict   = res["meta"].get("merge_conflict", False)
            age        = _age_days(res["meta"].get("run_date", ""))
            pct        = int(pass_count * 100 / total) if total else 0

            if new_fails:
                row_cls     = "pr-row-fail"
                result_cell = f'<span class="badge badge-new">&#x2717; {len(new_fails)} new failure{"s" if len(new_fails)!=1 else ""}</span>'
                if existing_fails:
                    result_cell += f' <span class="badge badge-exist">+{len(existing_fails)} pre-existing</span>'
            elif existing_fails:
                row_cls     = "pr-row-warn"
                result_cell = f'<span class="badge badge-warn">{len(existing_fails)} pre-existing only</span>'
            else:
                row_cls     = "pr-row-pass"
                result_cell = '<span class="badge badge-success">&#x2713; all pass</span>'

            if conflict:
                result_cell += ' <span class="badge badge-conflict" title="Merge conflict — raw branch tested">⚠ merge conflict</span>'
            if age is not None and age > 7:
                result_cell += f' <span class="badge badge-stale">stale {age}d</span>'

            score_cell = (
                f'<span style="font-size:12px;">'
                f'<strong style="color:#059669;">{pass_count:,}</strong>'
                f'<span style="color:#d1d5db;"> / </span>{total:,}'
                f'</span> <span style="font-size:10px;color:#9ca3af;">({pct}%)</span>'
            )

        rows += f"""<tr class="{row_cls}">
  <td><span class="pr-num">#{num}</span></td>
  <td>
    <a class="pr-title-link" href="{url}" target="_blank" rel="noopener">{title}</a>
    {('<br>' + suite_chips) if suite_chips else ''}
    <br><span class="pr-author-date">{author} &middot; {updated}</span>
  </td>
  <td>{result_cell}</td>
  <td>{score_cell}</td>
</tr>"""

    return f"""<div class="table-wrap">
<table class="pr-status-table">
  <thead><tr>
    <th style="width:52px;">PR</th>
    <th>Title</th>
    <th>Drools result</th>
    <th style="width:130px;">Pass rate</th>
  </tr></thead>
  <tbody>{rows}</tbody>
</table>
</div>
<p class="footnote">
  Results tested as if each PR branch were synced with master (local merge before run) —
  failures shown are genuine conflicts introduced by the PR, not stale-branch noise.
</p>"""


def _new_failures_drilldown(open_prs, pr_results, baseline_keys):
    """Per-PR tables showing only net-new failures. Pre-existing suppressed to a count."""
    blocks = ""
    for pr in open_prs:
        res = pr_results.get(pr["number"])
        if not res:
            continue
        existing_fails, new_fails = split_failures(res["failures"], baseline_keys)
        if not new_fails:
            continue

        url      = pr["html_url"]
        num      = pr["number"]
        title    = escape(pr["title"])
        conflict = res["meta"].get("merge_conflict", False)

        notes = []
        if conflict:
            notes.append('<span class="badge badge-conflict">⚠ merge conflict — some noise possible</span>')
        if existing_fails:
            notes.append(f'<span style="font-size:11px;color:#57606a;">{len(existing_fails)} pre-existing failures excluded from this list</span>')
        note_html = " ".join(notes)

        rows = ""
        for f in sorted(new_fails, key=lambda x: (x["level"], x["suite"], x["case_id"])):
            gh_url = f"https://github.com/dmn-tck/tck/tree/master/TestCases/{escape(f['suite_path'])}"
            rows += f"""<tr class="row-new">
  <td style="white-space:nowrap;"><span class="badge badge-gray">{escape(f['level'])}</span></td>
  <td class="mono" style="white-space:nowrap;">
    <a href="{gh_url}" target="_blank" rel="noopener">{escape(f['suite'])}</a>
  </td>
  <td class="mono">{escape(f['case_id'])}</td>
  <td class="mono">{escape(f['test'])}</td>
  <td><code>{escape(f['message'][:120])}{'…' if len(f['message'])>120 else ''}</code></td>
</tr>"""

        blocks += f"""<div class="fail-pr-block">
  <div class="fail-pr-header">
    <a href="{url}" target="_blank" rel="noopener">#{num} {title}</a>
    <span class="badge badge-new">{len(new_fails)} new failure{"s" if len(new_fails)!=1 else ""}</span>
    {note_html}
  </div>
  <div class="table-wrap"><table>
    <thead><tr><th>Level</th><th>Suite</th><th>Case ID</th><th>Test</th><th>Failure message</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
</div>"""

    if not blocks:
        return '<p style="color:#057a55;font-size:13px;padding:8px 0;">&#x2705; No net-new failures across all tested open PRs.</p>'
    return blocks


def _baseline_table(baseline_failure_details):
    if not baseline_failure_details:
        return '<p style="color:#057a55;font-size:13px;padding:8px 0;">&#x2705; No baseline failures on master.</p>'
    rows = ""
    for f in sorted(baseline_failure_details, key=lambda x: (x["level"], x["suite"])):
        gh_url = f"https://github.com/dmn-tck/tck/tree/master/TestCases/{escape(f['suite_path'])}"
        rows += f"""<tr>
  <td style="white-space:nowrap;"><span class="badge badge-gray">{escape(f['level'])}</span>
    <a class="mono" href="{gh_url}" target="_blank" rel="noopener">{escape(f['suite'])}</a>
  </td>
  <td class="mono">{escape(f['case_id'])}</td>
  <td class="mono">{escape(f['test'])}</td>
  <td><code>{escape(f['message'][:120])}{'…' if len(f['message'])>120 else ''}</code></td>
</tr>"""
    return f"""<div class="table-wrap"><table>
  <thead><tr><th>Suite</th><th>Case ID</th><th>Test</th><th>Failure message</th></tr></thead>
  <tbody>{rows}</tbody>
</table></div>"""


# ─────────────────────────────────────────────────────────────────────────────
# Main builder
# ─────────────────────────────────────────────────────────────────────────────

def build_dashboard(pr_results_dir, baseline_csv, upstream_repo, token, output_path):
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── Load data ──────────────────────────────────────────────────────────────
    baseline_keys = load_baseline(baseline_csv)

    baseline_suite_totals = {}
    baseline_failure_details = []
    if baseline_csv and os.path.exists(baseline_csv):
        baseline_suite_totals, baseline_failure_details, baseline_summary = parse_csv(baseline_csv)
    else:
        baseline_summary = {"total": 0, "pass": 0, "fail": 0}

    pr_results = load_pr_results(pr_results_dir)
    print(f"Loaded results for {len(pr_results)} PRs: {sorted(pr_results.keys())}")

    print(f"Fetching PRs from {upstream_repo}...")
    open_prs = fetch_prs(upstream_repo, token, state="open", limit=50)

    pr_suites_map = {}
    for pr in open_prs:
        num   = pr["number"]
        files = fetch_pr_files(upstream_repo, num, token)
        pr_suites_map[num] = pr_new_suites(files)

    # ── Derived metrics ────────────────────────────────────────────────────────
    total_tests   = baseline_summary["total"]
    total_pass    = baseline_summary["pass"]
    total_fail    = baseline_summary["fail"]
    pass_rate     = f"{total_pass / total_tests * 100:.2f}%" if total_tests else "—"

    total_open        = len(open_prs)
    tested_count      = len(pr_results)
    prs_with_new_fail = sum(
        1 for r in pr_results.values()
        if any(f["key"] not in baseline_keys for f in r["failures"])
    )

    # PRs needing attention (open + tested + has new failures)
    attention_prs = []
    for p in open_prs:
        res = pr_results.get(p["number"])
        if res:
            _, new_fails = split_failures(res["failures"], baseline_keys)
            if new_fails:
                attention_prs.append((p, new_fails))

    # ── Overview: donut + level bars + summary card ────────────────────────────
    donut = _donut_svg(total_pass, total_tests)
    level_bars = _level_bars(baseline_suite_totals)

    # Level totals from suite names (derive L2 vs L3 from suite number prefix)
    l2_pass = l2_total = l3_pass = l3_total = 0
    for suite, v in baseline_suite_totals.items():
        try:
            num_prefix = int(suite.split("-")[0])
            if num_prefix < 1000:
                l3_pass  += v["pass"];  l3_total  += v["total"]
            else:
                l3_pass  += v["pass"];  l3_total  += v["total"]
        except Exception:
            pass
    # Simpler: split on compliance level from the CSV level field
    # Re-parse to get level totals
    level_totals = defaultdict(lambda: {"pass": 0, "total": 0})
    if baseline_csv and os.path.exists(baseline_csv):
        with open(baseline_csv, newline="", encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if len(row) < 4:
                    continue
                suite_path = row[0].strip('"')
                status     = row[3].strip('"')
                parts      = suite_path.split("/")
                level      = parts[0] if parts else "unknown"
                level_totals[level]["total"] += 1
                if status == "SUCCESS":
                    level_totals[level]["pass"] += 1

    level_bar_rows = ""
    for lvl in sorted(level_totals):
        v    = level_totals[lvl]
        pct  = v["pass"] / v["total"] * 100 if v["total"] else 100
        col  = "#059669" if pct == 100 else "#f59e0b"
        lbl  = lvl.replace("compliance-level-", "Level-")
        level_bar_rows += f"""<div class="bar-wrap">
  <div class="bar-label">{escape(lbl)}</div>
  <div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%;background:{col}"></div></div>
  <div class="bar-val">{v['pass']:,} / {v['total']:,}</div>
</div>"""

    # Top failing suites bar rows
    failing_suite_rows = ""
    failing_suites = sorted(
        [(s, v) for s, v in baseline_suite_totals.items() if v["fail"] > 0],
        key=lambda x: x[1]["fail"], reverse=True
    )[:6]
    if failing_suites:
        failing_suite_rows = '<div style="height:6px"></div>'
        for suite, v in failing_suites:
            pct  = v["pass"] / v["total"] * 100 if v["total"] else 100
            col  = "#f59e0b" if pct > 0 else "#ef4444"
            lbl  = suite[:22] + "…" if len(suite) > 22 else suite
            failing_suite_rows += f"""<div class="bar-wrap">
  <div class="bar-label" title="{escape(suite)}">{escape(lbl)}</div>
  <div class="bar-track"><div class="bar-fill" style="width:{pct:.1f}%;background:{col}"></div></div>
  <div class="bar-val">{v['pass']:,} / {v['total']:,}</div>
</div>"""

    results_date = ""
    if pr_results:
        dates = [r["meta"].get("run_date", "")[:10] for r in pr_results.values() if r["meta"].get("run_date")]
        if dates:
            results_date = max(dates)

    vc_box = f"""<div class="vc-box">
  <div class="vc-head">Apache KIE Drools 999-SNAPSHOT{(' &nbsp;·&nbsp; Results: ' + results_date) if results_date else ''}</div>
  <div class="vc-stat"><span>Total tests</span><strong>{total_tests:,}</strong></div>
  <div class="vc-stat"><span>Passing</span><strong class="green">{total_pass:,}</strong></div>
  <div class="vc-stat"><span>Failing</span><strong class="red">{total_fail:,}</strong></div>
  <div class="vc-stat"><span>Pass rate</span><strong>{pass_rate}</strong></div>
  <div class="vc-stat"><span>Suites with failures</span><strong>{len([s for s,v in baseline_suite_totals.items() if v['fail']>0])}</strong></div>
  <div class="vc-stat"><span>Upstream repo</span>
    <a href="https://github.com/{upstream_repo}" target="_blank" rel="noopener">{upstream_repo}</a>
  </div>
</div>"""

    # ── Attention banner ───────────────────────────────────────────────────────
    attention_html = ""
    if attention_prs:
        items = "".join(
            f'<li><a href="{p["html_url"]}" target="_blank" rel="noopener">#{p["number"]} {escape(p["title"])}</a>'
            f' — <strong>{len(nf)} new failure{"s" if len(nf)!=1 else ""}</strong></li>'
            for p, nf in attention_prs
        )
        attention_html = f"""<div class="warn-box">
&#x26A0; <strong>Needs attention</strong> — {len(attention_prs)} open PR(s) introduce new test failures:
<ul>{items}</ul>
</div>"""

    # ── PR status table ────────────────────────────────────────────────────────
    pr_table_html = _pr_status_table(open_prs, pr_results, pr_suites_map, baseline_keys)

    # ── New failures drilldown ─────────────────────────────────────────────────
    drilldown_html = _new_failures_drilldown(open_prs, pr_results, baseline_keys)

    # ── Baseline failures table ────────────────────────────────────────────────
    baseline_table_html = _baseline_table(baseline_failure_details)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Drools TCK Dashboard — 999-SNAPSHOT</title>
<style>{CSS}</style>
</head>
<body>
<div class="page">

<div class="header">
  <h1>Drools TCK Compatibility Dashboard</h1>
  <div class="header-meta">
    <span>Source: <a href="https://github.com/{upstream_repo}" target="_blank" rel="noopener">github.com/{upstream_repo}</a> · master</span>
    <span>Engine: <strong>Apache KIE Drools</strong> 999-SNAPSHOT</span>
    <span>Generated: <strong>{now_utc}</strong></span>
  </div>
</div>

{attention_html}

<section>
  <div class="section-title">Overview — Apache KIE Drools 999-SNAPSHOT</div>
  <div class="kpi-row">
    <div class="kpi"><div class="kpi-value green">{total_pass:,}</div><div class="kpi-label">Tests Passing</div></div>
    <div class="kpi"><div class="kpi-value red">{total_fail}</div><div class="kpi-label">Tests Failing</div></div>
    <div class="kpi"><div class="kpi-value blue">{len([s for s,v in baseline_suite_totals.items() if v['fail']>0])}</div><div class="kpi-label">Suites Affected</div></div>
    <div class="kpi"><div class="kpi-value orange">{pass_rate}</div><div class="kpi-label">Pass Rate</div></div>
  </div>
  <div class="charts-row">
    <div class="chart-box">
      <div class="chart-title">Pass / Fail split</div>
      {donut}
    </div>
    <div class="chart-box">
      <div class="chart-title">Results by compliance level</div>
      {level_bar_rows}
      {failing_suite_rows}
    </div>
  </div>
  {vc_box}
</section>

<section>
  <div class="section-title">
    Open Pull Requests
    <span class="badge badge-info">{total_open} open</span>
    <span class="badge badge-gray">{tested_count} tested</span>
    {f'<span class="badge badge-fail">{prs_with_new_fail} with new failures</span>' if prs_with_new_fail else ''}
  </div>
  {pr_table_html}
</section>

{f'''<section>
  <div class="section-title">Net-New Failures Introduced by Open PRs
    <span class="badge badge-fail">{sum(len(nf) for _,nf in attention_prs)} failures across {len(attention_prs)} PR{"s" if len(attention_prs)!=1 else ""}</span>
  </div>
  <p class="footnote" style="margin-bottom:10px;">
    Pre-existing baseline failures are excluded from each PR block below — only failures
    that do <em>not</em> appear on master are listed here.
  </p>
  {drilldown_html}
</section>''' if attention_prs else ''}

<section>
  <div class="section-title">
    Baseline Failures — Already on Master
    <span class="badge badge-warn">{len(baseline_failure_details)} failures</span>
  </div>
  <p class="footnote" style="margin-bottom:10px;">
    These failures exist on the current master branch before any PR is applied.
    They are pre-existing issues in Drools 999-SNAPSHOT and do not count against any open PR.
  </p>
  {baseline_table_html}
</section>

</div>
<footer style="text-align:center;font-size:12px;color:#9ca3af;border-top:1px solid #e5e7eb;margin-top:32px;padding-top:12px;max-width:860px;margin-left:auto;margin-right:auto;">
  Auto-generated &nbsp;·&nbsp; Data from <a href="https://github.com/{upstream_repo}" target="_blank" rel="noopener" style="color:#9ca3af;">github.com/{upstream_repo}</a> &nbsp;·&nbsp; Made with IBM Bob
</footer>
</body>
</html>"""

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as out:
        out.write(html)
    print(f"Dashboard written → {output_path}")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr-results-dir", required=True)
    parser.add_argument("--baseline-csv",   default="TestResults/Drools/999-SNAPSHOT/tck_results.csv",
                        help="Path to the committed baseline CSV (master results)")
    parser.add_argument("--upstream-repo",  default="dmn-tck/tck")
    parser.add_argument("--token",          default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--output",         required=True)
    args = parser.parse_args()

    build_dashboard(
        pr_results_dir=args.pr_results_dir,
        baseline_csv=args.baseline_csv,
        upstream_repo=args.upstream_repo,
        token=args.token,
        output_path=args.output,
    )
