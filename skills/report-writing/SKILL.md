---
name: report-writing
description: Write original research reports (PDF + markdown) grounded in verified claims, with source links and limits stated.
version: 1.0.0
---
# Report writing procedure
1. Use only claims with status=verified from the fact-check report; link each finding to claim IDs.
2. Structure: title, dated summary, key findings (claim-linked), claim verification list, sources (publisher/title/URL/timestamps), methodology & limits.
3. Never invent facts to fill gaps; mark unknowns as unknowns. Fixture runs are labeled fixture.
4. English default; Bengali when language=bn (PDF needs DOC_FONT_TTF for Bengali glyphs).
5. Render report.pdf via the PDF provider; verify pages (count, A4 size, non-empty, title, sources, links, readability) and record findings.
6. Save report.md + report.pdf in the job namespace; return summary + artifact refs.
