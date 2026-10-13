"""One function per scholarly source. Each returns real abstract text or None, and only
accepts a record whose title matches the paper being looked up (never a guess)."""
import difflib, os, urllib.parse
import xml.etree.ElementTree as ET
from .common import fetch, ws, norm_title, strip_tags, CONTACT, ApiFail

OA = "https://api.openalex.org"
OA_KEY = os.environ.get("OPENALEX_API_KEY", "")
S2 = "https://api.semanticscholar.org/graph/v1"
S2_KEY = os.environ.get("S2_API_KEY", "")

def similar(a, b):
    return difflib.SequenceMatcher(None, norm_title(a), norm_title(b)).ratio()

def oa_get(path, strict=False, **params):
    if OA_KEY:
        params["api_key"] = OA_KEY
    return fetch("openalex", OA + path, 0.12, params=params, tries=3, strict=strict)

def oa_rebuild(inverted):
    """OpenAlex stores abstracts as {word: [positions]}; turn that back into text."""
    if not inverted:
        return None
    pos = {}
    for word, idxs in inverted.items():
        for i in idxs:
            pos[i] = word
    return ws(" ".join(pos[i] for i in sorted(pos))) or None

def abs_openalex_doi(doi, title):
    d = oa_get("/works/doi:" + urllib.parse.quote(doi, safe="/"), select="title,abstract_inverted_index")
    if d and similar(d.get("title"), title) >= 0.8:
        return oa_rebuild(d.get("abstract_inverted_index"))

def abs_openalex_title(title, year=None):
    d = oa_get("/works", search=title, select="title,publication_year,abstract_inverted_index", **{"per-page": 5})
    for w in (d or {}).get("results", []):
        near = True
        if year and w.get("publication_year"):
            near = abs(int(w["publication_year"]) - int(year)) <= 1
        if near and similar(w.get("title"), title) >= 0.92:
            a = oa_rebuild(w.get("abstract_inverted_index"))
            if a:
                return a

def abs_arxiv(arxiv_id, title):
    text = fetch("arxiv", "http://export.arxiv.org/api/query", 3.1, params={"id_list": arxiv_id}, as_json=False)
    if not text:
        return None
    try:
        ns = "{http://www.w3.org/2005/Atom}"
        e = ET.fromstring(text).find(ns + "entry")
        if e is not None and similar(e.findtext(ns + "title"), title) >= 0.8:
            return ws(e.findtext(ns + "summary")) or None
    except ET.ParseError:
        pass

def abs_crossref(doi, title):
    params = {"mailto": CONTACT} if CONTACT else None
    d = fetch("crossref", "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/"), 0.3, params=params)
    m = (d or {}).get("message") or {}
    if m.get("abstract") and similar((m.get("title") or [""])[0], title) >= 0.8:
        text = strip_tags(m["abstract"])
        return text[len("Abstract"):].strip() if text.startswith("Abstract") else text

def abs_s2(ident, title):
    """ident: 'DOI:10...', 'ARXIV:1234.5678' or a Semantic Scholar paper id."""
    headers = {"x-api-key": S2_KEY} if S2_KEY else None
    d = fetch("s2", f"{S2}/paper/{urllib.parse.quote(ident, safe=':/')}", 1.2 if S2_KEY else 3.0,
              params={"fields": "title,abstract"}, headers=headers, tries=2)
    if d and d.get("abstract") and similar(d.get("title"), title) >= 0.8:
        return ws(d["abstract"])

def abs_europepmc(doi, title):
    q = f'DOI:"{doi}"' if doi else f'TITLE:"{title}"'
    d = fetch("epmc", "https://www.ebi.ac.uk/europepmc/webservices/rest/search", 0.3,
              params={"query": q, "resultType": "core", "format": "json", "pageSize": 3})
    for r in (d or {}).get("resultList", {}).get("result", []):
        if r.get("abstractText") and similar(r.get("title"), title) >= 0.9:
            return strip_tags(r["abstractText"])

def find_abstract(title, doi=None, arxiv=None, year=None, s2_id=None):
    """Try every source in order. Returns (abstract, source) or (None, 'none')."""
    steps = []
    if doi:
        steps.append(("OpenAlex", lambda: abs_openalex_doi(doi, title)))
    if arxiv:
        steps.append(("arXiv", lambda: abs_arxiv(arxiv, title)))
    if doi and not doi.lower().startswith("10.48550"):
        steps.append(("Crossref", lambda: abs_crossref(doi, title)))
    if s2_id:
        steps.append(("SemanticScholar", lambda: abs_s2(s2_id, title)))
    elif doi:
        steps.append(("SemanticScholar", lambda: abs_s2("DOI:" + doi, title)))
    steps.append(("OpenAlex", lambda: abs_openalex_title(title, year)))
    steps.append(("EuropePMC", lambda: abs_europepmc(doi, title)))
    for name, fn in steps:
        try:
            a = fn()
        except ApiFail:
            a = None
        if a and len(a) > 40:
            return a, name
    return None, "none"
