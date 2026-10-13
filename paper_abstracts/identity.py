"""Identity checks used before trusting an author profile: name, university, topic."""
import re
from .common import ascii_fold

TITLE_WORDS = {"prof", "professor", "dr", "mr", "ms", "mrs", "assoc", "assistant", "associate"}
UNI_STOP = {"university", "of", "the", "at", "and", "in", "college", "institute", "for", "state", "system"}
STOP = set("""with from that this using based their they which these those into over under through between among
within novel approach approaches method methods model models system systems study analysis new via for and the use
used uses toward towards high low data design designs development application applications techniques technique
including include includes such also both other more most than then when where while efficient""".split())

def name_tokens(name):
    n = ascii_fold(re.sub(r'"[^"]*"|\([^)]*\)', " ", name))
    return [t for t in re.split(r"[^a-z]+", n) if t and t not in TITLE_WORDS and t not in {"jr", "sr", "ii", "iii", "phd"}]

def name_compatible(wanted, candidate):
    """Same last name AND a matching first name or initial."""
    p = name_tokens(wanted)
    c = [t for t in re.split(r"[^a-z]+", ascii_fold(candidate)) if t]
    if not p or not c or p[-1] not in c:
        return False
    first, last = p[0], p[-1]
    if first == last:
        return True
    return any(t != last and (t == first or t.startswith(first) or first.startswith(t) or (len(t) == 1 and t == first[0]))
               for t in c)

def university_matcher(uni):
    """Returns f(text) -> True when text names that university (distinctive words or acronym)."""
    u = ascii_fold(uni)
    toks = [t for t in re.split(r"[^a-z]+", u) if t and t not in UNI_STOP] or [t for t in re.split(r"[^a-z]+", u) if t]
    words = [w for w in re.split(r"[^a-z]+", u) if w and w not in {"of", "the", "at", "and"}]
    acro = "".join(w[0] for w in words)
    need = len(toks) if len(toks) <= 2 else len(toks) - 1
    def match(text):
        t = ascii_fold(text)
        if not t:
            return False
        hits = sum(1 for tok in toks if tok in t or (tok == "technology" and "tech" in t))
        if hits >= max(need, 1):
            return True
        return len(acro) >= 3 and re.search(r"\b" + acro + r"\b", t) is not None
    return match

def keywords(text):
    return {w[:5] for w in re.findall(r"[a-z]{4,}", ascii_fold(text)) if w not in STOP}

def topic_score(focus_kw, papers):
    """(# focus keywords found in titles, # found in titles+abstracts) of an author's recent papers."""
    title_kw = set()
    for p in papers:
        title_kw |= keywords(p.get("title") or "")
    all_kw = set(title_kw)
    for p in papers:
        all_kw |= keywords(p.get("abstract") or "")
    return len(focus_kw & title_kw), len(focus_kw & all_kw)
