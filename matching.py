"""Keyword matching of a job description against saved experiences.

No external AI service: a TF-IDF-style score, so it is free and runs anywhere.
"""
import math
import re
from collections import Counter

_STOP = set("""a an and are as at be been but by can for from had has have he her his i if in into is it its
me my of on or our out so than that the their them then there these they this to up us was we were what when
which who will with you your about across also all any more most other over per such using use within work
working team role job company candidate required requirements responsibilities experience ability skills
strong excellent good great new help should must may able join looking""".split())


def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s", "ly"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def tokens(s: str) -> list[str]:
    words = re.findall(r"[a-z][a-z+#.\-]{1,}", s.lower())
    return [_stem(w.strip(".-")) for w in words if w.strip(".-") not in _STOP and len(w) > 2]


def rank(job_description: str, experiences: list[dict], limit: int = 5) -> list[dict]:
    """Return up to `limit` experiences ordered by relevance, each with score and matched terms."""
    jd = Counter(tokens(job_description))
    if not jd or not experiences:
        return []
    docs = []
    for e in experiences:
        # Skills count triple: they're the most deliberate signal the user gave.
        toks = tokens(e["title"]) + tokens(e["what_i_did"]) + tokens(e["outcome"]) + tokens(e["skills"]) * 3
        docs.append(Counter(toks))
    n = len(docs)
    df = Counter(t for d in docs for t in d)
    scored = []
    for e, d in zip(experiences, docs):
        matched, score = {}, 0.0
        for term, jd_count in jd.items():
            if term in d:
                idf = math.log(1 + n / df[term])
                s = (1 + math.log(jd_count)) * (1 + math.log(d[term])) * idf
                score += s
                matched[term] = s
        if score > 0:
            top = sorted(matched, key=matched.get, reverse=True)[:8]
            scored.append({**e, "score": round(score, 2), "matched_terms": top})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]
