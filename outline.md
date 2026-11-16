PRESENTATION OUTLINE
============================================================
Template: IBM-Template_AI-Ready.pptx
Total Slides: 6

Slide 2: cover_slide (COVER-02)
------------------------------------------------------------
• title: "Drools TCK Compatibility Dashboard demo" [39/70 chars] ✓ ⚠️ IBM-BRAND
• name_and_job_title: "DMN Compatibility & Automation Team" [35/40 chars] ✓
• contact_details: "Apache KIE Drools continuous integration" [40/50 chars] ✓

Slide 22: context_slide (CONTENT-2COL)
------------------------------------------------------------
• title: "Modernizing DMN compliance reviews for Drools" [45/80 chars] ✓
• body_copy_01: "Managing Technology Compatibility Kit (TCK) compliance was previously a highl..." [348/600 chars] ✓ ⚠️ IBM-BRAND
• body_copy_02: "The TCK Compatibility Dashboard fully automates upstream PR compatibility eva..." [327/600 chars] ✓ ⚠️ IBM-BRAND

Slide 11: baseline_stats (STATS-3UP)
------------------------------------------------------------
• title: "Current DMN compliance baseline for Drools 999-SNAPSHOT" [55/80 chars] ✓
• statistic_01: "4,200+" [6 chars]
• statistic_claim_01: "Total DMN TCK test cases executed against master branch" [55 chars]
• statistic_02: "9" [1 chars]
• statistic_claim_02: "Baseline failures on master across 4 specific test suites" [57 chars]
• statistic_03: "99.8%" [5 chars]
• statistic_claim_03: "Overall test pass rate representing solid specification compliance" [66 chars]
• statistic_sources: "Source: dmn-tck/tck master branch baseline test results" [55 chars]

Slide 28: pillars_grid (GRID-4UP-01)
------------------------------------------------------------
• header: "ENGINEERING DEEP DIVE" [21/30 chars] ✓
• title: "The four pillars of our automation pipeline" [43/80 chars] ✓
• body_copy_title_01: "1. Sync & triggers" [18/20 chars] ✓
• body_copy_01: "Runs weekly via a cron job or manually on-demand. Merges the latest upstream ..." [142/150 chars] ✓
• body_copy_title_02: "2. Smart caching" [16/20 chars] ✓
• body_copy_02: "Caches Maven dependencies and only compiles the necessary Drools modules from..." [155/150 chars] ⚠ ⚠️ IBM-BRAND
• body_copy_title_03: "3. Isolated testing" [19/20 chars] ✓
• body_copy_03: "Spins up temporary runner workspaces. Clones, merges, and tests each PR again..." [140/150 chars] ✓ ⚠️ IBM-BRAND
• body_copy_title_04: "4. Auto-publish" [15/20 chars] ✓
• body_copy_04: "Aggregates test run metadata and renders a self-contained, responsive HTML fi..." [132/150 chars] ✓

Slide 24: features_wins (CONTENT-2COL-HEADERS)
------------------------------------------------------------
• title: "Delivering highly actionable reviews for developers" [51/80 chars] ✓
• body_copy_title_01: "Regression noise isolation" [26/50 chars] ✓
• body_copy_01: "By correlating failures against master, we separate existing gaps from net-ne..." [280/600 chars] ✓
• body_copy_title_02: "Direct-to-PR links" [18/50 chars] ✓
• body_copy_02: "When net-new failures are found, reviewers get a detailed drilldown with Leve..." [249/600 chars] ✓ ⚠️ IBM-BRAND

Slide 6: qa_divider (SECTION-01)
------------------------------------------------------------
• title: "Questions & Answers" [19/60 chars] ✓

============================================================
VALIDATION SUMMARY
============================================================

Character Limits:
  ✓ = Within character limit
  ⚠ = At or near limit (90-110%)
  ✗ = Exceeds limit (requires truncation)

IBM Brand Guidelines:
  ⚠️ IBM-BRAND = High priority issue (capitalization)
  ℹ️ IBM-BRAND = Medium priority issue (quotation marks)


============================================================
IBM BRAND GUIDELINE ISSUES
============================================================

HIGH PRIORITY (Capitalization):
------------------------------------------------------------
• cover_slide - title
  Issue: Uses title case instead of sentence-case capitalization
  Suggested: Drools TCK compatibility dashboard demo

• context_slide - body_copy_01
  Issue: Uses title case instead of sentence-case capitalization
  Suggested: Managing technology compatibility kit (TCK) compliance was previously a highly manual, noisy process. since drools has known gaps on master (9 baseline failures), any failures on upstream pull requests (prs) were difficult to classify. reviewers had to manually run and compile tests to see if a PR broke drools, leading to slow integration cycles.

• context_slide - body_copy_02
  Issue: Uses title case instead of sentence-case capitalization
  Suggested: The TCK compatibility dashboard fully automates upstream PR compatibility evaluation. by isolating baseline failures from net-new regressions, it provides reviewers with an instant, noise-free health report on every single open PR. this enables faster, safer integration of the latest DMN standard tests into the drools engine.

• pillars_grid - body_copy_02
  Issue: Uses title case instead of sentence-case capitalization
  Suggested: Caches maven dependencies and only compiles the necessary drools modules from source. caches baseline test results to skip runs if TCK master is unchanged.

• pillars_grid - body_copy_03
  Issue: Uses title case instead of sentence-case capitalization
  Suggested: Spins up temporary runner workspaces. clones, merges, and tests each PR against drools. skips compilation and flags merge conflicts cleanly.

• features_wins - body_copy_02
  Issue: Uses title case instead of sentence-case capitalization
  Suggested: When net-new failures are found, reviewers get a detailed drilldown with level, suite, case ID, and failure message.
Rather than linking to master (which would 404), links point directly to the PR's exact head commit SHA, enabling instant debugging.

============================================================
Total Issues: 6

IBM Brand Guidelines:
• Use sentence-case capitalization (capitalize only first word and proper nouns)
• Wrap quote text in curly quotation marks ()
• Proper nouns: IBM, Watson, watsonx, Bob


============================================================
Next Steps:
1. Review the outline above
2. Verify all content is accurate
3. Check character counts for any ✗ or ⚠ indicators
4. Fix any IBM brand guideline issues (⚠️ or ℹ️ indicators)
5. Approve to proceed with generation
