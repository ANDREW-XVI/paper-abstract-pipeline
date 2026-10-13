#!/usr/bin/env python3
"""Add real abstracts to a CSV of papers you already have.

  python find_abstracts.py --input papers.csv --output papers_with_abstracts.csv \
      --title-col "Paper title" --link-col "Link" [--year-col Year]

The link column may hold a DOI URL, an arXiv URL or a Semantic Scholar URL. Papers with no
abstract found get:  Abstract not available – see <link>   (Abstract Source = none).
Resumable: progress is kept in <output>.progress.jsonl.
"""
import argparse, csv, json, pathlib, re, sys
from paper_abstracts import common
from paper_abstracts.sources import find_abstract

def ids_from(link, venue=""):
    doi = arxiv = s2 = None
    m = re.search(r"doi\.org/(10\.\d{4,9}/[^\s?#]+)", link or "")
    if m:
        doi = m.group(1)
    m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", link or "") or re.search(r"arXiv:(\d{4}\.\d{4,5})", venue or "")
    if m:
        arxiv = m.group(1)
    if doi and doi.lower().startswith("10.48550/arxiv."):
        arxiv = arxiv or doi.split(".", 2)[-1].split("arXiv.")[-1].split("arxiv.")[-1]
    if arxiv and not doi:
        doi = "10.48550/arXiv." + arxiv
    m = re.search(r"semanticscholar\.org/paper/([0-9a-f]{40})", link or "")
    if m:
        s2 = m.group(1)
    return doi, arxiv, s2

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--title-col", default="Title")
    ap.add_argument("--link-col", default="Link")
    ap.add_argument("--year-col", default="Year")
    ap.add_argument("--venue-col", default="Venue")
    a = ap.parse_args()
    out = pathlib.Path(a.output)
    prog = pathlib.Path(str(out) + ".progress.jsonl")
    common.LOGFILE = str(out) + ".log"
    done = {}
    if prog.exists():
        for line in open(prog, encoding="utf-8"):
            j = json.loads(line)
            done[j["i"]] = j
    rows = list(csv.DictReader(open(a.input, encoding="utf-8-sig", newline="")))
    common.log(f"{len(rows)} papers, {len(done)} already done")
    cache = {}
    for i, r in enumerate(rows):
        if i in done:
            continue
        title, link = r.get(a.title_col, ""), r.get(a.link_col, "")
        common.log(f"[{i + 1}/{len(rows)}] {title[:90]}")
        key = common.norm_title(title)
        if key in cache:
            abstract, src = cache[key]
        else:
            doi, arxiv, s2 = ids_from(link, r.get(a.venue_col, ""))
            abstract, src = find_abstract(title, doi, arxiv, r.get(a.year_col), s2)
            if not abstract:
                abstract, src = f"Abstract not available – see {link}", "none"
            cache[key] = (abstract, src)
        common.log(f"    -> {src}")
        j = {"i": i, "a": abstract, "s": src}
        done[i] = j
        with open(prog, "a", encoding="utf-8") as f:
            f.write(json.dumps(j, ensure_ascii=False) + "\n")
    fields = list(rows[0].keys()) + ["Abstract", "Abstract Source"]
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, r in enumerate(rows):
            w.writerow({**r, "Abstract": done[i]["a"], "Abstract Source": done[i]["s"]})
    from collections import Counter
    common.log(f"DONE -> {out}  sources: {dict(Counter(d['s'] for d in done.values()))}")

if __name__ == "__main__":
    sys.exit(main())
