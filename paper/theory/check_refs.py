#!/usr/bin/env python
"""Look up every DOI cited in CRLB-NOTES.md on Crossref and save what Crossref says.
Usage:  python paper/theory/check_refs.py   (writes out/crossref.json)"""
import json
import os
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DOIS = {
    "ribnick2009": "10.1109/TPAMI.2008.247",
    "hartley2004": "10.1017/CBO9780511811685",
    "stoica2001": "10.1109/78.890346",
    "rothenberg1971": "10.2307/1913267",
    "gill1995": "10.2307/3318681",
    "huber1964": "10.1214/aoms/1177703732",
    "huber1973": "10.1214/aos/1176342503",
    "gorman1990": "10.1109/18.59929",
    "hero1996": "10.1109/78.533723",
    "seber1989": "10.1002/0471725315",
    "vantrees2007": "10.1109/9780470544198",
}
SEARCH = {"kay1993": "Fundamentals of Statistical Signal Processing Estimation Theory Kay"}
UA = {"User-Agent": "pocket-drs-paper-refcheck/1.0 (mailto:contact.me.kafle@gmail.com)"}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.load(r)["message"]


def brief(m):
    return dict(doi=m.get("DOI"), title=(m.get("title") or [""])[0], container=(m.get("container-title") or [""])[0],
                authors=[f"{a.get('given', '')} {a.get('family', '')}".strip() for a in m.get("author", [])],
                year=(m.get("issued", {}).get("date-parts") or [[None]])[0][0],
                volume=m.get("volume"), issue=m.get("issue"), pages=m.get("page"), publisher=m.get("publisher"),
                type=m.get("type"))


def main():
    out = {}
    for key, doi in DOIS.items():
        try:
            out[key] = brief(get("https://api.crossref.org/works/" + urllib.parse.quote(doi)))
        except Exception as exc:
            out[key] = dict(doi=doi, error=str(exc))
        print(key, json.dumps(out[key]))
    for key, q in SEARCH.items():
        try:
            items = get("https://api.crossref.org/works?rows=5&query.bibliographic=" + urllib.parse.quote(q))["items"]
            out[key] = dict(query=q, hits=[brief(m) for m in items])
        except Exception as exc:
            out[key] = dict(query=q, error=str(exc))
        print(key, json.dumps(out[key])[:600])
    os.makedirs(os.path.join(HERE, "out"), exist_ok=True)
    with open(os.path.join(HERE, "out", "crossref.json"), "w") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
