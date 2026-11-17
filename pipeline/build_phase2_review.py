#!/usr/bin/env python3
"""Build the Phase 2 review page: what came out, and what needs a decision."""

import html
import json
import sys
from collections import Counter
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "build/full2")
data = json.loads((OUT / "entries.json").read_text(encoding="utf-8"))
issues = json.loads((OUT / "issues.json").read_text(encoding="utf-8"))
candidates = json.loads((OUT / "candidates.json").read_text(encoding="utf-8"))
summary, entries = data["summary"], data["entries"]

alpha = [i for i in issues if i["code"] == "alpha_order"]
by_letter = summary["letters"]
peak = max(by_letter.values())

css = """
*{box-sizing:border-box}
body{margin:0;font:15px/1.65 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
 background:#15130f;color:#e8e3d8}
.wrap{max-width:1080px;margin:0 auto;padding:30px 28px 70px}
h1{font-size:21px;margin:0 0 4px;font-weight:600}
h2{font-size:15px;margin:38px 0 12px;font-weight:600;letter-spacing:.3px;
 text-transform:uppercase;color:#a89e8a}
.sub{color:#948d7e;font-size:13.5px;margin-bottom:22px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;
 margin:18px 0 6px}
.stat{background:#1d1a14;border:1px solid #2e2820;border-radius:6px;padding:13px 15px}
.stat b{display:block;font-size:23px;font-weight:600}
.stat span{font-size:10.5px;text-transform:uppercase;letter-spacing:.9px;color:#8a8273}
.stat.good b{color:#9ccf9c}.stat.warn b{color:#e0c07a}
p{color:#bdb6a6;font-size:14px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
th{text-align:left;color:#8a8273;font-weight:500;font-size:10.5px;text-transform:uppercase;
 letter-spacing:.8px;padding:7px 10px;border-bottom:1px solid #2e2820}
td{padding:7px 10px;border-bottom:1px solid #221e18;color:#cdc6b6;vertical-align:top}
td.n{color:#8a8273;white-space:nowrap;font-variant-numeric:tabular-nums}
.bars{display:flex;align-items:flex-end;gap:4px;height:120px;margin-top:10px;
 padding:10px;background:#1d1a14;border:1px solid #2e2820;border-radius:6px}
.bar{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;
 height:100%;gap:4px}
.bar i{display:block;width:100%;background:#6f8f6c;border-radius:2px 2px 0 0}
.bar u{font-size:9.5px;color:#8a8273;text-decoration:none}
.hw{color:#f0c987}
.q{color:#9c9382;font-style:italic}
details{margin-top:10px;background:#1d1a14;border:1px solid #2e2820;border-radius:6px;
 padding:12px 15px}
summary{cursor:pointer;color:#c8bfa8;font-size:13.5px;font-weight:500}
.note{background:#1e1a22;border:1px solid #3a2f44;border-radius:6px;padding:14px 16px;
 margin-top:12px;font-size:13.5px;color:#cbbfd6}
"""

parts = [
    "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
    "<meta name='viewport' content='width=device-width,initial-scale=1'>",
    "<title>Phase 2 — full extraction</title>",
    f"<style>{css}</style></head><body><div class='wrap'>",
    "<h1>Phase 2 &mdash; full extraction</h1>",
    "<div class='sub'>All 946 pages of Mackey's <em>Encyclopaedia of Freemasonry</em> "
    "(1912), OCR'd and parsed.</div>",
    "<div class='stats'>",
]
for label, value, cls in [
    ("entries", f"{summary['entries']:,}", "good"),
    ("flagged candidates", f"{summary['rejected_candidates']:,}", "warn"),
    ("body text", f"{summary['total_body_chars']/1e6:.1f} MB", ""),
    ("mean OCR conf", f"{summary['mean_confidence']}%", "good"),
    ("ordering errors", f"{len(alpha):,}", "warn"),
    ("multi-page entries", f"{summary['multi_page_entries']:,}", ""),
]:
    parts.append(f"<div class='stat {cls}'><b>{value}</b><span>{label}</span></div>")
parts.append("</div>")

parts.append("<h2>Entries per letter</h2><div class='bars'>")
for letter, count in by_letter.items():
    height = max(3, round(100 * count / peak))
    parts.append(f"<div class='bar' title='{letter}: {count}'>"
                 f"<i style='height:{height}%'></i><u>{letter}</u></div>")
parts.append("</div>")

parts.append("<h2>Pages by region</h2><table><tr><th>Region</th><th>Pages</th>"
             "<th>Handling</th></tr>")
for region, count in summary["regions"].items():
    how = {"main": "Parsed into entries",
           "pronouncing": "Not yet parsed — three-column table, own parser needed",
           "bibliography": "Not yet parsed — author and works list",
           "plate": "Skipped (illustrations)",
           "failed": "OCR failed"}.get(region, "")
    parts.append(f"<tr><td>{region}</td><td class='n'>{count}</td><td>{how}</td></tr>")
parts.append("</table>")

parts.append("<h2>Ordering errors &mdash; what needs correcting</h2>")
parts.append(f"<p>{len(alpha)} headwords break alphabetical order. Each is either an OCR "
             "misread or a segmentation slip, and each is the correction pass's work "
             "list. A sample:</p>")
parts.append("<table><tr><th>PDF page</th><th>Entry</th></tr>")
for issue in alpha[:70]:
    parts.append(f"<tr><td class='n'>{issue['pdf_page']}</td>"
                 f"<td>{html.escape(issue['detail'][:150])}</td></tr>")
parts.append("</table>")
if len(alpha) > 70:
    parts.append(f"<p class='q'>&hellip; and {len(alpha)-70} more, in issues.json.</p>")

parts.append("<h2>Flagged candidates</h2>")
parts.append(
    f"<p>{len(candidates)} spans looked like headwords by weight but had no sentence "
    "ending before them. Most are italic book titles that volume 2's heavier scan "
    "rendered as thick as bold; some are real headwords whose preceding full stop the "
    "OCR dropped. They are held back from the dictionary rather than deleted, because "
    "a missing headword is invisible to someone searching for it while a spurious one "
    "can simply be struck out.</p>")
sample = [c for c in candidates if len(c["headword"]) > 4][:40]
parts.append("<table><tr><th>PDF page</th><th>Candidate</th></tr>")
for candidate in sample:
    parts.append(f"<tr><td class='n'>{candidate['pdf_page']}</td>"
                 f"<td>{html.escape(candidate['headword'][:110])}</td></tr>")
parts.append("</table>")

parts.append("<h2>Longest entries</h2>")
parts.append("<p>Mackey writes some very long articles. These were checked against the "
             "page images and are genuine, not runs of missed headwords.</p>")
parts.append("<table><tr><th>Chars</th><th>PDF page</th><th>Headword</th></tr>")
for entry in sorted(entries, key=lambda e: -len(e["body"]))[:10]:
    parts.append(f"<tr><td class='n'>{len(entry['body']):,}</td>"
                 f"<td class='n'>{entry['pdf_page']}</td>"
                 f"<td class='hw'>{html.escape(entry['headword'])}</td></tr>")
parts.append("</table>")

parts.append("<h2>Sample entries</h2>")
mid = [e for e in entries if 200 < len(e["body"]) < 700]
parts.append("<table><tr><th>Headword</th><th>Definition</th><th>Page</th></tr>")
for entry in mid[::max(1, len(mid)//22)][:22]:
    parts.append(f"<tr><td class='hw'>{html.escape(entry['headword'])}</td>"
                 f"<td>{html.escape(entry['body'][:260])}&hellip;</td>"
                 f"<td class='n'>{entry['printed_page'] or '—'}</td></tr>")
parts.append("</table>")

parts.append(
    "<div class='note'><b>Known gap.</b> Volume 1 yields 4.6 entries a page, volume 2 "
    "only 3.4. The two volumes were scanned separately and volume 2 is heavier, which "
    "blurs the weight difference between bold and italic that entry detection depends "
    "on. The flagged candidates are mostly from volume 2, and recovering the real "
    "headwords among them is the single biggest quality win available in Phase 3.</div>")

parts.append("</div></body></html>")
(OUT / "phase2.html").write_text("".join(parts), encoding="utf-8")
print("wrote", OUT / "phase2.html")
