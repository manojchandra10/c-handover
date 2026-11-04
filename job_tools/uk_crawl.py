#!/usr/bin/env python3
"""Check UK licensed sponsors' own careers pages for live entry-level data roles, and collect public recruitment emails.

Usage (from the repository root, in a session with full network access):
  python3 -I job_tools/uk_crawl.py <shortlist.csv> <data_dir> [--tiers A,B,C] [--limit N] [--workers 12]
        [--sites my_sites.csv] [--only "name text"] [--sources careers,jobsacuk,analysis,findajob] [--no-probe]

<shortlist.csv> comes from uk_shortlist.py. For each company, in priority order:
  1 find its website: your sites file (columns Organisation,Website), a short list of known domains, then guessed
    domains that are only accepted when the company's name appears on the page
  2 find its careers page and any hiring system linked from it (Greenhouse, Lever, Ashby, Workable, SmartRecruiters,
    Recruitee, Personio, Pinpoint, BambooHR, Breezy, Teamtailor, Workday, Oracle, Eightfold)
  3 read every advert there, keep UK roles in the wanted families (uk_rules.py) and record why others were left out
  4 pick role-based public addresses (careers@, recruitment@, hr@, info@ and similar) from the company's own pages
Sources jobsacuk, analysis and findajob search jobs.ac.uk, the Civil Service Analysis Function vacancy list and the
DWP Find a Job service, and match each employer to the shortlist.
Writes <data_dir>/companies.jsonl and <data_dir>/roles.jsonl, and resumes from them if they already exist.
robots.txt is respected for every web page; requests to the same host are spaced out.
"""
import sys, os, re, json, time, threading, argparse, datetime as dt
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote_plus
from urllib import robotparser
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parent))
import uk_rules as R
import requests
from bs4 import BeautifulSoup

UA = os.environ.get("UK_CRAWL_UA", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/124.0 Safari/537.36 uk-careers-check/1.0")
ROBOTS_AGENT = "uk-careers-check"
TEST_BASE = os.environ.get("UK_CRAWL_TEST_BASE")   # tests only: every https:// request goes to this local server
MAX_BYTES = 2_500_000
TODAY = dt.date.today()

# ---------------------------------------------------------------- fetching

_local = threading.local()
_host_lock = threading.Lock()
_host_next = {}
_robots, _robots_lock = {}, threading.Lock()
API_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com", "recruitee.com",
             "personio.de", "personio.com", "pinpointhq.com", "bamboohr.com", "breezy.hr", "myworkdayjobs.com",
             "oraclecloud.com", "eightfold.ai", "teamtailor.com")


class Resp:
    def __init__(self, status, url, text, ctype):
        self.status, self.url, self.text, self.ctype = status, url, text, ctype

    def json(self):
        return json.loads(self.text)

    @property
    def ok_html(self):
        return self.status == 200 and ("html" in self.ctype or self.text.lstrip()[:1] == "<")


def _session():
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9"})
        _local.s = s
    return s


def _route(url):
    if TEST_BASE and url.startswith("https://"):
        return TEST_BASE.rstrip("/") + "/ext/" + url[len("https://"):]
    return url


def _is_api(host):
    return any(host == h or host.endswith("." + h) for h in API_HOSTS)


def _wait_turn(host):
    gap = 0.0 if TEST_BASE else 0.35 if _is_api(host) else 1.0
    with _host_lock:
        now = time.monotonic()
        t = max(now, _host_next.get(host, 0.0))
        _host_next[host] = t + gap
    if t > now:
        time.sleep(t - now)


def robots_ok(url):
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    with _robots_lock:
        rp = _robots.get(base)
    if rp is None:
        rp = robotparser.RobotFileParser()
        r = fetch(base + "/robots.txt", check_robots=False, timeout=8)
        if r is not None and r.status == 200 and len(r.text) < 500_000:
            rp.parse(r.text.splitlines())
        elif r is not None and r.status in (401, 403):
            rp.parse([])
            rp.disallow_all = True
        else:
            rp.parse([])
        with _robots_lock:
            _robots[base] = rp
    return rp.can_fetch(ROBOTS_AGENT, url)


def set_budget(n):
    _local.budget = n


def fetch(url, method="GET", check_robots=True, timeout=15, json_body=None, params=None, headers=None, tries=2):
    """Return a Resp, None on network error or when this company's request budget is spent,
    or Resp(status=-1) when robots.txt asks us not to fetch the page."""
    budget = getattr(_local, "budget", None)
    if budget is not None:
        if budget <= 0:
            return None
        _local.budget = budget - 1
    host = urlparse(url).netloc
    if check_robots and not _is_api(host) and not robots_ok(url):
        return Resp(-1, url, "", "")
    for attempt in range(tries):
        try:
            _wait_turn(host)
            r = _session().request(method, _route(url), params=params, json=json_body, headers=headers,
                                   timeout=(7, timeout), stream=True, allow_redirects=True)
            chunks, size = [], 0
            for chunk in r.iter_content(65536):
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BYTES:
                    break
            r.close()
            text = b"".join(chunks).decode(r.encoding or "utf-8", errors="replace")
            if r.status_code in (429, 502, 503, 504) and attempt < tries - 1:
                time.sleep(4)
                continue
            final = r.url
            if TEST_BASE and final.startswith(TEST_BASE.rstrip("/") + "/ext/"):
                final = "https://" + final[len(TEST_BASE.rstrip("/") + "/ext/"):]
            return Resp(r.status_code, final, text, r.headers.get("content-type", ""))
        except requests.RequestException:
            if attempt < tries - 1:
                time.sleep(1.5)
    return None


_dns_cache, _dns_lock = {}, threading.Lock()
DNS_WORKS = None


def resolves(host):
    """True or False when local DNS can tell; True when this machine cannot resolve anything (proxy-only network)."""
    global DNS_WORKS
    import socket
    if TEST_BASE:
        return True
    if DNS_WORKS is None:
        try:
            socket.getaddrinfo("www.gov.uk", 443)
            DNS_WORKS = True
        except OSError:
            DNS_WORKS = False
    if not DNS_WORKS:
        return True
    with _dns_lock:
        if host in _dns_cache:
            return _dns_cache[host]
    try:
        socket.getaddrinfo(host, 443)
        ok = True
    except OSError:
        ok = False
    with _dns_lock:
        _dns_cache[host] = ok
    return ok


def get_json(url, **kw):
    r = fetch(url, **kw)
    if r is None or r.status != 200:
        return None
    try:
        return r.json()
    except ValueError:
        return None


# ---------------------------------------------------------------- page helpers

def soup_of(html):
    return BeautifulSoup(html or "", "lxml")


def page_text(html, limit=25000):
    s = soup_of(html)
    for t in s(["script", "style", "noscript", "svg"]):
        t.decompose()
    return " ".join(s.get_text(" ", strip=True).split())[:limit]


def page_title(html):
    s = soup_of(html)
    parts = [s.title.get_text(" ", strip=True) if s.title else ""]
    for m in s.find_all("meta", attrs={"property": "og:site_name"}) + s.find_all("meta", attrs={"name": "application-name"}):
        parts.append(m.get("content") or "")
    return " ".join(parts)


def _jp_location(jp):
    locs = jp.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    parts = []
    for l in locs:
        a = (l or {}).get("address") or {}
        if isinstance(a, str):
            parts.append(a)
            continue
        if isinstance(a, dict):
            c = a.get("addressCountry")
            c = c.get("name") if isinstance(c, dict) else c
            parts.append(", ".join(str(x) for x in [a.get("addressLocality"), a.get("addressRegion"), c] if x))
    if jp.get("jobLocationType") == "TELECOMMUTE" and not parts:
        parts.append("Remote")
    return "; ".join(p for p in parts if p)


def _walk_ld(d):
    if isinstance(d, list):
        for x in d:
            yield from _walk_ld(x)
    elif isinstance(d, dict):
        t = d.get("@type")
        if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
            yield d
        for k in ("@graph", "itemListElement", "item"):
            if k in d:
                yield from _walk_ld(d[k])


def jsonld_jobs(html, url):
    """Every schema.org JobPosting on the page."""
    out = []
    for s in soup_of(html).find_all("script", type=re.compile("ld\\+json", re.I)):
        try:
            data = json.loads(s.string or s.get_text() or "")
        except ValueError:
            continue
        for jp in _walk_ld(data):
            org = jp.get("hiringOrganization") or {}
            if isinstance(org, list):
                org = org[0] if org else {}
            out.append({"title": R.clean_text(jp.get("title") or ""), "location": _jp_location(jp),
                        "url": jp.get("url") or url, "text": R.clean_text(jp.get("description") or ""),
                        "posted": str(jp.get("datePosted") or "")[:10], "valid_through": str(jp.get("validThrough") or "")[:10],
                        "employer": org.get("name") if isinstance(org, dict) else "", "how": "Job page (schema.org data)"})
    return out


CAREER_TEXT = re.compile(r"^\s*(careers?|jobs?|vacanc(y|ies)|current vacancies|join (us|our team|the team)|work (with|for) us|"
                         r"working (here|with us|at \w+)|opportunities|recruitment|open (roles|positions)|we'?re hiring|"
                         r"graduates?|early careers|life at \w+)\s*$", re.I)
CAREER_HREF = re.compile(r"(career|/jobs?\b|/jobs?/|vacanc|join-?us|work-?(with|for)-?us|opportunit|recruit|hiring|graduate|early-careers)", re.I)
COMMON_PATHS = ["careers", "jobs", "vacancies", "join-us", "work-with-us", "work-for-us", "about/careers", "about-us/careers",
                "current-vacancies", "join"]


def same_site(url, site):
    return R.registrable(urlparse(url).netloc) == R.registrable(urlparse(site).netloc)


def careers_links(html, base):
    """Careers-looking links on the same site, best first."""
    ranked = []
    for i, a in enumerate(soup_of(html).find_all("a", href=True)):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        u = urljoin(base, href).split("#")[0]
        if not same_site(u, base) or _is_api(urlparse(u).netloc):
            continue
        text = " ".join(a.get_text(" ", strip=True).split())
        if CAREER_TEXT.match(text):
            ranked.append((0, i, u))
        elif CAREER_HREF.search(urlparse(u).path):
            ranked.append((1, i, u))
    seen, out = set(), []
    for _, _, u in sorted(ranked):
        if u not in seen and u.rstrip("/") != base.rstrip("/"):
            seen.add(u)
            out.append(u)
    return out[:6]


ATS_PATTERNS = [
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?([A-Za-z0-9_-]+)"),
    ("greenhouse", r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)"),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_.-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)"),
    ("workable", r"apply\.workable\.com/([A-Za-z0-9_-]+)"),
    ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    ("recruitee", r"([A-Za-z0-9-]+)\.recruitee\.com"),
    ("personio", r"([A-Za-z0-9-]+)\.jobs\.personio\.(?:de|com)"),
    ("teamtailor", r"([A-Za-z0-9-]+)\.teamtailor\.com"),
    ("pinpoint", r"([A-Za-z0-9-]+)\.pinpointhq\.com"),
    ("bamboohr", r"([A-Za-z0-9-]+)\.bamboohr\.com"),
    ("breezy", r"([A-Za-z0-9-]+)\.breezy\.hr"),
    ("workday", r"([A-Za-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)"),
    ("oracle", r"([a-z0-9-]+\.fa\.[a-z0-9-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-zA-Z-]+/sites/([A-Za-z0-9_]+)"),
    ("eightfold", r"([a-z0-9-]+)\.eightfold\.ai/careers"),
]
ATS_PATTERNS = [(k, re.compile(p)) for k, p in ATS_PATTERNS]
SLUG_STOP = {"www", "app", "api", "help", "support", "status", "cdn", "assets", "static", "resources", "blog", "embed",
             "jobs", "careers", "apply", "js", "css", "images", "img", "media", "widget", "widgets", "en", "en-gb", "v1"}


def detect_ats(html):
    found = set()
    for kind, rx in ATS_PATTERNS:
        for m in rx.finditer(html or ""):
            g = m.groups()
            if kind == "workday":
                if g[2].lower() not in SLUG_STOP and g[2].lower() != "wday":
                    found.add((kind, f"{g[0]}|{g[1]}|{g[2]}"))
            elif kind == "oracle":
                found.add((kind, f"{g[0]}|{g[1]}"))
            elif g[0].lower() not in SLUG_STOP:
                found.add((kind, g[0]))
    return found


# ---------------------------------------------------------------- hiring-system readers (public job board APIs)

def _job(title, location, url, text="", posted="", valid_through="", employer="", how=""):
    return {"title": R.clean_text(title or ""), "location": location or "", "url": url or "", "text": R.clean_text(text or ""),
            "posted": str(posted or "")[:10], "valid_through": str(valid_through or "")[:10], "employer": employer or "", "how": how}


def _wanted(title):
    return R.classify_title(title)[0] is not None


def _ms(v):
    try:
        return dt.datetime.utcfromtimestamp(int(v) / 1000).date().isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def read_greenhouse(slug, site=None):
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"})
    if not d:
        return [], ""
    meta = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}") or {}
    out = [_job(j.get("title"), (j.get("location") or {}).get("name", ""), j.get("absolute_url"), j.get("content"),
                j.get("first_published") or j.get("updated_at"), how=f"Greenhouse board ({slug})")
           for j in d.get("jobs", [])]
    return out, meta.get("name", "")


def read_lever(slug, site=None):
    for host in ("api.lever.co", "api.eu.lever.co"):
        d = get_json(f"https://{host}/v0/postings/{slug}", params={"mode": "json"})
        if isinstance(d, list) and d:
            out = []
            for j in d:
                cat = j.get("categories") or {}
                text = " ".join([j.get("descriptionPlain") or "", j.get("additionalPlain") or ""] +
                                [(x.get("text") or "") + " " + R.clean_text(x.get("content")) for x in (j.get("lists") or [])])
                loc = cat.get("location") or ", ".join(cat.get("allLocations") or [])
                if j.get("workplaceType"):
                    text += f" Workplace: {j['workplaceType']}."
                out.append(_job(j.get("text"), loc, j.get("hostedUrl"), text, _ms(j.get("createdAt")), how=f"Lever board ({slug})"))
            return out, ""
    return [], ""


def read_ashby(slug, site=None):
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", params={"includeCompensation": "true"})
    if not d:
        return [], ""
    out = []
    for j in d.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [x.get("location", "") for x in (j.get("secondaryLocations") or [])]
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        text = (j.get("descriptionPlain") or R.clean_text(j.get("descriptionHtml"))) + " " + comp
        if j.get("workplaceType"):
            text += f" Workplace: {j['workplaceType']}."
        out.append(_job(j.get("title"), "; ".join(x for x in locs if x), j.get("jobUrl"), text, j.get("publishedAt"),
                        how=f"Ashby board ({slug})"))
    return out, ""


def read_workable(slug, site=None):
    d = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}", params={"details": "true"})
    if not d:
        return [], ""
    out = []
    for j in d.get("jobs", []):
        loc = ", ".join(x for x in [j.get("city"), j.get("state"), j.get("country")] if x)
        if j.get("telecommuting"):
            loc += " (remote)"
        out.append(_job(j.get("title"), loc, j.get("url") or j.get("shortlink"), j.get("description"),
                        j.get("published_on") or j.get("created_at"), how=f"Workable board ({slug})"))
    return out, d.get("name", "")


def read_smartrecruiters(slug, site=None):
    out, name = [], ""
    for offset in range(0, 600, 100):
        d = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", params={"limit": 100, "offset": offset})
        if not d:
            break
        content = d.get("content") or []
        for j in content:
            name = name or (j.get("company") or {}).get("name", "")
            l = j.get("location") or {}
            loc = ", ".join(x for x in [l.get("city"), l.get("region"), l.get("country")] if x)
            if l.get("country", "").lower() in ("gb", "uk"):
                loc += ", United Kingdom"
            text = ""
            if _wanted(j.get("name")):
                det = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{j.get('id')}") or {}
                secs = (det.get("jobAd") or {}).get("sections") or {}
                text = " ".join(R.clean_text((v or {}).get("text")) for v in secs.values())
            out.append(_job(j.get("name"), loc, f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}", text,
                            j.get("releasedDate"), how=f"SmartRecruiters board ({slug})"))
        if len(content) < 100:
            break
    return out, name


def read_recruitee(slug, site=None):
    d = get_json(f"https://{slug}.recruitee.com/api/offers/")
    if not d:
        return [], ""
    out, name = [], ""
    for j in d.get("offers", []):
        name = name or j.get("company_name", "")
        loc = ", ".join(x for x in [j.get("city"), j.get("country")] if x)
        out.append(_job(j.get("title"), loc, j.get("careers_url"), (j.get("description") or "") + " " + (j.get("requirements") or ""),
                        j.get("published_at") or j.get("created_at"), how=f"Recruitee board ({slug})"))
    return out, name


def read_personio(slug, site=None):
    for dom in ("jobs.personio.de", "jobs.personio.com"):
        r = fetch(f"https://{slug}.{dom}/xml", params={"language": "en"})
        if r is None or r.status != 200 or "<position" not in r.text:
            continue
        x = BeautifulSoup(r.text, "xml")
        out = []
        for p in x.find_all("position"):
            g = lambda tag: p.find(tag).get_text() if p.find(tag) else ""
            offices = [o.get_text() for o in p.find_all("office")]
            out.append(_job(g("name"), ", ".join(offices), f"https://{slug}.{dom}/job/{g('id')}?language=en",
                            " ".join(v.get_text() for v in p.find_all("value")) + " " + g("yearsOfExperience"),
                            g("createdAt"), how=f"Personio board ({slug})"))
        return out, (x.find("company").get_text() if x.find("company") else "")
    return [], ""


def read_pinpoint(slug, site=None):
    d = get_json(f"https://{slug}.pinpointhq.com/postings.json")
    rows = (d or {}).get("data") if isinstance(d, dict) else None
    if not rows:
        return [], ""
    out = []
    for j in rows:
        a = j.get("attributes") if isinstance(j.get("attributes"), dict) else j
        loc = a.get("location") or {}
        loc = loc.get("name") or loc.get("city") or "" if isinstance(loc, dict) else str(loc)
        url = a.get("url") or (f"https://{slug}.pinpointhq.com" + a["path"] if a.get("path") else "")
        out.append(_job(a.get("title"), loc, url, a.get("description") or a.get("content") or "",
                        a.get("published_at") or a.get("created_at"), a.get("deadline_at") or "", how=f"Pinpoint board ({slug})"))
    return out, ""


def read_bamboohr(slug, site=None):
    d = get_json(f"https://{slug}.bamboohr.com/careers/list")
    if not d:
        return [], ""
    out = []
    for j in d.get("result", []):
        l = j.get("location") or {}
        loc = ", ".join(x for x in [l.get("city"), l.get("state"), l.get("country")] if x)
        text = ""
        if _wanted(j.get("jobOpeningName")):
            det = get_json(f"https://{slug}.bamboohr.com/careers/{j.get('id')}/detail") or {}
            text = R.clean_text(((det.get("result") or {}).get("jobOpening") or {}).get("description"))
        out.append(_job(j.get("jobOpeningName"), loc, f"https://{slug}.bamboohr.com/careers/{j.get('id')}", text,
                        how=f"BambooHR board ({slug})"))
    return out, ""


def read_breezy(slug, site=None):
    d = get_json(f"https://{slug}.breezy.hr/json")
    if not isinstance(d, list):
        return [], ""
    out = []
    for j in d:
        l = j.get("location") or {}
        loc = l.get("name") or ", ".join(x for x in [l.get("city"), (l.get("country") or {}).get("name")] if x)
        text = ""
        if _wanted(j.get("name")) and j.get("url"):
            r = fetch(j["url"])
            text = page_text(r.text) if r is not None and r.ok_html else ""
        out.append(_job(j.get("name"), loc, j.get("url"), text, j.get("published_date"), how=f"Breezy board ({slug})"))
    return out, ""


def read_teamtailor(slug, site=None):
    base = f"https://{slug}.teamtailor.com"
    r = fetch(base + "/jobs")
    if r is None or not r.ok_html:
        return [], ""
    return follow_job_links(r.text, r.url, base, how=f"Teamtailor board ({slug})"), ""


SEARCH_WORDS = ["graduate", "junior", "data analyst", "data scientist", "statistician", "associate", "consultant", "entry level"]


def read_workday(key, site=None):
    tenant, wd, board = key.split("|")
    host = f"https://{tenant}.{wd}.myworkdayjobs.com"
    api = f"{host}/wday/cxs/{tenant}/{board}"
    seen, out = set(), []
    for kw in SEARCH_WORDS:
        for offset in (0, 20, 40):
            d = get_json(f"{api}/jobs", method="POST", json_body={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": kw})
            posts = (d or {}).get("jobPostings") or []
            for j in posts:
                path = j.get("externalPath")
                if not path or path in seen:
                    continue
                seen.add(path)
                if not _wanted(j.get("title")):
                    continue
                det = (get_json(f"{api}{path}") or {}).get("jobPostingInfo") or {}
                loc = det.get("location") or j.get("locationsText") or ""
                if det.get("country"):
                    loc += f", {(det.get('country') or {}).get('descriptor', '')}"
                out.append(_job(j.get("title"), loc, det.get("externalUrl") or f"{host}/{board}{path}",
                                det.get("jobDescription", ""), det.get("startDate", ""), det.get("endDate", ""),
                                how=f"Workday board ({tenant})"))
            if len(posts) < 20:
                break
    return out, ""


def read_oracle(key, site=None):
    host, site_no = key.split("|")
    out, seen = [], set()
    for kw in SEARCH_WORDS:
        url = (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList"
               f"&finder=findReqs;siteNumber={site_no},limit=50,keyword={quote_plus(kw)}")
        d = get_json(url) or {}
        for item in d.get("items", []):
            for j in item.get("requisitionList", []) or []:
                jid = j.get("Id")
                if not jid or jid in seen or not _wanted(j.get("Title")):
                    continue
                seen.add(jid)
                det_url = (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails?expand=all&onlyData=true"
                           f"&finder=ById;Id=%22{jid}%22,siteNumber={site_no}")
                det = ((get_json(det_url) or {}).get("items") or [{}])[0]
                text = " ".join(R.clean_text(det.get(k)) for k in ("ExternalDescriptionStr", "ExternalQualificationsStr",
                                                                     "ExternalResponsibilitiesStr") if det.get(k))
                out.append(_job(j.get("Title"), j.get("PrimaryLocation", ""),
                                f"https://{host}/hcmUI/CandidateExperience/en/sites/{site_no}/job/{jid}", text,
                                j.get("PostedDate", ""), det.get("ExternalPostedEndDate", "") or "", how=f"Oracle careers site ({host.split('.')[0]})"))
    return out, ""


def read_eightfold(sub, site=None):
    dom = R.registrable(urlparse(site).netloc) if site else ""
    out, seen = [], set()
    for kw in SEARCH_WORDS:
        d = get_json(f"https://{sub}.eightfold.ai/api/apply/v2/jobs", params={"domain": dom, "query": kw, "location": "United Kingdom",
                                                                              "start": 0, "num": 50}) or {}
        for j in d.get("positions", []) or []:
            jid = j.get("id")
            if jid in seen or not _wanted(j.get("name")):
                continue
            seen.add(jid)
            out.append(_job(j.get("name"), j.get("location", ""), j.get("canonicalPositionUrl") or f"https://{sub}.eightfold.ai/careers?pid={jid}",
                            j.get("job_description", ""), _ms((j.get("t_create") or 0) * 1000), how=f"Eightfold careers site ({sub})"))
    return out, ""


READERS = {"greenhouse": read_greenhouse, "lever": read_lever, "ashby": read_ashby, "workable": read_workable,
           "smartrecruiters": read_smartrecruiters, "recruitee": read_recruitee, "personio": read_personio,
           "pinpoint": read_pinpoint, "bamboohr": read_bamboohr, "breezy": read_breezy, "teamtailor": read_teamtailor,
           "workday": read_workday, "oracle": read_oracle, "eightfold": read_eightfold}
PROBE = ["greenhouse", "workable", "ashby", "lever", "recruitee", "smartrecruiters", "personio"]   # boards that can be found by name


# ---------------------------------------------------------------- careers pages without a hiring system

LOOSE_JOB = re.compile(r"\b(analyst|scientist|statistician|graduate|consultant|associate|data)\b", re.I)
NO_VACANCIES = re.compile(r"\b(no (current )?(vacancies|openings|opportunities|positions|roles)|not currently recruiting|"
                          r"no open (roles|positions)|there are currently no)\b", re.I)


def follow_job_links(html, base, site, how="Careers page link", limit=12):
    """Open links whose text looks like a wanted job title; read JSON-LD or the page text."""
    out, seen = [], set()
    for a in soup_of(html).find_all("a", href=True):
        text = " ".join(a.get_text(" ", strip=True).split())
        if not text or len(text) > 140 or not LOOSE_JOB.search(text):
            continue
        u = urljoin(base, a["href"]).split("#")[0]
        if u in seen or u.rstrip("/") == base.rstrip("/") or not (same_site(u, site) or _is_api(urlparse(u).netloc)):
            continue
        if not _wanted(text):
            continue
        seen.add(u)
        if len(seen) > limit:
            break
        r = fetch(u)
        if r is None or not r.ok_html:
            continue
        jl = jsonld_jobs(r.text, r.url)
        if jl:
            for j in jl:
                j["how"] = how + " (schema.org data)"
            out.extend(jl)
            continue
        s = soup_of(r.text)
        h1 = s.find("h1")
        title = h1.get_text(" ", strip=True) if h1 and _wanted(h1.get_text(" ", strip=True)) else text
        out.append(_job(title, "", r.url, page_text(r.text), how=how))
    return out


def inline_jobs(html, url):
    """Wanted job titles written as headings on the careers page itself, with the text under each heading."""
    out = []
    s = soup_of(html)
    for h in s.find_all(["h2", "h3", "h4", "h5", "strong", "b"]):
        title = " ".join(h.get_text(" ", strip=True).split())
        if not title or len(title) > 120 or not _wanted(title):
            continue
        parts, n = [], 0
        for sib in h.find_all_next():
            if sib.name in ("h1", "h2", "h3", "h4") and sib is not h:
                break
            if sib.name in ("p", "li", "span", "div") and not sib.find(["p", "li", "div"]):
                parts.append(sib.get_text(" ", strip=True))
                n += len(parts[-1])
            if n > 4000:
                break
        out.append(_job(title, "", url, " ".join(parts), how="Listed on the careers page (no separate advert)"))
    return out


# ---------------------------------------------------------------- finding the company website

GENERIC = set("""the limited ltd llp plc lp inc uk u.k group holdings holding co company international services service solutions
europe european global partners partner partnership capital consulting consultancy consultants consultant management managers
investment investments investors financial finance advisory advisors advisers adviser asset assets wealth fund funds data analytics
analysis research institute centre center london british england scottish welsh english national trust foundation association
society bank banking insurance brokers broker securities markets trading technologies technology tech systems digital software
labs lab and of for t/a ta a an in on at by intelligence insights insight economics strategic strategy branch office
representative uk-branch""".split())

KNOWN_SITES = {   # start of the register name (lower case, "the" and brackets removed) -> domain
    "university college london": "ucl.ac.uk", "imperial college london": "imperial.ac.uk",
    "london school of economics and political science": "lse.ac.uk", "king's college london": "kcl.ac.uk",
    "university of oxford": "ox.ac.uk", "university of cambridge": "cam.ac.uk", "university of edinburgh": "ed.ac.uk",
    "university of glasgow": "gla.ac.uk", "university of strathclyde": "strath.ac.uk", "queen mary university of london": "qmul.ac.uk",
    "newcastle university": "ncl.ac.uk", "loughborough university": "lboro.ac.uk", "university of st andrews": "st-andrews.ac.uk",
    "university of east anglia": "uea.ac.uk", "university of east london": "uel.ac.uk", "university of the west of england": "uwe.ac.uk",
    "manchester metropolitan university": "mmu.ac.uk", "liverpool john moores university": "ljmu.ac.uk",
    "university of central lancashire": "uclan.ac.uk", "anglia ruskin university": "aru.ac.uk", "london south bank university": "lsbu.ac.uk",
    "university of hertfordshire": "herts.ac.uk", "birkbeck": "bbk.ac.uk", "brunel university": "brunel.ac.uk",
    "middlesex university": "mdx.ac.uk", "university of greenwich": "gre.ac.uk", "university of portsmouth": "port.ac.uk",
    "oxford brookes university": "brookes.ac.uk", "de montfort university": "dmu.ac.uk", "nottingham trent university": "ntu.ac.uk",
    "sheffield hallam university": "shu.ac.uk", "heriot-watt university": "hw.ac.uk", "university of aberdeen": "abdn.ac.uk",
    "university of stirling": "stir.ac.uk", "queen's university belfast": "qub.ac.uk", "university of leicester": "le.ac.uk",
    "university of huddersfield": "hud.ac.uk", "london school of hygiene": "lshtm.ac.uk", "goldsmiths": "gold.ac.uk",
    "royal holloway": "royalholloway.ac.uk", "city, university of london": "city.ac.uk", "city university of london": "city.ac.uk",
    "aberystwyth university": "aber.ac.uk", "university of westminster": "westminster.ac.uk",
    "office for national statistics": "ons.gov.uk", "bank of england": "bankofengland.co.uk", "financial conduct authority": "fca.org.uk",
    "met office": "metoffice.gov.uk", "ordnance survey": "os.uk", "greater london authority": "london.gov.uk",
    "transport for london": "tfl.gov.uk", "alan turing institute": "turing.ac.uk", "francis crick institute": "crick.ac.uk",
    "institute for fiscal studies": "ifs.org.uk", "resolution foundation": "resolutionfoundation.org", "cancer research uk": "cancerresearchuk.org",
    "wellcome trust": "wellcome.org", "national audit office": "nao.org.uk", "uk research and innovation": "ukri.org", "ofcom": "ofcom.org.uk",
    "information commissioners office": "ico.org.uk", "civil aviation authority": "caa.co.uk", "nhs england": "england.nhs.uk",
    "nhs business services authority": "nhsbsa.nhs.uk", "scottish government": "gov.scot", "welsh government": "gov.wales",
    "audit scotland": "audit-scotland.gov.uk", "electoral commission": "electoralcommission.org.uk", "care quality commission": "cqc.org.uk",
    "financial reporting council": "frc.org.uk",
    "barclays": "home.barclays", "hsbc": "hsbc.com", "natwest": "natwestgroup.com", "santander uk": "santander.co.uk",
    "lloyds banking": "lloydsbankinggroup.com", "monzo bank": "monzo.com", "starling bank": "starlingbank.com", "revolut": "revolut.com",
    "zopa bank": "zopa.com", "capital one": "capitalone.co.uk", "clear score technology": "clearscore.com",
    "nationwide building society": "nationwide.co.uk", "goldman sachs": "goldmansachs.com", "morgan stanley": "morganstanley.com",
    "jpmorgan chase": "jpmorganchase.com", "london stock exchange": "lseg.com", "bloomberg": "bloomberg.com", "moody's": "moodys.com",
    "s&p global": "spglobal.com", "fitch ratings": "fitchratings.com", "experian": "experian.co.uk", "dunnhumby": "dunnhumby.com",
    "ipsos": "ipsos.com", "kantar": "kantar.com", "yougov": "yougov.co.uk", "kubrick group": "kubrickgroup.com",
    "faculty science": "faculty.ai", "quantexa": "quantexa.com", "wood mackenzie": "woodmac.com", "msci": "msci.com",
    "factset": "factset.com", "oxford economics": "oxfordeconomics.com", "frontier economics": "frontier-economics.com",
    "deloitte": "deloitte.com", "pricewaterhousecoopers": "pwc.co.uk", "ernst & young": "ey.com", "kpmg llp": "kpmg.com",
    "accenture": "accenture.com", "mckinsey": "mckinsey.com", "boston consulting": "bcg.com", "bain & company": "bain.com",
    "oliver wyman": "oliverwyman.com", "baringa": "baringa.com", "capgemini": "capgemini.com", "grant thornton": "grantthornton.co.uk",
    "bdo llp": "bdo.co.uk", "forvis mazars": "forvismazars.com", "rsm uk": "rsmuk.com", "lane clark": "lcp.com",
    "hymans robertson": "hymans.co.uk", "capital markets company": "capco.com", "slalom": "slalom.com", "a t kearney": "kearney.com",
    "jane street": "janestreet.com", "man group": "man.com", "blackrock investment": "blackrock.com", "schroder investment": "schroders.com",
    "aviva plc": "aviva.com", "hastings insurance": "hastingsdirect.com", "legal & general": "legalandgeneral.com",
}


def known_site(name):
    low = re.sub(r"\(.*?\)", " ", name.lower().replace("’", "'"))
    low = re.sub(r"^the ", "", " ".join(low.split()))
    for k, dom in KNOWN_SITES.items():
        if low.startswith(k):
            return dom
    return None


def trading_name(name):
    m = re.search(r"\b(?:t/as?|trading as)\.?\s+(.+)$", name, re.I)
    return m.group(1).strip() if m else ""


def _words(name):
    s = re.sub(r"\(.*?\)", " ", name.lower().replace("&", " "))
    s = re.sub(r"[^a-z0-9' -]", " ", s).replace("'", "")
    return [w for w in s.split() if w]


def name_tokens(name):
    base = trading_name(name) or name
    return [w for w in _words(base) if len(w) >= 3 and w not in GENERIC][:4]


LEGAL_TAIL = {"limited", "ltd", "llp", "plc", "inc", "lp", "uk", "the", "co", "company"}


def domain_candidates(name, sector=""):
    base = trading_name(name) or re.split(r",", name)[0]
    words = [w for w in _words(base) if w not in LEGAL_TAIL]
    if not words:
        return []
    core = [w for w in words if w not in ("group", "holdings", "holding", "services", "international")] or words
    stems = []
    if sector == "University" or "university" in words:
        rest = [w for w in core if w not in ("university", "of", "the")]
        if rest:
            stems.append(("".join(rest), [".ac.uk"]))
            stems.append((rest[0], [".ac.uk"]))
    if sector in ("Government", "Local government"):
        rest = [w for w in core if w not in ("borough", "city", "county", "district", "council", "metropolitan", "of", "the")]
        if rest:
            stems.append(("".join(rest), [".gov.uk"]))
            if "city" in words:
                stems.append(("".join(rest) + "city", [".gov.uk"]))
    tlds = [".co.uk", ".com", ".uk", ".org.uk", ".org", ".io", ".net"]
    if sector == "Research":
        tlds = [".ac.uk", ".org.uk", ".org"] + tlds
    joined = "".join(w for w in core if w != "and")
    stems += [(joined, tlds), ("-".join(w for w in core if w != "and"), tlds[:3])]
    if "and" in core:
        stems.append(("".join(core), tlds[:3]))
    if len(core) >= 2:
        stems.append(("".join(core[:2]), tlds[:3]))
    if len(core[0]) >= 5 and core[0] not in GENERIC:
        stems.append((core[0], tlds[:3]))
    out = []
    for stem, ts in stems:
        if len(stem) < 3:
            continue
        for t in ts:
            d = stem + t
            if d not in out:
                out.append(d)
    return out


PARKED = re.compile(r"(domain (is|may be) for sale|buy this domain|this domain is parked|parkingcrew|sedoparking|hugedomains|"
                    r"dan\.com|domain has expired|future home of|under construction|website coming soon|account suspended|"
                    r"default web site page|welcome to nginx|it works!)", re.I)


def site_matches(html, name):
    hay = (page_title(html) + " " + page_text(html, 30000)).lower()
    toks = name_tokens(name)
    if toks:
        return any(re.search(r"\b" + re.escape(t) + r"\b", hay) for t in toks)
    joined = "".join(_words(trading_name(name) or name))
    return len(joined) >= 6 and joined in re.sub(r"[^a-z0-9]", "", hay)


def find_site(c, overrides):
    name = c["Organisation"]
    if name in overrides:
        return overrides[name], "From your sites file"
    dom = known_site(name)
    if dom:
        for url in (f"https://www.{dom}/", f"https://{dom}/"):
            r = fetch(url, timeout=12)
            if r is not None and r.ok_html:
                return r.url, "Known domain"
    for d in domain_candidates(name, c.get("Primary sector", ""))[:12]:
        if not (resolves(d) or resolves("www." + d)):
            continue
        for url in (f"https://{d}/", f"https://www.{d}/"):
            r = fetch(url, timeout=10, tries=1)
            if r is None:
                continue          # no answer: try the www form, then the next domain
            if r.ok_html and not PARKED.search(r.text[:30000]) and site_matches(r.text, name):
                return r.url, f"Guessed domain {d}, name found on the page"
            break                 # the host answered but it is not this company
    return None, "No website found by name"


# ---------------------------------------------------------------- one company

def _now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def assess_jobs(jobs, c, source_kind):
    roles, seen = [], set()
    for j in jobs:
        key = (j["title"].lower(), j["url"])
        if not j["title"] or key in seen:
            continue
        seen.add(key)
        if not _wanted(j["title"]):
            continue
        a = R.assess(j["title"], j["text"], j["location"], c.get("Town/City", ""), j.get("valid_through"), TODAY)
        roles.append({"organisation": c["Organisation"], "employer_on_advert": j.get("employer") or "", "sector": c.get("Primary sector", ""),
                      "priority": c.get("Priority", ""), "town_on_register": c.get("Town/City", ""), "title": j["title"],
                      "location": j["location"], "url": j["url"], "posted": j.get("posted", ""), "how": j.get("how", source_kind),
                      "source_kind": source_kind, "checked_at": _now(), "text_start": j["text"][:600],
                      **{k: (v.isoformat() if isinstance(v, dt.date) else v) for k, v in a.items()}})
    return roles


def process(c, overrides, probe=True):
    res = {"organisation": c["Organisation"], "town": c.get("Town/City", ""), "sector": c.get("Primary sector", ""),
           "priority": c.get("Priority", ""), "site": "", "site_note": "", "careers_pages": [], "ats": [], "jobs_seen": 0,
           "kept": 0, "emails": [], "email_page": "", "note": "", "checked_at": _now()}
    pages, jobs = {}, []
    set_budget(90)
    site, res["site_note"] = find_site(c, overrides)
    if site:
        res["site"] = site
        home = fetch(site)
        if home is not None and home.status == -1:
            res["note"] = "robots.txt asks crawlers not to read this site"
        elif home is not None and home.ok_html:
            pages[home.url] = home.text
            links = careers_links(home.text, home.url)
            if not links:
                for p in COMMON_PATHS[:6]:
                    r = fetch(urljoin(home.url, p))
                    if r is not None and r.ok_html and same_site(r.url, home.url) and re.search(r"career|job|vacanc|join", r.url + page_title(r.text), re.I):
                        links.append(r.url)
                        pages[r.url] = r.text
                        break
            for u in links[:3]:
                if u not in pages:
                    r = fetch(u)
                    if r is not None and r.ok_html:
                        pages[r.url] = r.text
                        for u2 in careers_links(r.text, r.url)[:2]:      # "current vacancies" one level down
                            if u2 not in pages and len(pages) < 7:
                                r2 = fetch(u2)
                                if r2 is not None and r2.ok_html:
                                    pages[r2.url] = r2.text
            res["careers_pages"] = [u for u in pages if u != home.url]
    ats = set()
    for u, html in pages.items():
        ats |= detect_ats(html)
        if u != res["site"]:
            jobs += jsonld_jobs(html, u)
            jobs += follow_job_links(html, u, res["site"] or u)
            jobs += inline_jobs(html, u)
            if NO_VACANCIES.search(page_text(html, 15000)):
                res["note"] = (res["note"] + "; " if res["note"] else "") + "Careers page says there are no current vacancies"
    if not ats and probe:
        names = {w.lower() for w in name_tokens(c["Organisation"])}
        joined = "".join(w for w in _words(trading_name(c["Organisation"]) or c["Organisation"]) if w not in LEGAL_TAIL)
        slugs = [s for s in dict.fromkeys([joined, "-".join(w for w in _words(trading_name(c["Organisation"]) or c["Organisation"])
                                                            if w not in LEGAL_TAIL)]) if len(s) >= 4]
        for kind in PROBE:
            for slug in slugs:
                found, board_name = READERS[kind](slug, res["site"])
                if not found:
                    continue
                blob = (board_name + " " + " ".join(j["text"][:3000] for j in found[:5])).lower()
                if names and not any(n in blob for n in names):
                    continue   # a board with this slug belongs to someone else
                ats.add((kind, slug))
                jobs += found
                break
    for kind, slug in sorted(ats):
        if any(j["how"].startswith(kind.capitalize()) and f"({slug})" in j["how"] for j in jobs):
            continue
        try:
            found, _ = READERS[kind](slug, res["site"])
        except Exception as e:   # a reader must never stop the run
            res["note"] = (res["note"] + "; " if res["note"] else "") + f"{kind} reader failed: {type(e).__name__}"
            found = []
        jobs += found
    res["ats"] = [f"{k}:{s}" for k, s in sorted(ats)]
    # a title written on the careers page and also linked to its own advert: keep the advert
    titled = {j["title"].lower() for j in jobs if not j["how"].startswith("Listed on the careers page")}
    jobs = [j for j in jobs if not (j["how"].startswith("Listed on the careers page") and j["title"].lower() in titled)]
    res["jobs_seen"] = len(jobs)
    roles = assess_jobs(jobs, c, "Employer careers page")
    res["kept"] = sum(1 for r in roles if not r["exclude"])
    # role-based public addresses from the company's own pages
    if res["site"]:
        found = []
        for u, html in pages.items():
            mail = " ".join(a["href"][7:] for a in soup_of(html).find_all("a", href=True) if a["href"].lower().startswith("mailto:"))
            got = R.role_emails(page_text(html, 60000) + " " + mail, urlparse(res["site"]).netloc)
            if got:
                found += [(e, u) for e in got]
        if not found:
            for p in ("contact", "contact-us", "about-us"):
                r = fetch(urljoin(res["site"], p))
                if r is not None and r.ok_html and same_site(r.url, res["site"]):
                    mail = " ".join(a["href"][7:] for a in soup_of(r.text).find_all("a", href=True) if a["href"].lower().startswith("mailto:"))
                    got = R.role_emails(page_text(r.text, 60000) + " " + mail, urlparse(res["site"]).netloc)
                    if got:
                        found += [(e, r.url) for e in got]
                        break
        uniq = list(dict.fromkeys(e for e, _ in found))
        rank = {e: i for i, e in enumerate(R.role_emails(" ".join(uniq), urlparse(res["site"]).netloc))}
        uniq.sort(key=lambda e: rank.get(e, 99))
        res["emails"] = uniq[:3]
        res["email_page"] = next((u for e, u in found if uniq and e == uniq[0]), "")
    set_budget(None)
    return res, roles


# ---------------------------------------------------------------- job boards that list many employers

def _norm_employer(s):
    s = (s or "").lower().replace("&", " and ").replace("’", "'")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9' ]", " ", s).replace("'", "")
    s = re.sub(r"\b(limited|ltd|llp|plc|inc|lp|the|uk|group|holdings?|company|co|hr)\b", " ", s)
    return " ".join(s.split())


class Matcher:
    def __init__(self, companies):
        self.exact, self.by_token = {}, {}
        for c in companies:
            for nm in filter(None, [c["Organisation"], trading_name(c["Organisation"])]):
                k = _norm_employer(nm)
                if k:
                    self.exact.setdefault(k, c)
                    for t in k.split():
                        if len(t) >= 5 and t not in GENERIC:
                            self.by_token.setdefault(t, []).append((k, c))

    def match(self, employer):
        k = _norm_employer(employer)
        if not k:
            return None, ""
        if k in self.exact:
            return self.exact[k], "Exact name"
        kt = set(k.split())
        best = None
        for t in kt:
            for k2, c in self.by_token.get(t, []):
                t2 = set(k2.split())
                if len(t2) >= 2 and (t2 <= kt or kt <= t2) and len(kt & t2) >= 2:
                    best = best or (c, "Close name")
        return best if best else (None, "")


JOBSACUK_WORDS = ["data analyst", "data scientist", "statistician", "junior data", "graduate data", "research data analyst",
                  "machine learning", "data officer", "research assistant data", "insight analyst", "business intelligence analyst"]


def source_jobsacuk(matcher, log):
    rows = []
    seen = set()
    for kw in JOBSACUK_WORDS:
        for start in (1, 101):
            r = fetch("https://www.jobs.ac.uk/search/", params={"keywords": kw, "pageSize": 100, "startIndex": start, "sortOrder": 1})
            if r is None or not r.ok_html:
                break
            s = soup_of(r.text)
            links = [a for a in s.find_all("a", href=True) if re.match(r"^(https://www\.jobs\.ac\.uk)?/job/[A-Z0-9]+/", a["href"])]
            for a in links:
                u = urljoin("https://www.jobs.ac.uk/", a["href"]).split("?")[0]
                title = " ".join(a.get_text(" ", strip=True).split())
                if u in seen or not _wanted(title):
                    continue
                seen.add(u)
                d = fetch(u)
                if d is None or not d.ok_html:
                    continue
                text = page_text(d.text, 40000)
                jl = jsonld_jobs(d.text, u)
                employer = (jl[0]["employer"] if jl else "") or _label_after(text, ["Employer:", "Organisation:"]) or ""
                loc = (jl[0]["location"] if jl else "") or _label_after(text, ["Location:"])
                rows.append(("jobs.ac.uk", title, employer, loc, u, text, jl[0]["valid_through"] if jl else ""))
            if len(links) < 50:
                break
        log("jobs.ac.uk", kw, "running total", len(rows))
    return _board_roles(rows, matcher)


def source_analysis(matcher, log):
    rows, seen = [], set()
    for page in range(1, 8):
        url = "https://analysisfunction.civilservice.gov.uk/vacancies/" + (f"page/{page}/" if page > 1 else "")
        r = fetch(url)
        if r is None or not r.ok_html:
            break
        links = {urljoin(url, a["href"]).split("#")[0]: " ".join(a.get_text(" ", strip=True).split())
                 for a in soup_of(r.text).find_all("a", href=True)
                 if re.search(r"/vacancies/[a-z0-9-]+/?$", a["href"]) and "/page/" not in a["href"]}
        new = [(u, t) for u, t in links.items() if u not in seen]
        for u, title in new:
            seen.add(u)
            if not _wanted(title):
                continue
            d = fetch(u)
            if d is None or not d.ok_html:
                continue
            text = page_text(d.text, 30000)
            employer = _label_after(text, ["Department:", "Organisation:", "Department"]) or ""
            rows.append(("Civil Service Analysis Function", title, employer, _label_after(text, ["Location:", "Location"]), u, text, ""))
        if not new:
            break
    log("Analysis Function vacancies", len(rows))
    return _board_roles(rows, matcher)


FINDAJOB_WORDS = ["junior data analyst", "graduate data analyst", "data analyst", "junior data scientist", "data scientist",
                  "statistician", "graduate consultant", "associate consultant", "associate data"]


def source_findajob(matcher, log):
    rows, seen = [], set()
    for kw in FINDAJOB_WORDS:
        for p in range(1, 6):
            r = fetch("https://findajob.dwp.gov.uk/search", params={"q": kw, "pp": 50, "p": p})
            if r is None or not r.ok_html:
                break
            links = [a for a in soup_of(r.text).find_all("a", href=True) if "/details/" in a["href"]]
            for a in links:
                u = urljoin("https://findajob.dwp.gov.uk/", a["href"]).split("?")[0]
                title = " ".join(a.get_text(" ", strip=True).split())
                if u in seen or not _wanted(title):
                    continue
                seen.add(u)
                d = fetch(u)
                if d is None or not d.ok_html:
                    continue
                text = page_text(d.text, 30000)
                jl = jsonld_jobs(d.text, u)
                employer = (jl[0]["employer"] if jl else "") or _label_after(text, ["Company:", "Company", "Employer"])
                loc = (jl[0]["location"] if jl else "") or _label_after(text, ["Location:", "Location"])
                rows.append(("DWP Find a job", title, employer, loc, u, text, jl[0]["valid_through"] if jl else ""))
            if len(links) < 20:
                break
        log("Find a job", kw, "running total", len(rows))
    return _board_roles(rows, matcher)


def _label_after(text, labels):
    for lab in labels:
        m = re.search(re.escape(lab) + r"\s*:?\s*([A-Z][^|•\n]{2,80}?)(?=\s{2,}|\s(?:[A-Z][a-z]+:)|$)", text)
        if m:
            return m.group(1).strip(" -:")
    return ""


def _board_roles(rows, matcher):
    roles = []
    for board, title, employer, loc, url, text, vt in rows:
        c, quality = matcher.match(employer)
        base = c or {"Organisation": "", "Town/City": "", "Primary sector": "", "Priority": ""}
        for r in assess_jobs([_job(title, loc, url, text, valid_through=vt, employer=employer, how=board)], base, board):
            r["register_match"] = quality or "Not matched to the shortlist"
            roles.append(r)
    return roles


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shortlist")
    ap.add_argument("data_dir")
    ap.add_argument("--tiers", default="A,B,C")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--sites", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--sources", default="careers,jobsacuk,analysis,findajob")
    ap.add_argument("--no-probe", action="store_true", help="do not look for hiring boards by company name")
    a = ap.parse_args()

    import csv
    out = Path(a.data_dir)
    out.mkdir(parents=True, exist_ok=True)
    logf = open(out / "crawl.log", "a", encoding="utf8")
    lock = threading.Lock()

    def log(*x):
        msg = dt.datetime.now().strftime("%H:%M:%S ") + " ".join(str(v) for v in x)
        print(msg, flush=True)
        with lock:
            logf.write(msg + "\n")
            logf.flush()

    with open(a.shortlist, newline="", encoding="utf8") as f:
        companies = list(csv.DictReader(f))
    overrides = {}
    if a.sites:
        with open(a.sites, newline="", encoding="utf8") as f:
            overrides = {r["Organisation"]: r["Website"] for r in csv.DictReader(f) if r.get("Website")}
    tiers = set(a.tiers.split(","))
    todo = [c for c in companies if c.get("Priority", "A") in tiers and (not a.only or a.only.lower() in c["Organisation"].lower())]
    sources = set(a.sources.split(","))

    comp_path, role_path = out / "companies.jsonl", out / "roles.jsonl"
    done = set()
    if comp_path.exists():
        for line in comp_path.read_text(encoding="utf8").splitlines():
            try:
                d = json.loads(line)
                done.add((d["organisation"], d["town"]))
            except (ValueError, KeyError):
                pass
    todo = [c for c in todo if (c["Organisation"], c.get("Town/City", "")) not in done]
    if a.limit:
        todo = todo[:a.limit]
    log(f"companies to check: {len(todo)} (already done: {len(done)})")

    def write(res, roles):
        with lock:
            with open(comp_path, "a", encoding="utf8") as f:
                f.write(json.dumps(res, ensure_ascii=False) + "\n")
            if roles:
                with open(role_path, "a", encoding="utf8") as f:
                    for r in roles:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")

    if "careers" in sources and todo:
        counter = {"n": 0, "kept": 0}

        def one(c):
            try:
                res, roles = process(c, overrides, probe=not a.no_probe and c.get("Priority") in ("A", "B"))
            except Exception as e:   # one bad site must not stop the run
                res = {"organisation": c["Organisation"], "town": c.get("Town/City", ""), "sector": c.get("Primary sector", ""),
                       "priority": c.get("Priority", ""), "site": "", "site_note": "", "careers_pages": [], "ats": [],
                       "jobs_seen": 0, "kept": 0, "emails": [], "email_page": "", "note": f"Error: {type(e).__name__}: {e}"[:200],
                       "checked_at": _now()}
                roles = []
            write(res, roles)
            with lock:
                counter["n"] += 1
                counter["kept"] += res["kept"]
                if counter["n"] % 25 == 0:
                    log(f"checked {counter['n']}/{len(todo)} companies, roles kept so far {counter['kept']}")

        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            list(ex.map(one, todo))
        log("careers pages done")

    matcher = Matcher(companies)
    for name, fn in (("jobsacuk", source_jobsacuk), ("analysis", source_analysis), ("findajob", source_findajob)):
        if name in sources and not (out / f"done_{name}").exists():
            try:
                roles = fn(matcher, log)
            except Exception as e:
                log(name, "failed:", type(e).__name__, e)
                continue
            with lock, open(role_path, "a", encoding="utf8") as f:
                for r in roles:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            (out / f"done_{name}").write_text(_now())
            log(name, "roles recorded:", len(roles), "kept:", sum(1 for r in roles if not r["exclude"]))
    log("finished")


if __name__ == "__main__":
    main()
