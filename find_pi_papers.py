#!/usr/bin/env python3
"""For each researcher, find their newest papers (default: 3 papers from 2024+) with real abstracts.

  python find_pi_papers.py --input examples/sample_pis.csv --out-dir out/

Input CSV columns: University, PI Name, Research Focus   (any extra columns are carried through).
Output (in --out-dir):  papers.csv  and  status.csv  (OK / PARTIAL / NO_MATCH / SKIPPED, with a reason).
Resumable: finished researchers are skipped; use --retry-failed to redo SKIPPED / NO_MATCH / empty ones.
"""
import argparse, csv, pathlib
from paper_abstracts import common
from paper_abstracts.pi_papers import find_papers

PAPER_COLS = ["University", "PI Name", "Paper Rank", "Title", "Year", "Publication Date", "Venue",
              "DOI or URL", "Abstract", "Abstract Source", "Author ID", "Profile Source"]
STATUS_COLS = ["University", "PI Name", "Status", "Reason"]

def append(path, cols, rows):
    new = not path.exists() or path.stat().st_size == 0
    with open(path, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(cols)
        w.writerows(rows)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--since-year", type=int, default=2024)
    ap.add_argument("--papers", type=int, default=3, help="papers per researcher")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--retry-failed", action="store_true")
    a = ap.parse_args()
    out = pathlib.Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    common.LOGFILE = str(out / "run.log")
    pf, sf = out / "papers.csv", out / "status.csv"
    last = {}
    if sf.exists():
        for r in csv.DictReader(open(sf, encoding="utf-8-sig", newline="")):
            last[(r["University"], r["PI Name"])] = r["Status"]
    have = set()
    if pf.exists():
        have = {(r["University"], r["PI Name"]) for r in csv.DictReader(open(pf, encoding="utf-8-sig", newline=""))}
    done = {k for k, st in last.items()
            if not (a.retry_failed and (st in ("SKIPPED", "NO_MATCH") or (st == "PARTIAL" and k not in have)))}
    people = [r for r in csv.DictReader(open(a.input, encoding="utf-8-sig", newline=""))
              if (r["University"], r["PI Name"]) not in done]
    if a.limit:
        people = people[:a.limit]
    common.log(f"{len(people)} researchers to process")
    for n, r in enumerate(people, 1):
        uni, name = r["University"], r["PI Name"]
        common.log(f"[{n}/{len(people)}] {name} | {uni}")
        try:
            papers, source, note = find_papers(name, uni, r.get("Research Focus", ""), a.since_year, a.papers)
            if not papers:
                status, reason = "NO_MATCH", "no verified profile with recent papers"
            else:
                miss = sum(p["abstract_source"] == "none" for p in papers)
                status = "OK" if len(papers) >= a.papers and not miss else "PARTIAL"
                reason = f"{source}: {note}" + (f"; {miss} abstract(s) not available" if miss else "") + \
                         (f"; only {len(papers)} paper(s)" if len(papers) < a.papers else "")
                append(pf, PAPER_COLS, [[uni, name, k, p["title"], p["year"], p["date"], p["venue"], p["url"],
                                         p["abstract"], p["abstract_source"], p.get("author_id", ""), source]
                                        for k, p in enumerate(papers, 1)])
        except common.ApiFail as e:
            status, reason = "SKIPPED", str(e)
        append(sf, STATUS_COLS, [[uni, name, status, reason]])
        common.log(f"    -> {status}  {reason}")

if __name__ == "__main__":
    main()
