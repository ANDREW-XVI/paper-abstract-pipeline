"""Find a researcher's newest papers: OpenAlex first, Semantic Scholar as the fallback.
A profile is accepted only if its NAME, UNIVERSITY and RESEARCH TOPIC all check out."""
import re, time
from .common import ApiFail, fetch, log, ws, norm_title
from .identity import name_compatible, name_tokens, university_matcher, keywords, topic_score
from .sources import oa_get, oa_rebuild, S2, S2_KEY, find_abstract

BAD_OA_TYPES = {"editorial", "letter", "erratum", "paratext", "retraction", "peer-review", "dataset",
                "book", "dissertation", "report", "standard", "grant"}
BAD_TITLE = re.compile(r"\b(erratum|errata|corrigendum|correction to|correction:|retraction|book review|editorial|"
                       r"thesis|dissertation|addendum|publisher correction)\b", re.I)
OA_SELECT = "id,title,publication_year,publication_date,doi,type,primary_location,abstract_inverted_index"
S2_FIELDS = "title,year,publicationDate,venue,externalIds,abstract,publicationTypes"

_s2_cooldown_until = 0.0
_oa_cooldown_until = 0.0

def _paper(title, year, date, venue, doi, arxiv, abstract, url, bad=False):
    doi = (doi or "").replace("https://doi.org/", "").lower() or None
    if doi and not arxiv:
        m = re.match(r"10\.48550/arxiv\.(.+)$", doi)
        arxiv = m.group(1) if m else None
    link = ("https://doi.org/" + doi) if doi else (("https://arxiv.org/abs/" + arxiv) if arxiv else url)
    return {"title": ws(title), "year": year or 0, "date": date or "", "venue": ws(venue), "doi": doi,
            "arxiv": arxiv, "abstract": abstract, "url": link, "bad": bad or bool(BAD_TITLE.search(title or ""))}

# ---------------------------------------------------------------- OpenAlex
def oa_works(aid, since, n):
    d = oa_get("/works", strict=True, filter=f"author.id:{aid},from_publication_date:{since}",
               sort="publication_date:desc", select=OA_SELECT, **{"per-page": n})
    out = []
    for w in (d or {}).get("results", []):
        if not w.get("title"):
            continue
        loc = w.get("primary_location") or {}
        out.append(_paper(w["title"], w.get("publication_year"), w.get("publication_date"),
                          (loc.get("source") or {}).get("display_name"), w.get("doi"), None,
                          oa_rebuild(w.get("abstract_inverted_index")),
                          loc.get("landing_page_url") or w["id"], bad=w.get("type") in BAD_OA_TYPES))
    return out

def oa_resolve(name, uni, focus):
    d = oa_get("/authors", strict=True, search=" ".join(name_tokens(name)),
               select="id,display_name,works_count,affiliations,last_known_institutions", **{"per-page": 15})
    match, fkw = university_matcher(uni), keywords(focus)
    cands = []
    for c in (d or {}).get("results", []):
        if not name_compatible(name, c.get("display_name", "")):
            continue
        inst = [a.get("institution", {}).get("display_name", "") for a in c.get("affiliations") or []]
        inst += [i.get("display_name", "") for i in c.get("last_known_institutions") or []]
        if any(match(x) for x in inst):
            cands.append(c)
    cands.sort(key=lambda c: -(c.get("works_count") or 0))
    ids, weak = [], set()
    for c in cands[:4]:
        aid = c["id"].split("/")[-1]
        t, ta = topic_score(fkw, oa_works(aid, "2021-01-01", 15))
        if t >= 2 or ta >= 4:
            ids.append(aid)
            if t < 3:
                weak.add(aid)   # maybe a merged profile: every paper must itself fit the topic
    return ids, weak

# ---------------------------------------------------------------- Semantic Scholar
def s2_get(path, **params):
    headers = {"x-api-key": S2_KEY} if S2_KEY else None
    return fetch("s2", S2 + path, 1.2 if S2_KEY else 3.0, params=params, headers=headers, tries=2, strict=True)

def s2_works(aid, since_year):
    d = s2_get(f"/author/{aid}/papers", fields=S2_FIELDS, limit=100)
    out = []
    for w in (d or {}).get("data", []):
        if not w.get("title") or (w.get("year") or 0) < since_year:
            continue
        ex = w.get("externalIds") or {}
        out.append(_paper(w["title"], w.get("year"), w.get("publicationDate"), w.get("venue"), ex.get("DOI"),
                          ex.get("ArXiv"), ws(w.get("abstract")) or None,
                          "https://www.semanticscholar.org/paper/" + (w.get("paperId") or ""),
                          bad=bool({"Editorial", "Book", "Dataset", "News", "LettersAndComments"} & set(w.get("publicationTypes") or []))))
    return out

def s2_resolve(name, uni, focus):
    d = s2_get("/author/search", query=" ".join(name_tokens(name)), limit=10, fields="name,affiliations,paperCount")
    match, fkw = university_matcher(uni), keywords(focus)
    cands = [c for c in (d or {}).get("data", [])
             if name_compatible(name, c.get("name", "")) and any(match(a) for a in c.get("affiliations") or [])]
    cands.sort(key=lambda c: -(c.get("paperCount") or 0))
    ids, weak = [], set()
    for c in cands[:3]:
        papers = sorted(s2_works(c["authorId"], 2021), key=lambda p: p["date"] or str(p["year"]), reverse=True)[:15]
        t, ta = topic_score(fkw, papers)
        if t >= 2 or ta >= 4:
            ids.append(c["authorId"])
            if t < 3:
                weak.add(c["authorId"])
    return ids, weak

# ---------------------------------------------------------------- selection
def fits_topic(p, fkw):
    return len(fkw & keywords(p["title"] + " " + (p["abstract"] or ""))) >= 1

def dedupe(papers):
    """A preprint and its published version are one paper; keep the later one."""
    seen, out = {}, []
    for p in sorted(papers, key=lambda p: p["date"] or str(p["year"])):
        keys = [norm_title(p["title"])] + ([p["doi"]] if p["doi"] else [])
        idx = next((seen[k] for k in keys if k in seen), None)
        if idx is None:
            out.append(p)
            idx = len(out) - 1
        else:
            old = out[idx]
            p = dict(p)
            p["abstract"] = p["abstract"] or old["abstract"]
            p["arxiv"] = p["arxiv"] or old["arxiv"]
            out[idx] = p
        for k in keys:
            seen[k] = idx
    return out

def pick_top(ids, weak, fetch_works, focus, since_year, n):
    fkw, keep = keywords(focus), []
    for aid in ids:
        for p in fetch_works(aid):
            if aid in weak and not fits_topic(p, fkw):
                continue
            if p["bad"] or p["year"] < since_year:
                continue
            p["author_id"] = aid
            keep.append(p)
    return sorted(dedupe(keep), key=lambda p: (p["date"] or str(p["year"]), p["title"]), reverse=True)[:n]

def find_papers(name, uni, focus, since_year=2024, n=3):
    """Returns (papers, source, note). Raises ApiFail only if every source is unavailable."""
    global _oa_cooldown_until, _s2_cooldown_until
    best, source, note, oa_failed = [], "", "", False
    if time.time() >= _oa_cooldown_until:
        try:
            ids, weak = oa_resolve(name, uni, focus)
            if ids:
                best = pick_top(ids, weak, lambda a: oa_works(a, f"{since_year}-01-01", 50), focus, since_year, n)
                source, note = "OpenAlex", f"author ids {';'.join(ids)}"
        except ApiFail as e:
            oa_failed, _oa_cooldown_until = True, time.time() + 600
            log(f"    OpenAlex unavailable ({e}); falling back to Semantic Scholar for 10 min")
    else:
        oa_failed = True
    if len(best) < n and time.time() >= _s2_cooldown_until:
        try:
            ids, weak = s2_resolve(name, uni, focus)
            if ids:
                alt = pick_top(ids, weak, lambda a: s2_works(a, since_year), focus, since_year, n)
                if len(alt) > len(best):
                    best, source, note = alt, "SemanticScholar", f"author ids {';'.join(ids)}"
        except ApiFail:
            _s2_cooldown_until = time.time() + 600
            if oa_failed and not best:
                raise ApiFail("OpenAlex and Semantic Scholar both unavailable")
    elif oa_failed and not best:
        raise ApiFail("OpenAlex and Semantic Scholar both unavailable (cooling down)")
    for p in best:
        if not p["abstract"]:
            p["abstract"], p["abstract_source"] = find_abstract(p["title"], p["doi"], p["arxiv"], p["year"])
        else:
            p["abstract_source"] = source
        if not p["abstract"]:
            p["abstract"], p["abstract_source"] = f"Abstract not available – see {p['url']}", "none"
    return best, source, note
