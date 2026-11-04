#!/usr/bin/env python3
"""Collect live graduate and junior data jobs in Germany and Austria, classify them and check each one is open.

Usage: python3 -I collect.py <data_dir> [source ...]
Sources: linkedin arbeitnow ba ats karriere devjobs bsj gtj  (default: all)
Writes <data_dir>/raw_<source>.json and <data_dir>/collect.log.
"""
import sys, json, time, re, random, base64, datetime as dt
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rules import (clean_text, area_of, assess_level, assess_language, place_of, work_mode, salary_of)

OUT = Path(sys.argv[1]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
LOGF = open(OUT / "collect.log", "a", encoding="utf8")
TODAY = dt.date.today()


def log(*a):
    msg = dt.datetime.now().strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(msg, flush=True)
    LOGF.write(msg + "\n")
    LOGF.flush()


S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9,de;q=0.5",
})


def get(url, params=None, headers=None, tries=4, pause=1.5, quiet=False):
    """GET with retries on network errors and 429/5xx. Returns the Response or None."""
    for i in range(tries):
        try:
            r = S.get(url, params=params, headers=headers, timeout=30)
        except requests.RequestException as e:
            if not quiet:
                log("ERR", url[:120], type(e).__name__)
            time.sleep(pause * (2 ** i))
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            wait = pause * (2 ** (i + 1)) + random.random() * 2
            if not quiet:
                log("RETRY", r.status_code, url[:100], "sleep", round(wait, 1))
            time.sleep(wait)
            continue
        return r
    return None


def iso(d):
    if d is None or d == "":
        return None
    try:
        if isinstance(d, (int, float)):
            if d > 1e11:
                d = d / 1000
            return dt.datetime.utcfromtimestamp(d).date().isoformat()
        s = str(d)
        m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
        return m.group(1) if m else None
    except Exception:
        return None


def rec(source, sid, title, company, location, url, text="", posted=None, remote=None, workplace=None,
        seniority=None, extra=None):
    return {
        "source": source, "sid": str(sid), "title": (title or "").strip(), "company": (company or "").strip(),
        "location": (location or "").strip(), "url": url, "text": text or "", "posted": iso(posted),
        "remote": remote, "workplace": workplace, "seniority": seniority, "extra": extra or {},
        "collected_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def prefilter(title, location):
    country, city = place_of(location)
    return country in ("DE", "AT") and area_of(title) is not None


def save(name, items):
    p = OUT / f"raw_{name}.json"
    p.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf8")
    log("SAVED", name, len(items), "->", p.name)


# ------------------------------------------------------------------ LinkedIn (public job search)

LI_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LI_DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{}"
LI_JUNIOR_KW = ["junior data analyst", "junior data scientist", "graduate data analyst", "graduate data scientist",
                "junior business intelligence", "junior bi analyst", "junior analytics engineer",
                "junior machine learning engineer", "junior ml engineer", "entry level data analyst",
                "associate data scientist", "associate data analyst", "junior product analyst",
                "junior reporting analyst", "junior marketing analyst", "junior data", "junior ai engineer"]
LI_BROAD_KW = ["data analyst", "data scientist", "business intelligence analyst", "bi analyst", "analytics engineer",
               "machine learning engineer", "product analyst", "reporting analyst", "data analytics",
               "marketing data analyst", "pricing analyst", "ai engineer"]


def li_cards(html):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for el in soup.select("[data-entity-urn]"):
        urn = el.get("data-entity-urn", "")
        m = re.search(r"jobPosting:(\d+)", urn)
        if not m:
            continue
        jid = m.group(1)
        root = el if el.name == "div" else el.parent
        t = root.select_one(".base-search-card__title")
        c = root.select_one(".base-search-card__subtitle")
        l = root.select_one(".job-search-card__location")
        d = root.select_one("time")
        a = root.select_one("a.base-card__full-link") or (el if el.name == "a" else None)
        out.append({
            "id": jid,
            "title": t.get_text(" ", strip=True) if t else "",
            "company": c.get_text(" ", strip=True) if c else "",
            "location": l.get_text(" ", strip=True) if l else "",
            "posted": d.get("datetime") if d else None,
            "url": (a.get("href", "").split("?")[0] if a else "") or f"https://www.linkedin.com/jobs/view/{jid}",
        })
    return out


def li_detail(jid):
    r = get(LI_DETAIL.format(jid), pause=3, quiet=True)
    if r is None:
        return None
    if r.status_code != 200:
        return {"status": r.status_code}
    soup = BeautifulSoup(r.text, "lxml")
    desc = soup.select_one("div.show-more-less-html__markup") or soup.select_one("div.description__text")
    crit = {}
    for li in soup.select("li.description__job-criteria-item"):
        h, v = li.select_one("h3"), li.select_one("span")
        if h and v:
            crit[h.get_text(strip=True)] = v.get_text(strip=True)
    closed = bool(soup.select_one("figure.closed-job")) or "No longer accepting applications" in r.text
    apply_url = None
    code = soup.select_one("code#applyUrl")
    if code:
        m = re.search(r"url=([^&\"]+)", code.get_text())
        if m:
            apply_url = requests.utils.unquote(m.group(1))
    return {"status": 200, "text": str(desc) if desc else "", "criteria": crit, "closed": closed, "apply_url": apply_url}


def linkedin():
    items, seen = [], set()
    plans = []
    for country, loc in (("DE", "Germany"), ("AT", "Austria")):
        for kw in LI_JUNIOR_KW:
            plans.append((country, loc, kw, None))
        for kw in LI_BROAD_KW:
            plans.append((country, loc, kw, "2,3"))
    for country, loc, kw, fe in plans:
        new_total = 0
        for start in range(0, 1000, 25):
            params = {"keywords": kw, "location": loc, "f_TPR": "r2592000", "f_WT": "1,3", "start": start}
            if fe:
                params["f_E"] = fe
            r = get(LI_SEARCH, params=params, pause=3)
            if r is None or r.status_code != 200 or not r.text.strip():
                break
            cards = li_cards(r.text)
            if not cards:
                break
            new = 0
            for c in cards:
                if c["id"] in seen:
                    continue
                seen.add(c["id"])
                new += 1
                if not prefilter(c["title"], c["location"]):
                    continue
                items.append(rec("LinkedIn", c["id"], c["title"], c["company"], c["location"], c["url"],
                                 posted=c["posted"]))
            new_total += new
            time.sleep(1.2 + random.random())
            if len(cards) < 10:
                break
        log("LinkedIn", country, repr(kw), "fe" if fe else "", "new ids", new_total, "kept so far", len(items))
    log("LinkedIn detail fetch for", len(items))
    for i, it in enumerate(items):
        d = li_detail(it["sid"])
        if d and d.get("status") == 200:
            it["text"] = d["text"]
            it["seniority"] = d["criteria"].get("Seniority level")
            it["extra"] = {"criteria": d["criteria"], "closed": d["closed"], "apply_url": d["apply_url"]}
        else:
            it["extra"] = {"detail_status": (d or {}).get("status")}
        time.sleep(1.0 + random.random())
        if i % 50 == 0:
            log("LinkedIn detail", i, "/", len(items))
    save("linkedin", items)


# ------------------------------------------------------------------ Arbeitnow API

def arbeitnow():
    items = []
    for page in range(1, 80):
        r = get("https://www.arbeitnow.com/api/job-board-api", params={"page": page})
        if r is None or r.status_code != 200:
            break
        data = r.json().get("data") or []
        if not data:
            break
        for d in data:
            if not prefilter(d.get("title"), d.get("location")):
                continue
            items.append(rec("Arbeitnow", d.get("slug"), d.get("title"), d.get("company_name"), d.get("location"),
                             d.get("url"), text=d.get("description"), posted=d.get("created_at"),
                             remote=d.get("remote"), extra={"tags": d.get("tags"), "types": d.get("job_types")}))
        time.sleep(0.5)
    log("Arbeitnow kept", len(items))
    save("arbeitnow", items)


# ------------------------------------------------------------------ German Federal Employment Agency (Jobsuche API)

BA_SEARCH = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
BA_DETAIL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/{}"
BA_H = {"X-API-Key": "jobboerse-jobsuche"}
BA_TERMS = ["Junior Data Analyst", "Data Analyst", "Junior Data Scientist", "Data Scientist",
            "Business Intelligence Analyst", "BI Analyst", "Analytics Engineer", "Machine Learning Engineer",
            "Product Analyst", "Reporting Analyst", "Graduate Data"]


def ba_detail(refnr):
    enc = base64.b64encode(refnr.encode()).decode()
    r = get(BA_DETAIL.format(enc), headers=BA_H, quiet=True)
    if r is not None and r.status_code == 200:
        try:
            j = r.json()
            return j.get("stellenangebotsBeschreibung") or j.get("stellenbeschreibung") or "", j
        except ValueError:
            pass
    return None, None


def ba():
    items, seen = [], set()
    for term in BA_TERMS:
        for page in range(1, 11):
            r = get(BA_SEARCH, params={"was": term, "angebotsart": 1, "veroeffentlichtseit": 60, "size": 100,
                                       "page": page}, headers=BA_H)
            if r is None or r.status_code != 200:
                log("BA status", None if r is None else r.status_code, term)
                break
            offers = r.json().get("stellenangebote") or []
            if not offers:
                break
            for o in offers:
                ref = o.get("refnr")
                if not ref or ref in seen:
                    continue
                seen.add(ref)
                ort = o.get("arbeitsort") or {}
                loc = ", ".join(x for x in [ort.get("ort"), ort.get("region"), ort.get("land") or "Deutschland"] if x)
                if not prefilter(o.get("titel"), loc):
                    continue
                url = o.get("externeUrl") or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}"
                items.append(rec("Bundesagentur für Arbeit", ref, o.get("titel"), o.get("arbeitgeber"), loc, url,
                                 posted=o.get("aktuelleVeroeffentlichungsdatum"),
                                 extra={"refnr": ref, "external": o.get("externeUrl")}))
            time.sleep(0.4)
        log("BA", repr(term), "kept so far", len(items))
    for i, it in enumerate(items):
        text, j = ba_detail(it["extra"]["refnr"])
        if text:
            it["text"] = text
        elif it["extra"].get("external"):
            r = get(it["extra"]["external"], quiet=True)
            if r is not None and r.status_code == 200:
                it["text"] = page_text(r.text)
        time.sleep(0.3)
        if i % 50 == 0:
            log("BA detail", i, "/", len(items))
    save("ba", items)


# ------------------------------------------------------------------ Company hiring boards

COMPANIES = """
n26 getyourguide hellofresh deliveryhero zalando sumup contentful babbel omio taxfix raisin traderepublic solarisbank solaris
mambu sennder forto wolt bolt tier dott flink choco moss pliant upvest scalablecapital scalable idealo ecosia doctolib
auto1 auto1group autoscout24 mobilede kaufland zenjob almedia statista adjust blinkist soundcloud misterspex homeday
mcmakler thermondo enpal 1komma5grad zolar ottonova clark wefox getsafe finn grover vivid nuri kontist penta billie mondu
smava check24 verivox quandoo ableton nativeinstruments sevdesk personio celonis flix flixbus freeletics holidu konux
leapsome isaraerospace helsing alephalpha deepl trivago buynomics ionos travelcircus eidu outdooractive gemmaanalytics
phiture parloa langfuse cognigy tado navvis smartrics agicap pitch sumupgroup heycar finleap lendis spendesk rasa
merantix appliedai twaice ryte commercetools ecovadis personiogmbh trustpilot hometogo hometogogmbh ebay klarna
spotify booking wayfair amazon delivery-hero zalandose researchgate hellofreshse mytheresa breuninger about-you aboutyou
otto ottogroup xing newwork hapaglloyd airbus statistagmbh jimdo goodgame bigpoint innogames playa playagames
freenow free-now miles shareNow sharenow sixt flaschenpost picnic gorillas getir lieferando justeattakeaway
celonisse wandelbots instagrid nfon tonies westwing home24 zooplus egym urbansportsclub urban-sports-club
bitpanda gostudent refurbed tourradar planradar dynatrace anyline adverity prewave tractive bitmovin storyblok
mostlyai runtastic shpock willhaben byrd hokify eversports kapsch frequentis tricentis celum fabasoft catalysts
cloudflight craftworks anexia paysafe greentube sportradar redbull silicon-austria-labs siliconaustrialabs
knowcenter iiasa ista complexityhub ait parkbob journi tilcode tiko fiskaly blockpit hygh nuki woom
""".split()


def ats_greenhouse(t):
    r = get(f"https://boards-api.greenhouse.io/v1/boards/{t}/jobs", params={"content": "true"}, tries=2, quiet=True)
    if r is None or r.status_code != 200:
        return []
    out = []
    for j in r.json().get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        if prefilter(j.get("title"), loc):
            out.append(rec(f"Greenhouse ({t})", j.get("id"), j.get("title"), t, loc, j.get("absolute_url"),
                           text=j.get("content"), posted=j.get("first_published") or j.get("updated_at")))
    return out


def ats_lever(t):
    out = []
    for host in ("api.lever.co", "api.eu.lever.co"):
        r = get(f"https://{host}/v0/postings/{t}", params={"mode": "json"}, tries=2, quiet=True)
        if r is None or r.status_code != 200:
            continue
        try:
            data = r.json()
        except ValueError:
            continue
        for j in data if isinstance(data, list) else []:
            cat = j.get("categories") or {}
            loc = cat.get("location") or ", ".join(cat.get("allLocations") or [])
            text = " ".join([j.get("descriptionPlain") or "", j.get("additionalPlain") or ""] +
                            [(x.get("text") or "") + " " + clean_text(x.get("content")) for x in (j.get("lists") or [])])
            if prefilter(j.get("text"), loc):
                out.append(rec(f"Lever ({t})", j.get("id"), j.get("text"), t, loc, j.get("hostedUrl"), text=text,
                               posted=j.get("createdAt"), workplace=j.get("workplaceType")))
        if out:
            break
    return out


def ats_ashby(t):
    r = get(f"https://api.ashbyhq.com/posting-api/job-board/{t}", params={"includeCompensation": "true"},
            tries=2, quiet=True)
    if r is None or r.status_code != 200:
        return []
    out = []
    for j in r.json().get("jobs", []):
        locs = [j.get("location") or ""] + [x.get("location", "") for x in (j.get("secondaryLocations") or [])]
        loc = "; ".join(x for x in locs if x)
        if prefilter(j.get("title"), loc):
            comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
            out.append(rec(f"Ashby ({t})", j.get("id"), j.get("title"), t, loc, j.get("jobUrl"),
                           text=(j.get("descriptionPlain") or clean_text(j.get("descriptionHtml"))) + " " + comp,
                           posted=j.get("publishedAt"), remote=j.get("isRemote"), workplace=j.get("workplaceType")))
    return out


def ats_personio(t):
    out = []
    for dom in ("jobs.personio.de", "jobs.personio.com"):
        r = get(f"https://{t}.{dom}/xml", params={"language": "en"}, tries=2, quiet=True)
        if r is None or r.status_code != 200 or "<position" not in r.text:
            continue
        soup = BeautifulSoup(r.text, "xml")
        company = (soup.find("company") or {}).get_text() if soup.find("company") else t
        for p in soup.find_all("position"):
            title = p.find("name").get_text() if p.find("name") else ""
            offices = [o.get_text() for o in p.find_all("office")]
            loc = ", ".join(offices) + ", Germany" if offices else ""
            text = " ".join(clean_text(v.get_text()) for v in p.find_all("value"))
            seniority = p.find("seniority").get_text() if p.find("seniority") else None
            years = p.find("yearsOfExperience").get_text() if p.find("yearsOfExperience") else ""
            pid = p.find("id").get_text() if p.find("id") else ""
            # Personio boards list Austrian offices by city name; place_of resolves Vienna, Graz etc. first.
            if prefilter(title, loc):
                out.append(rec(f"Personio ({t})", pid, title, company or t, loc,
                               f"https://{t}.{dom}/job/{pid}?language=en", text=text + " " + years,
                               posted=p.find("createdAt").get_text() if p.find("createdAt") else None,
                               seniority=seniority))
        if out:
            break
    return out


def ats_smartrecruiters(t):
    out = []
    for offset in range(0, 1000, 100):
        r = get(f"https://api.smartrecruiters.com/v1/companies/{t}/postings", params={"limit": 100, "offset": offset},
                tries=2, quiet=True)
        if r is None or r.status_code != 200:
            break
        content = r.json().get("content") or []
        for j in content:
            locd = j.get("location") or {}
            loc = ", ".join(x for x in [locd.get("city"), locd.get("region"), locd.get("country")] if x)
            if locd.get("country", "").lower() == "de":
                loc += ", Germany"
            if locd.get("country", "").lower() == "at":
                loc += ", Austria"
            if prefilter(j.get("name"), loc):
                d = get(f"https://api.smartrecruiters.com/v1/companies/{t}/postings/{j.get('id')}", tries=2, quiet=True)
                text = ""
                if d is not None and d.status_code == 200:
                    secs = (d.json().get("jobAd") or {}).get("sections") or {}
                    text = " ".join(clean_text((v or {}).get("text")) for v in secs.values())
                out.append(rec(f"SmartRecruiters ({t})", j.get("id"), j.get("name"), (j.get("company") or {}).get("name") or t,
                               loc, f"https://jobs.smartrecruiters.com/{t}/{j.get('id')}", text=text,
                               posted=j.get("releasedDate"), remote=locd.get("remote"),
                               seniority=(j.get("experienceLevel") or {}).get("label")))
        if len(content) < 100:
            break
    return out


def ats_recruitee(t):
    r = get(f"https://{t}.recruitee.com/api/offers/", tries=2, quiet=True)
    if r is None or r.status_code != 200:
        return []
    out = []
    try:
        offers = r.json().get("offers", [])
    except ValueError:
        return []
    for j in offers:
        loc = ", ".join(x for x in [j.get("city"), j.get("country")] if x)
        if prefilter(j.get("title"), loc):
            out.append(rec(f"Recruitee ({t})", j.get("id"), j.get("title"), j.get("company_name") or t, loc,
                           j.get("careers_url"), text=(j.get("description") or "") + " " + (j.get("requirements") or ""),
                           posted=j.get("published_at") or j.get("created_at"), remote=j.get("remote")))
    return out


SR_IDS = ["BoschGroup", "DeliveryHero", "RedBull", "Sportradar", "AUTO1Group", "Visa", "Continental", "Henkel",
          "DBSchenker", "Lufthansa", "Allianz", "Siemens", "SAP", "Infineon", "PUMA", "Adidas", "Zeiss", "Bayer",
          "MerckKGaA", "BoehringerIngelheim", "Sixt", "Vodafone", "Telefonica", "IKEA", "Ubisoft", "Wargaming",
          "Celonis", "Dynatrace", "Flix", "FlixBus", "Zalando", "TeamViewer", "Freudenberg", "Schaeffler", "ZF", "MAN"]


def ats():
    items = []
    funcs = [ats_greenhouse, ats_lever, ats_ashby, ats_personio, ats_recruitee]
    jobs = [(f, t) for t in COMPANIES for f in funcs] + [(ats_smartrecruiters, t) for t in SR_IDS]
    found = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for (f, t), res in zip(jobs, ex.map(lambda ft: ft[0](ft[1]), jobs)):
            if res:
                found[(f.__name__, t)] = len(res)
                items.extend(res)
    log("ATS boards with matches:", found)
    log("ATS kept", len(items))
    save("ats", items)


# ------------------------------------------------------------------ Austria: karriere.at

def jsonld_jobposting(html_text):
    soup = BeautifulSoup(html_text, "lxml")
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except Exception:
            continue
        for d in data if isinstance(data, list) else [data]:
            if isinstance(d, dict) and d.get("@type") == "JobPosting":
                return d
            if isinstance(d, dict) and "@graph" in d:
                for g in d["@graph"]:
                    if isinstance(g, dict) and g.get("@type") == "JobPosting":
                        return g
    return None


def page_text(html_text):
    soup = BeautifulSoup(html_text, "lxml")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)[:20000]


def jobposting_record(source, sid, url, jp, fallback_text=""):
    org = jp.get("hiringOrganization") or {}
    if isinstance(org, list):
        org = org[0] if org else {}
    locs = jp.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    parts = []
    for l in locs:
        a = (l or {}).get("address") or {}
        if isinstance(a, dict):
            parts.append(", ".join(x for x in [a.get("addressLocality"), a.get("addressRegion"),
                                               a.get("addressCountry") if isinstance(a.get("addressCountry"), str) else
                                               (a.get("addressCountry") or {}).get("name")] if x))
    loc = "; ".join(p for p in parts if p)
    return rec(source, sid, jp.get("title"), org.get("name") if isinstance(org, dict) else str(org), loc, url,
               text=(jp.get("description") or "") + " " + fallback_text, posted=jp.get("datePosted"),
               workplace=jp.get("jobLocationType"),
               extra={"validThrough": jp.get("validThrough"), "employmentType": jp.get("employmentType"),
                      "baseSalary": jp.get("baseSalary")})


def karriere():
    items, links = [], set()
    slugs = ["data-analyst", "junior-data-analyst", "data-scientist", "junior-data-scientist", "business-intelligence",
             "bi-analyst", "analytics-engineer", "machine-learning", "data-analytics", "english", "data"]
    for slug in slugs:
        for page in range(1, 8):
            url = f"https://www.karriere.at/jobs/{slug}/oesterreich" + (f"?page={page}" if page > 1 else "")
            r = get(url, quiet=True)
            if r is None or r.status_code != 200:
                log("karriere status", None if r is None else r.status_code, url)
                break
            found = set(re.findall(r"https://www\.karriere\.at/jobs/(\d{6,9})", r.text))
            if not found - links:
                break
            links |= found
            time.sleep(0.8)
    log("karriere job links", len(links))
    for i, jid in enumerate(sorted(links)):
        url = f"https://www.karriere.at/jobs/{jid}"
        r = get(url, quiet=True)
        if r is None or r.status_code != 200:
            continue
        jp = jsonld_jobposting(r.text)
        if not jp:
            continue
        it = jobposting_record("karriere.at", jid, url, jp)
        if it["location"] and "austria" not in it["location"].lower() and "österreich" not in it["location"].lower():
            it["location"] += ", Austria"
        if prefilter(it["title"], it["location"]):
            items.append(it)
        time.sleep(0.6)
        if i % 50 == 0:
            log("karriere detail", i, "/", len(links))
    save("karriere", items)


# ------------------------------------------------------------------ devjobs.at / devjobs.de

def devjobs():
    items, links = [], set()
    for host, country in (("devjobs.at", "AT"), ("devjobs.de", "DE")):
        for slug in ["data-analyst", "data-scientist", "bi-data-analyst", "junior-job-level-python", "machine-learning",
                     "analytics-engineer", "junior-job-level-sql", "junior-job-level-power-bi", "ai-data-scientist"]:
            r = get(f"https://en.{host}/jobs/{slug}", quiet=True)
            if r is None or r.status_code != 200:
                continue
            for h in re.findall(r"/job/([0-9a-f]{32})", r.text):
                links.add((host, h))
            time.sleep(0.6)
    log("devjobs links", len(links))
    for host, h in sorted(links):
        url = f"https://en.{host}/job/{h}"
        r = get(url, quiet=True)
        if r is None or r.status_code != 200:
            continue
        jp = jsonld_jobposting(r.text)
        if jp:
            it = jobposting_record(f"{host}", h, url, jp, fallback_text=page_text(r.text)[:6000])
        else:
            continue
        if "expired" in r.text.lower() and "this job has expired" in r.text.lower():
            it["extra"]["closed"] = True
        if prefilter(it["title"], it["location"]):
            items.append(it)
        time.sleep(0.6)
    save("devjobs", items)


# ------------------------------------------------------------------ Berlin Startup Jobs (RSS) and GermanTechJobs

def bsj():
    items = []
    feeds = ["https://berlinstartupjobs.com/skill-areas/data-science/feed/", "https://berlinstartupjobs.com/feed/?s=data+analyst",
             "https://berlinstartupjobs.com/feed/?s=data+scientist", "https://berlinstartupjobs.com/feed/?s=analytics"]
    seen = set()
    for f in feeds:
        r = get(f, quiet=True)
        if r is None or r.status_code != 200:
            continue
        soup = BeautifulSoup(r.text, "xml")
        for it in soup.find_all("item"):
            link = it.find("link").get_text() if it.find("link") else ""
            if link in seen:
                continue
            seen.add(link)
            title_full = it.find("title").get_text() if it.find("title") else ""
            title, _, company = title_full.partition("//")
            desc = it.find("encoded") or it.find("description")
            if prefilter(title, "Berlin, Germany"):
                items.append(rec("Berlin Startup Jobs", link, title, company, "Berlin, Germany", link,
                                 text=desc.get_text() if desc else "", posted=it.find("pubDate").get_text() if it.find("pubDate") else None))
    for it in items:
        if it["posted"] is None:
            continue
    save("bsj", items)


def gtj():
    items = []
    r = get("https://germantechjobs.de/api/jobsLight", quiet=True)
    if r is None or r.status_code != 200:
        log("germantechjobs status", None if r is None else r.status_code)
        save("gtj", items)
        return
    try:
        data = r.json()
    except ValueError:
        save("gtj", items)
        return
    for j in data:
        title = j.get("name") or j.get("title")
        loc = (j.get("actualCity") or j.get("cityCategory") or "") + ", Germany"
        if prefilter(title, loc):
            url = "https://germantechjobs.de/jobs/" + (j.get("jobUrl") or "")
            items.append(rec("GermanTechJobs", j.get("_id") or j.get("jobUrl"), title, j.get("company"), loc, url,
                             posted=j.get("activeFrom"), workplace=j.get("workplace"),
                             seniority=j.get("expLevel"), extra={"language": j.get("language")}))
    for it in items:
        r = get(it["url"], quiet=True)
        if r is not None and r.status_code == 200:
            jp = jsonld_jobposting(r.text)
            it["text"] = (jp or {}).get("description") or page_text(r.text)[:8000]
        time.sleep(0.5)
    save("gtj", items)


SOURCES = {"linkedin": linkedin, "arbeitnow": arbeitnow, "ba": ba, "ats": ats, "karriere": karriere,
           "devjobs": devjobs, "bsj": bsj, "gtj": gtj}

if __name__ == "__main__":
    wanted = sys.argv[2:] or list(SOURCES)
    for name in wanted:
        log("=== source", name)
        try:
            SOURCES[name]()
        except Exception as e:
            log("SOURCE FAILED", name, type(e).__name__, e)
    log("done")
