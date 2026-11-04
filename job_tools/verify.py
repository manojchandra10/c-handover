#!/usr/bin/env python3
"""Classify collected jobs, apply the rules, dedupe, and re-check that each kept advert is still live.

Usage: python3 -I verify.py <data_dir>
Reads raw_*.json, writes final.json (kept jobs) and excluded.json (with reasons).
"""
import sys, json, re, time, random, datetime as dt
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rules import (clean_text, area_of, assess_level, assess_language, place_of, work_mode, salary_of, permit_note)
import collect  # reuses the HTTP session and LinkedIn detail parser

DATA = Path(sys.argv[1]).resolve()
NOW = dt.datetime.now()
TODAY = NOW.date()

CLOSED_MARKERS = [
    "no longer accepting applications", "no longer available", "this job has expired", "job has expired",
    "job is no longer", "position has been filled", "this position is closed", "position is no longer",
    "job is closed", "not accepting applications", "job not found", "posting has been closed", "vacancy has been filled",
    "this job is not available", "the job you are looking for", "listing has expired", "job offer has expired",
    "nicht mehr verfügbar", "nicht mehr aktiv", "bereits besetzt", "stellenanzeige ist abgelaufen",
    "diese stelle ist nicht mehr", "bewerbungsfrist ist abgelaufen", "anzeige ist abgelaufen", "leider ist diese job-anzeige",
]


def norm_company(s):
    s = (s or "").lower()
    s = re.sub(r"\b(gmbh|ag|se|kg|co|mbh|ug|inc|ltd|llc|group|gruppe|holding|deutschland|germany|austria|österreich)\b", " ", s)
    return re.sub(r"[^a-z0-9äöü]+", "", s)


def norm_title(s):
    s = (s or "").lower()
    s = re.sub(r"\((?:[mwfdxa]\s*/\s*){1,3}[mwfdxa]\)|\(all genders?\)|\(gn\)|\(d/m/w\)|\(w/m/d\)|\(m/w/x\)|\(f/m/x\)|\(f/m/div\.?\)", " ", s)
    s = re.sub(r"\*|\bin\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def classify(it):
    country, city = place_of(it["location"])
    area = area_of(it["title"])
    text = it.get("text") or ""
    level, years = assess_level(it["title"], text, it.get("seniority"))
    lang, evidence = assess_language(text) if clean_text(text) else ("Unknown", "")
    mode = work_mode(it["location"], text, it.get("remote"), it.get("workplace"))
    annual, monthly, sal_snip = salary_of(text, country)
    it.update({"country": country, "city": city, "area": area, "level": level, "years": years, "language": lang,
               "lang_evidence": evidence, "mode": mode, "pay_annual": annual, "pay_monthly": monthly,
               "salary_text": sal_snip, "permit": permit_note(country, annual, monthly)})
    reasons = []
    if country not in ("DE", "AT"):
        reasons.append("Not in Germany or Austria")
    if area is None:
        reasons.append("Not a data analyst, data scientist, BI, analytics or ML role, or excluded level in title")
    if not clean_text(text):
        reasons.append("Advert text could not be read, so it could not be checked")
    elif level is None:
        reasons.append("Asks for 3 or more years, or no sign it is open to graduates")
    if lang == "German required":
        reasons.append("German required")
    if mode == "Remote":
        reasons.append("Remote only")
    ex = it.get("extra") or {}
    if ex.get("closed"):
        reasons.append("Closed (first check)")
    vt = iso(ex.get("validThrough"))
    if vt and vt < TODAY.isoformat():
        reasons.append("Closing date passed")
    return reasons


def iso(s):
    if not s:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(s))
    return m.group(1) if m else None


def live_check(it):
    """Second, independent check that the advert is open now. Returns (ok, note)."""
    src = it["source"]
    try:
        if src == "LinkedIn":
            d = collect.li_detail(it["sid"])
            time.sleep(1.0 + random.random())
            if not d or d.get("status") != 200:
                return False, f"LinkedIn detail status {None if not d else d.get('status')}"
            return (not d["closed"]), ("open on LinkedIn" if not d["closed"] else "LinkedIn says no longer accepting applications")
        if src.startswith(("Greenhouse", "Lever", "Ashby", "Personio", "SmartRecruiters", "Recruitee")):
            r = collect.get(it["url"], tries=3, quiet=True)
            if r is None:
                return False, "employer page did not load"
            if r.status_code != 200:
                return False, f"employer page status {r.status_code}"
            low = r.text.lower()
            if "error=true" in r.url or any(m in low for m in CLOSED_MARKERS):
                return False, "employer page says closed"
            return True, "open on employer's hiring page"
        r = collect.get(it["url"], tries=3, quiet=True)
        if r is None:
            return False, "page did not load"
        if r.status_code != 200:
            return False, f"page status {r.status_code}"
        low = r.text.lower()
        if any(m in low for m in CLOSED_MARKERS):
            return False, "page says closed"
        jp = collect.jsonld_jobposting(r.text)
        vt = iso((jp or {}).get("validThrough"))
        if vt and vt < TODAY.isoformat():
            return False, f"closing date {vt} passed"
        return True, "open on " + src
    except Exception as e:
        return False, f"check failed: {type(e).__name__}"


SOURCE_RANK = {"Greenhouse": 0, "Lever": 0, "Ashby": 0, "Personio": 0, "SmartRecruiters": 0, "Recruitee": 0,
               "karriere.at": 1, "devjobs.at": 1, "devjobs.de": 1, "Bundesagentur für Arbeit": 1, "Arbeitnow": 2,
               "Berlin Startup Jobs": 2, "GermanTechJobs": 2, "LinkedIn": 3}


def rank(src):
    for k, v in SOURCE_RANK.items():
        if src.startswith(k):
            return v
    return 4


def main():
    raw = []
    for p in sorted(DATA.glob("raw_*.json")):
        raw.extend(json.loads(p.read_text(encoding="utf8")))
    print("raw records", len(raw))
    kept, excluded = [], []
    for it in raw:
        reasons = classify(it)
        (excluded if reasons else kept).append(it)
        if reasons:
            it["reasons"] = reasons
    print("pass rules", len(kept), "excluded", len(excluded))

    # Dedupe: prefer the employer's own board, then specialist boards, then LinkedIn.
    groups = {}
    for it in kept:
        key = (norm_company(it["company"]), norm_title(it["title"]), it["city"])
        groups.setdefault(key, []).append(it)
    unique = []
    for key, its in groups.items():
        its.sort(key=lambda x: (rank(x["source"]), x.get("posted") or ""))
        best = dict(its[0])
        best["also_on"] = sorted({x["source"] for x in its[1:]} - {best["source"]})
        unique.append(best)
    print("after dedupe", len(unique))

    # Second check, done for every kept job at the end of the run.
    def check(it):
        ok, note = live_check(it)
        it["check2_ok"], it["check2_note"], it["check2_at"] = ok, note, dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        return it

    li = [x for x in unique if x["source"] == "LinkedIn"]
    other = [x for x in unique if x["source"] != "LinkedIn"]
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(check, other))
    for i, x in enumerate(li):
        check(x)
        if i % 50 == 0:
            print("LinkedIn recheck", i, "/", len(li), flush=True)

    final = [x for x in unique if x.get("check2_ok")]
    failed = [x for x in unique if not x.get("check2_ok")]
    for x in failed:
        x["reasons"] = ["Closed or unreachable on second check: " + x.get("check2_note", "")]
    excluded.extend(failed)
    for x in final + excluded:
        x["text"] = clean_text(x.get("text"))[:1500]
    (DATA / "final.json").write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding="utf8")
    (DATA / "excluded.json").write_text(json.dumps(excluded, ensure_ascii=False, indent=1), encoding="utf8")
    by = {}
    for x in final:
        by[x["country"]] = by.get(x["country"], 0) + 1
    print("FINAL", len(final), by, "excluded", len(excluded))


if __name__ == "__main__":
    main()
