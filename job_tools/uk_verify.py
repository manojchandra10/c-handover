#!/usr/bin/env python3
"""Second live check of every kept UK role, then removal of duplicates.

Usage: python3 -I job_tools/uk_verify.py <data_dir> [--workers 8] [--seed web_roles.json]
Reads <data_dir>/roles.jsonl (from uk_crawl.py), opens each kept advert again in a separate request, and writes
<data_dir>/roles_checked.jsonl. A role stays in the Jobs sheet only when both checks found it open.
--seed adds roles found earlier by web search, so they are re-opened as well.
Second-check results: Open, Closed (with the reason) or Not re-opened (no answer, or robots.txt).
"""
import sys, json, re, argparse, datetime as dt
from pathlib import Path
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uk_rules as R
import uk_crawl as C


def second_check(role):
    url = role.get("url") or ""
    out = {"second_check": "", "second_note": "", "second_checked_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    if not url.startswith("http"):
        out.update(second_check="Not re-opened", second_note="No link to re-open")
        return out
    if re.search(r"/(categories|search|tracker)(/|\?|$)|/graduate-jobs/?$", urlparse(url).path + ("?" if urlparse(url).query else "")):
        out.update(second_check="Not re-opened", second_note="The link is a list of many jobs, so it cannot show this one is open")
        return out
    r = C.fetch(url, timeout=20)
    if r is None:
        out.update(second_check="Not re-opened", second_note="The page did not answer")
        return out
    if r.status == -1:
        out.update(second_check="Not re-opened", second_note="robots.txt asks crawlers not to read this page")
        return out
    if r.status in (404, 410):
        out.update(second_check="Closed", second_note=f"Page returns {r.status}")
        return out
    if r.status >= 400:
        out.update(second_check="Not re-opened", second_note=f"Page returns {r.status}")
        return out
    first, final = urlparse(url), urlparse(r.url)
    if final.netloc == first.netloc and len(final.path.rstrip("/")) + 3 < len(first.path.rstrip("/")) and \
            not re.search(r"\d{3,}", final.path) and re.search(r"\d{3,}|[a-f0-9-]{16,}", first.path):
        out.update(second_check="Closed", second_note="Advert link now redirects to the jobs list")
        return out
    is_html = "html" in r.ctype or r.text.lstrip()[:1] == "<"
    if (role.get("how") or "").startswith("Listed on the careers page"):
        # several roles share this page: judge only the text under this role's heading
        same = [j for j in C.inline_jobs(r.text, r.url) if j["title"].lower() == role["title"].lower()]
        if not same:
            out.update(second_check="Closed", second_note="Role no longer listed on the careers page")
            return out
        status, closing, note = R.open_status(same[0]["text"], role.get("valid_through") or None)
        out.update(second_check=status, second_note=note)
        if closing:
            out["closing"] = closing.isoformat()
        return out
    text = C.page_text(r.text, 60000) if is_html else R.clean_text(r.text)[:60000]
    jl = C.jsonld_jobs(r.text, r.url) if is_html else []
    vt = next((j["valid_through"] for j in jl if j.get("valid_through")), None)
    status, closing, note = R.open_status(text, vt or role.get("valid_through") or role.get("closing"))
    out.update(second_check=status if status != "Unclear" else "Not re-opened", second_note=note)
    if closing:
        out["closing"] = closing.isoformat()
    return out


def norm_title(t):
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", (t or "").lower())
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    t = re.sub(r"\b(20\d\d|hybrid|remote|london|uk|ft|full time|permanent|fixed term)\b", " ", t)
    return " ".join(t.split())


RANK = {"Employer careers page": 0, "Civil Service Analysis Function": 1, "jobs.ac.uk": 2, "DWP Find a job": 3}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", default="")
    a = ap.parse_args()
    d = Path(a.data_dir)
    roles = [json.loads(l) for l in (d / "roles.jsonl").read_text(encoding="utf8").splitlines() if l.strip()] \
        if (d / "roles.jsonl").exists() else []
    if a.seed:
        have = {(r.get("url"), r.get("title")) for r in roles}
        for r in json.loads(Path(a.seed).read_text(encoding="utf8")):
            if (r.get("url"), r.get("title")) not in have:
                r.setdefault("source_kind", "Web search")
                r.setdefault("checked_at", "")
                r.setdefault("city", "")
                roles.append(r)
    kept = [r for r in roles if not r.get("exclude")]
    print(f"roles read {len(roles)}, kept after the first check {len(kept)}")

    # one advert per employer, title and city: prefer the employer's own page, then the most recent record
    best = {}
    for r in kept:
        emp = (r.get("organisation") or r.get("employer_on_advert") or "").lower()
        k = (C._norm_employer(emp), norm_title(r["title"]), (r.get("city") or "").lower())
        cur = best.get(k)
        if cur is None or (RANK.get(r["source_kind"], 9), r["checked_at"]) < (RANK.get(cur["source_kind"], 9), cur["checked_at"]):
            if cur is not None:
                cur["duplicate_of"] = r["url"]
            best[k] = r
        else:
            r["duplicate_of"] = cur["url"]
    unique = list(best.values())
    print(f"after removing duplicates {len(unique)}")

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        checks = list(ex.map(second_check, unique))
    for r, c in zip(unique, checks):
        r.update(c)
        if c["second_check"] == "Closed":
            r["exclude"] = "Closed at the second check: " + c["second_note"]
    excluded = [r for r in roles if r.get("exclude") or r.get("duplicate_of")]
    with open(d / "roles_checked.jsonl", "w", encoding="utf8") as f:
        for r in unique + [r for r in excluded if r not in unique]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_open = sum(1 for r in unique if r["second_check"] == "Open")
    n_closed = sum(1 for r in unique if r["second_check"] == "Closed")
    print(f"second check: open {n_open}, closed {n_closed}, not re-opened {len(unique) - n_open - n_closed}")


if __name__ == "__main__":
    main()
