#!/usr/bin/env python3
"""End-to-end run of uk_crawl.py, uk_verify.py and uk_build.py against a local test server (no internet needed).

Run: python3 -I job_tools/uk_test_e2e.py
"""
import sys, os, json, csv, threading, subprocess, tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
JL = lambda d: '<script type="application/ld+json">' + json.dumps(d) + "</script>"

PAGES = {
    # Acme: careers link, schema.org advert, a followed advert, a Greenhouse board, robots.txt
    "www.acme.co.uk/robots.txt": ("text/plain", "User-agent: *\nDisallow: /private\n"),
    "www.acme.co.uk/": ("text/html", "<html><head><title>Acme Analytics</title></head><body><a href='/careers'>Careers</a>"
                        "<a href='/contact'>Contact</a></body></html>"),
    "www.acme.co.uk/careers": ("text/html", "<html><head><title>Careers | Acme Analytics</title>" + JL({
        "@context": "https://schema.org", "@type": "JobPosting", "title": "Graduate Data Analyst", "datePosted": "2026-10-28",
        "validThrough": "2099-12-31", "hiringOrganization": {"@type": "Organization", "name": "Acme Analytics"},
        "jobLocation": {"@type": "Place", "address": {"addressLocality": "Leeds", "addressCountry": "GB"}},
        "description": "<p>Join our graduate intake. Hybrid working.</p>"}) +
        "</head><body><h1>Join us</h1><a href='/careers/junior-data-scientist'>Junior Data Scientist</a>"
        "<a href='/careers/senior-data-engineer'>Senior Data Engineer</a>"
        "<iframe src='https://boards.greenhouse.io/embed/job_board?for=acmeanalytics'></iframe>"
        "<p>Questions? careers@acme.co.uk</p></body></html>"),
    "www.acme.co.uk/careers/junior-data-scientist": ("text/html", "<html><body><h1>Junior Data Scientist</h1><p>London, UK. Hybrid, "
                                                     "2 days a week in the office.</p><p>Closing date: 30 November 2099</p>"
                                                     "<p>Salary £34,000 per annum.</p></body></html>"),
    "boards-api.greenhouse.io/v1/boards/acmeanalytics/jobs": ("application/json", json.dumps({"jobs": [
        {"id": 1, "title": "Associate Data Scientist", "location": {"name": "London, United Kingdom"},
         "absolute_url": "https://boards.greenhouse.io/acmeanalytics/jobs/1001",
         "content": "&lt;p&gt;Acme Analytics is hiring. We are unable to offer visa sponsorship.&lt;/p&gt;", "first_published": "2026-10-30"},
        {"id": 2, "title": "Data Analyst", "location": {"name": "Manchester, UK"}, "absolute_url": "https://boards.greenhouse.io/acmeanalytics/jobs/1002",
         "content": "You bring 3+ years of experience in SQL.", "first_published": "2026-10-20"},
        {"id": 3, "title": "Junior Data Analyst", "location": {"name": "Dublin, Ireland"}, "absolute_url": "https://boards.greenhouse.io/acmeanalytics/jobs/1003",
         "content": "Dublin office.", "first_published": "2026-10-21"}]})),
    "boards-api.greenhouse.io/v1/boards/acmeanalytics": ("application/json", json.dumps({"name": "Acme Analytics"})),
    "boards.greenhouse.io/acmeanalytics/jobs/1001": ("text/html", "<html><body><h1>Associate Data Scientist</h1><p>Apply now</p></body></html>"),
    # Beta: found by guessed domain, careers page says no vacancies, email on the contact page
    "betainsight.co.uk/": ("text/html", "<html><head><title>Beta Insight Partners | Home</title></head><body>Strategy advice</body></html>"),
    "betainsight.co.uk/careers": ("text/html", "<html><head><title>Careers</title></head><body>There are currently no vacancies.</body></html>"),
    "betainsight.co.uk/contact": ("text/html", "<html><body>Email recruitment@betainsight.co.uk or jane.doe@betainsight.co.uk</body></html>"),
    # Gamma: roles written on the careers page itself, one already closed
    "www.gammacap.com/": ("text/html", "<html><head><title>Gamma Capital</title></head><body><a href='/join-us'>Join us</a></body></html>"),
    "www.gammacap.com/join-us": ("text/html", "<html><body><h2>Junior Data Analyst</h2><p>Closing date: 1 October 2026</p>"
                                 "<h2>Graduate Consultant</h2><p>London. Apply by 15 December 2099.</p><p>hr@gammacap.com</p></body></html>"),
    # University: own site has no wanted roles; jobs.ac.uk lists one
    "testshire.ac.uk/": ("text/html", "<html><head><title>University of Testshire</title></head><body><a href='/jobs'>Jobs</a></body></html>"),
    "testshire.ac.uk/jobs": ("text/html", "<html><body><a href='/jobs/1'>Senior Lecturer in History</a></body></html>"),
    "www.jobs.ac.uk/search/": ("text/html", "<html><body><a href='/job/ABC123/data-analyst'>Data Analyst</a></body></html>"),
    "www.jobs.ac.uk/job/ABC123/data-analyst": ("text/html", "<html><head>" + JL({
        "@context": "https://schema.org", "@type": "JobPosting", "title": "Data Analyst", "hiringOrganization": {"name": "University of Testshire"},
        "jobLocation": {"address": {"addressLocality": "Testshire", "addressCountry": "United Kingdom"}},
        "validThrough": "2099-11-20", "description": "Recent graduates welcome. Salary £31,000."}) +
        "</head><body>Data Analyst. Closes: 20th November 2099</body></html>"),
    "analysisfunction.civilservice.gov.uk/vacancies/": ("text/html", "<html><body><a href='/vacancies/assistant-statistician-ons/'>"
                                                        "Assistant Statistician (HEO)</a></body></html>"),
    "analysisfunction.civilservice.gov.uk/vacancies/assistant-statistician-ons/": ("text/html", "<html><body><h1>Assistant Statistician</h1>"
        "<p>Department: Office for National Statistics</p><p>Location: Newport, Wales</p><p>Closing date: 30 November 2099</p></body></html>"),
    "findajob.dwp.gov.uk/search": ("text/html", "<html><body><a href='/details/111'>Junior Data Analyst</a></body></html>"),
    "findajob.dwp.gov.uk/details/111": ("text/html", "<html><head>" + JL({
        "@context": "https://schema.org", "@type": "JobPosting", "title": "Junior Data Analyst", "hiringOrganization": {"name": "Acme Analytics Limited"},
        "jobLocation": {"address": {"addressLocality": "Bristol", "addressCountry": "GB"}}, "validThrough": "2099-12-01",
        "description": "Entry level role."}) + "</head><body>Junior Data Analyst</body></html>"),
}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _serve(self):
        p = urlparse(self.path).path
        key = p[len("/ext/"):] if p.startswith("/ext/") else p.lstrip("/")
        hit = PAGES.get(key) or PAGES.get(key.rstrip("/")) or PAGES.get(key + "/")
        if not hit:
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body>Not here</body></html>")
            return
        ctype, body = hit
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf8"))

    do_GET = _serve
    do_POST = _serve


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    tmp = Path(tempfile.mkdtemp(prefix="uk_e2e_"))
    shortlist, sites = tmp / "shortlist.csv", tmp / "sites.csv"
    with open(shortlist, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Organisation", "Town/City", "County", "Licence rating", "Primary sector", "All sectors", "Priority", "Known employer"])
        w.writerow(["Acme Analytics Limited", "Leeds", "", "Worker (A rating)", "Data", "Data", "A", ""])
        w.writerow(["Beta Insight Partners LLP", "London", "", "Worker (A rating)", "Consulting", "Consulting", "B", ""])
        w.writerow(["Gamma Capital Management LLP", "London", "", "Worker (A rating)", "Investment", "Investment", "A", ""])
        w.writerow(["University of Testshire", "Testshire", "", "Worker (A rating)", "University", "University", "A", ""])
    with open(sites, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Organisation", "Website"])
        w.writerow(["Acme Analytics Limited", "https://www.acme.co.uk/"])
        w.writerow(["Gamma Capital Management LLP", "https://www.gammacap.com/"])
    env = dict(os.environ, UK_CRAWL_TEST_BASE=base)
    data = tmp / "data"
    run = lambda *args: subprocess.run([sys.executable, "-I", *args], env=env, check=True, capture_output=True, text=True)
    run(str(HERE / "uk_crawl.py"), str(shortlist), str(data), "--sites", str(sites), "--workers", "4")
    run(str(HERE / "uk_verify.py"), str(data))
    out = run(str(HERE / "uk_build.py"), str(data), str(tmp), "--label", "test").stdout
    srv.shutdown()

    roles = [json.loads(l) for l in (data / "roles_checked.jsonl").read_text().splitlines()]
    comps = {c["organisation"]: c for c in map(json.loads, (data / "companies.jsonl").read_text().splitlines())}
    kept = sorted((r.get("organisation") or r.get("employer_on_advert"), r["title"]) for r in roles
                  if not r.get("exclude") and not r.get("duplicate_of"))
    why = {r["title"] + " @ " + (r.get("organisation") or r.get("employer_on_advert")): r.get("exclude") for r in roles if r.get("exclude")}
    fails = []

    def expect(label, cond):
        print(("ok   " if cond else "FAIL ") + label)
        if not cond:
            fails.append(label)

    expect("kept roles", kept == sorted([
        ("Acme Analytics Limited", "Associate Data Scientist"), ("Acme Analytics Limited", "Graduate Data Analyst"),
        ("Acme Analytics Limited", "Junior Data Analyst"), ("Acme Analytics Limited", "Junior Data Scientist"),
        ("Gamma Capital Management LLP", "Graduate Consultant"), ("University of Testshire", "Data Analyst"),
        ("Office for National Statistics", "Assistant Statistician (HEO)")]))
    expect("3+ years left out", why.get("Data Analyst @ Acme Analytics Limited") == "Asks for 3+ years of experience")
    expect("Dublin left out", why.get("Junior Data Analyst @ Acme Analytics Limited") == "Not in the UK")
    expect("closed inline role left out", why.get("Junior Data Analyst @ Gamma Capital Management LLP") == "Closing date has passed")
    ads = {r["title"]: r for r in roles if r.get("organisation") == "Acme Analytics Limited" and not r.get("exclude")}
    expect("no-sponsorship note", ads["Associate Data Scientist"]["visa_note"] == "Says no sponsorship")
    expect("followed advert read", ads["Junior Data Scientist"]["closing"] == "2099-11-30" and ads["Junior Data Scientist"]["work_mode"] == "Hybrid")
    expect("second check ran", all(r.get("second_check") for r in roles if not r.get("exclude") and not r.get("duplicate_of")))
    expect("beta site guessed", comps["Beta Insight Partners LLP"]["site"].startswith("https://betainsight.co.uk"))
    expect("beta no-vacancies note", "no current vacancies" in comps["Beta Insight Partners LLP"]["note"])
    expect("beta email, personal address left out", comps["Beta Insight Partners LLP"]["emails"] == ["recruitment@betainsight.co.uk"])
    expect("acme ats found", "greenhouse:acmeanalytics" in comps["Acme Analytics Limited"]["ats"])
    expect("university site guessed", comps["University of Testshire"]["site"].startswith("https://testshire.ac.uk"))
    expect("workbooks written", (tmp / "UK_Data_Jobs.xlsx").exists() and (tmp / "UK_Speculative_Contacts.xlsx").exists())
    print(out.strip())
    print("\n" + ("all checks passed" if not fails else f"{len(fails)} check(s) failed") + f"  (files in {tmp})")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
