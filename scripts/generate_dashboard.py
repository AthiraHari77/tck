#!/usr/bin/env python3
"""
BAMOE TCK Dashboard Generator
Reads per-PR result folders + queries upstream GitHub API for open PRs.
Produces a self-contained HTML dashboard.

Usage:
    python3 scripts/generate_dashboard.py \
        --pr-results-dir pr-results \
        --upstream-repo  dmn-tck/tck \
        --token          $GITHUB_TOKEN \
        --output         docs/drools-dashboard.html
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

            parts  = suite_path.split("/")
            level  = parts[0].replace("compliance-level-", "L") if parts else "?"
            suite  = parts[1] if len(parts) >= 2 else suite_path

            suite_totals[suite]["total"] += 1
            if status == "SUCCESS":
                suite_totals[suite]["pass"] += 1
            else:
                suite_totals[suite]["fail"] += 1
                failures.append({
                    "suite": suite, "level": level,
                    "case_id": case_id, "test": test_name,
                    "message": message, "suite_path": suite_path,
                })

    total  = sum(v["total"] for v in suite_totals.values())
    passed = sum(v["pass"]  for v in suite_totals.values())
    failed = sum(v["fail"]  for v in suite_totals.values())
    return dict(suite_totals), failures, {"total": total, "pass": passed, "fail": failed}


# ─────────────────────────────────────────────────────────────────────────────
# Load per-PR results from disk
# ─────────────────────────────────────────────────────────────────────────────

def load_pr_results(pr_results_dir):
    """
    Returns dict: { pr_number(int): { meta, suite_totals, failures, summary } }
    """
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
.page { max-width: 920px; margin: 0 auto; }
.header { border-bottom: 2px solid #e5e7eb; padding-bottom: 14px; margin-bottom: 24px; }
.header h1 { font-size: 20px; font-weight: 700; }
.header-meta { font-size: 12px; color: #57606a; margin-top: 6px; display: flex; flex-wrap: wrap; gap: 6px 20px; }
.header-meta a { color: #3b82d4; }
section { margin-bottom: 32px; }
.section-title { font-size: 11px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase;
  color: #57606a; border-bottom: 1px solid #e5e7eb; padding-bottom: 5px; margin-bottom: 14px; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 12px; font-size: 11px; font-weight: 600;
  vertical-align: middle; white-space: nowrap; }
.badge-fail    { background: #fee2e2; color: #991b1b; }
.badge-pass    { background: #d1fae5; color: #065f46; }
.badge-info    { background: #dbeafe; color: #1e40af; }
.badge-purple  { background: #ede9fe; color: #5b21b6; }
.badge-gray    { background: #f3f4f6; color: #374151; }
.badge-orange  { background: #ffedd5; color: #9a3412; }
.badge-merged  { background: #d1fae5; color: #065f46; }
.kpi-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 16px; }
.kpi { background: #f7f8fa; border: 1px solid #e5e7eb; border-radius: 6px; padding: 14px 12px; text-align: center; }
.kpi-value { font-size: 26px; font-weight: 700; line-height: 1.15; }
.kpi-label { font-size: 11px; color: #57606a; margin-top: 3px; }
.green { color: #065f46; } .red { color: #991b1b; } .orange { color: #92400e; } .blue { color: #1e40af; }
.table-wrap { overflow-x: auto; border: 1px solid #e5e7eb; border-radius: 6px; margin-bottom: 10px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
thead th { background: #f7f8fa; text-align: left; padding: 8px 10px; font-size: 11px; font-weight: 700;
  text-transform: uppercase; letter-spacing: .04em; color: #57606a; border-bottom: 1px solid #e5e7eb; white-space: nowrap; }
tbody tr { border-bottom: 1px solid #f0f1f3; }
tbody tr:last-child { border-bottom: none; }
tbody td { padding: 8px 10px; vertical-align: top; }
tbody tr:hover { background: #fafbfc; }
.mono { font-family: "SFMono-Regular", Consolas, monospace; font-size: 12px; }
code { font-family: "SFMono-Regular", Consolas, monospace; font-size: 11px;
  background: #f3f4f6; padding: 1px 4px; border-radius: 3px; word-break: break-all; }
.pr-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.pr-card { background: #f7f8fa; border: 1px solid #e5e7eb; border-radius: 6px; padding: 12px 14px; }
.pr-card.has-failures { border-left: 3px solid #ef4444; }
.pr-card.all-pass     { border-left: 3px solid #059669; }
.pr-card.not-tested   { border-left: 3px solid #d1d5db; }
.pr-title { font-weight: 600; font-size: 13px; margin-bottom: 4px; }
.pr-title a { color: #3b82d4; text-decoration: none; }
.pr-title a:hover { text-decoration: underline; }
.pr-meta { font-size: 11px; color: #57606a; display: flex; flex-wrap: wrap; gap: 5px; align-items: center; margin-bottom: 6px; }
.pr-suites { display: flex; flex-wrap: wrap; gap: 3px; margin-top: 4px; }
.pr-result { font-size: 12px; margin-top: 6px; padding-top: 6px; border-top: 1px solid #e5e7eb; }
.pr-result.fail { color: #991b1b; }
.pr-result.pass { color: #065f46; }
.pr-result.pending { color: #57606a; font-style: italic; }
.fail-detail { margin-top: 8px; }
.fail-row { font-size: 11px; padding: 3px 0; border-bottom: 1px solid #f3f4f6; display: flex; gap: 8px; flex-wrap: wrap; }
.fail-row:last-child { border-bottom: none; }
.attention-box { background: #fff7ed; border: 1px solid #fed7aa; border-radius: 6px;
  padding: 12px 14px; font-size: 13px; color: #9a3412; margin-bottom: 14px; }
.bar-wrap { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.bar-label { font-size: 12px; color: #57606a; min-width: 80px; }
.bar-track { flex: 1; height: 12px; background: #e5e7eb; border-radius: 3px; overflow: hidden; }
.bar-fill  { height: 100%; border-radius: 3px; }
.bar-val   { font-size: 11px; color: #57606a; min-width: 58px; text-align: right; }
"""


def status_badge(fail_count, tested):
    if not tested:
        return '<span class="badge badge-gray">not tested</span>'
    if fail_count == 0:
        return '<span class="badge badge-pass">all pass</span>'
    return f'<span class="badge badge-fail">{fail_count} failure{"s" if fail_count != 1 else ""}</span>'


def pr_card(pr, pr_result, suites, upstream_repo):
    number  = pr["number"]
    title   = escape(pr["title"])
    url     = pr["html_url"]
    author  = escape(pr.get("user", {}).get("login", ""))
    updated = (pr.get("updated_at") or "")[:10]
    merged  = pr.get("merged_at")
    state   = pr["state"]

    state_badge = '<span class="badge badge-merged">merged</span>' if merged else \
                  '<span class="badge badge-gray">closed</span>' if state == "closed" else \
                  '<span class="badge badge-info">open</span>'

    suite_chips = "".join(
        f'<span class="badge badge-purple">{escape(s)}</span>'
        for s in sorted(suites)
    ) if suites else ""

    tested = pr_result is not None
    fail_count = pr_result["summary"]["fail"] if tested else 0
    pass_count = pr_result["summary"]["pass"] if tested else 0
    total      = pr_result["summary"]["total"] if tested else 0
    run_date   = pr_result["meta"].get("run_date", "")[:10] if tested else ""
    drools_sha = pr_result["meta"].get("drools_sha", "") if tested else ""

    card_class = "has-failures" if (tested and fail_count > 0) else \
                 "all-pass"     if (tested and fail_count == 0) else \
                 "not-tested"

    # Show top 3 failures inline
    fail_rows = ""
    if tested and fail_count > 0:
        for f in pr_result["failures"][:3]:
            fail_rows += f"""<div class="fail-row">
  <span class="badge badge-gray">{escape(f['level'])}</span>
  <span class="mono">{escape(f['suite'])}</span>
  <span class="mono">{escape(f['case_id'])}</span>
  <code>{escape(f['message'][:80])}{'…' if len(f['message']) > 80 else ''}</code>
</div>"""
        if fail_count > 3:
            fail_rows += f'<div class="fail-row" style="color:#57606a;font-size:11px;">… and {fail_count - 3} more — see full table below</div>'

    result_html = ""
    if tested:
        res_class = "fail" if fail_count > 0 else "pass"
        result_html = f"""<div class="pr-result {res_class}">
  {status_badge(fail_count, tested)} &nbsp;
  {pass_count:,} / {total:,} passed
  &nbsp;·&nbsp; tested {run_date}
  &nbsp;·&nbsp; <code>{escape(drools_sha)}</code>
  {('<div class="fail-detail">' + fail_rows + '</div>') if fail_rows else ''}
</div>"""
    else:
        result_html = '<div class="pr-result pending">Not yet tested against Drools 999-SNAPSHOT</div>'

    return f"""<div class="pr-card {card_class}">
  <div class="pr-title"><a href="{url}" target="_blank" rel="noopener">#{number} {title}</a></div>
  <div class="pr-meta">
    {state_badge}
    <span>{escape(author)}</span>
    <span>{updated}</span>
    {('<div class="pr-suites">' + suite_chips + '</div>') if suite_chips else ''}
  </div>
  {result_html}
</div>"""


def full_failures_table(all_failures_by_pr):
    """Renders the full failure table across all tested PRs."""
    if not all_failures_by_pr:
        return '<div style="color:#057a55;font-size:13px;padding:10px 0;">&#x2705; No failures across all tested PRs.</div>'

    rows = ""
    for pr_num, failures in sorted(all_failures_by_pr.items()):
        for f in failures:
            gh_url = f"https://github.com/dmn-tck/tck/tree/master/TestCases/{escape(f['suite_path'])}"
            rows += f"""<tr>
  <td><span class="badge badge-info">PR #{pr_num}</span></td>
  <td class="mono" style="white-space:nowrap;">
    <span class="badge badge-gray">{escape(f['level'])}</span>&nbsp;
    <a href="{gh_url}" target="_blank" rel="noopener">{escape(f['suite'])}</a>
  </td>
  <td class="mono">{escape(f['case_id'])}</td>
  <td class="mono">{escape(f['test'])}</td>
  <td><code>{escape(f['message'])}</code></td>
</tr>"""

    return f"""<div class="table-wrap"><table>
  <thead><tr><th>PR</th><th>Suite</th><th>Case ID</th><th>Test</th><th>Failure Message</th></tr></thead>
  <tbody>{rows}</tbody>
</table></div>"""


# ─────────────────────────────────────────────────────────────────────────────
# Main builder
# ─────────────────────────────────────────────────────────────────────────────

def build_dashboard(pr_results_dir, upstream_repo, token, output_path):
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Load all per-PR results from disk
    pr_results = load_pr_results(pr_results_dir)
    print(f"Loaded results for {len(pr_results)} PRs: {sorted(pr_results.keys())}")

    # Fetch upstream PRs
    print(f"Fetching PRs from {upstream_repo}...")
    all_prs = fetch_prs(upstream_repo, token, state="all", limit=60)

    # For each PR get files changed
    pr_suites_map = {}
    for pr in all_prs:
        num = pr["number"]
        files = fetch_pr_files(upstream_repo, num, token)
        pr_suites_map[num] = pr_new_suites(files)

    open_prs   = [p for p in all_prs if p["state"] == "open"]
    merged_prs = [p for p in all_prs if p.get("merged_at")][:10]

    # KPI counts
    total_open     = len(open_prs)
    open_with_tests = sum(1 for p in open_prs if pr_suites_map.get(p["number"]))
    tested_count   = len(pr_results)
    prs_with_fail  = sum(1 for r in pr_results.values() if r["summary"]["fail"] > 0)

    # Attention — open PRs with failures
    attention_prs = [p for p in open_prs
                     if p["number"] in pr_results and pr_results[p["number"]]["summary"]["fail"] > 0]

    # All failures grouped by PR
    all_failures_by_pr = {num: data["failures"]
                          for num, data in pr_results.items()
                          if data["failures"]}

    # ── Build HTML ────────────────────────────────────────────────────────

    # Attention box
    attention_html = ""
    if attention_prs:
        items = "".join(
            f'<li><a href="{p["html_url"]}" target="_blank" rel="noopener">#{p["number"]} {escape(p["title"])}</a>'
            f' — <strong>{pr_results[p["number"]]["summary"]["fail"]} failure(s)</strong></li>'
            for p in attention_prs
        )
        attention_html = f'<div class="attention-box">&#x26A0;&#xFE0F; <strong>Needs attention</strong> — {len(attention_prs)} open PR(s) have test failures:<ul style="margin-top:6px;padding-left:18px;">{items}</ul></div>'

    # KPIs
    kpis = f"""<div class="kpi-row">
  <div class="kpi"><div class="kpi-value blue">{total_open}</div><div class="kpi-label">Open Upstream PRs</div></div>
  <div class="kpi"><div class="kpi-value orange">{open_with_tests}</div><div class="kpi-label">PRs Adding Tests</div></div>
  <div class="kpi"><div class="kpi-value green">{tested_count}</div><div class="kpi-label">PRs Tested</div></div>
  <div class="kpi"><div class="kpi-value red">{prs_with_fail}</div><div class="kpi-label">PRs With Failures</div></div>
</div>"""

    # Open PRs board
    open_cards = "".join(
        pr_card(p, pr_results.get(p["number"]), pr_suites_map.get(p["number"], set()), upstream_repo)
        for p in open_prs
    ) or '<div style="color:#57606a;font-size:13px;padding:10px 0;">No open upstream PRs.</div>'

    # Merged PRs board
    merged_cards = "".join(
        pr_card(p, pr_results.get(p["number"]), pr_suites_map.get(p["number"], set()), upstream_repo)
        for p in merged_prs
    ) or '<div style="color:#57606a;font-size:13px;padding:10px 0;">No recently merged PRs.</div>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BAMOE TCK Dashboard</title>
<style>{CSS}</style>
</head>
<body>
<div class="page">

<div class="header">
  <h1>BAMOE TCK Compatibility Dashboard</h1>
  <div class="header-meta">
    <span>Engine: <strong>Apache KIE Drools 999-SNAPSHOT</strong></span>
    <span>Upstream: <a href="https://github.com/{upstream_repo}" target="_blank" rel="noopener">{upstream_repo}</a></span>
    <span>Generated: <strong>{now_utc}</strong></span>
  </div>
</div>

{attention_html}

<section>
  <div class="section-title">Overview</div>
  {kpis}
</section>

<section>
  <div class="section-title">Open Upstream PRs
    <span class="badge badge-info" style="margin-left:6px;">{total_open} open</span>
    <span class="badge badge-purple" style="margin-left:4px;">{open_with_tests} add tests</span>
  </div>
  <div class="pr-grid">{open_cards}</div>
</section>

<section>
  <div class="section-title">Recently Merged PRs</div>
  <div class="pr-grid">{merged_cards}</div>
</section>

<section>
  <div class="section-title">All Failures Across Tested PRs
    <span class="badge badge-fail" style="margin-left:6px;">{sum(len(v) for v in all_failures_by_pr.values())} total</span>
  </div>
  {full_failures_table(all_failures_by_pr)}
</section>

</div>
<footer style="text-align:center;font-size:12px;color:#9ca3af;border-top:1px solid #e5e7eb;
  margin-top:32px;padding-top:12px;max-width:920px;margin-left:auto;margin-right:auto;">
  BAMOE TCK Dashboard &nbsp;·&nbsp; Auto-generated by CI &nbsp;·&nbsp;
  <a href="https://github.com/{upstream_repo}" target="_blank" rel="noopener" style="color:#9ca3af;">{upstream_repo}</a>
  &nbsp;·&nbsp; Made with IBM Bob
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
    parser.add_argument("--upstream-repo",  default="dmn-tck/tck")
    parser.add_argument("--token",          default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--output",         required=True)
    args = parser.parse_args()

    build_dashboard(
        pr_results_dir=args.pr_results_dir,
        upstream_repo=args.upstream_repo,
        token=args.token,
        output_path=args.output,
    )
