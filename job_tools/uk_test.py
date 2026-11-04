#!/usr/bin/env python3
"""Offline checks for uk_rules.py and the parsers in uk_crawl.py. Run: python3 -I job_tools/uk_test.py"""
import sys, json, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import uk_rules as R

TODAY = dt.date(2026, 11, 4)
fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else f"\n     got  {got!r}\n     want {want!r}"))


# titles
for title, fam in [
    ("Junior Data Analyst", "Junior data analyst"),
    ("Graduate Data Scientist 2027", "Junior data scientist"),
    ("Associate Data Scientist – Pricing", "Associate data scientist"),
    ("Associate Data Analyst (Hybrid)", "Associate data analyst"),
    ("Assistant Statistician", "Junior statistician"),
    ("Statistical Officer", "Junior statistician"),
    ("Graduate Consultant - Data & Analytics", "Entry-level consultant"),
    ("Associate Consultant", "Entry-level consultant"),
    ("Analyst Consultant, Economics", "Entry-level consultant"),
    ("2027 Graduate Programme – Technology", "Graduate programme"),
    ("Data Analyst", "Analyst (level from advert)"),
    ("Insight Analyst", "Analyst (level from advert)"),
    ("Data Scientist", "Data scientist (level from advert)"),
    ("Graduate Trainee - Data Science 2027", "Junior data scientist"),
]:
    check(f"family: {title}", R.classify_title(title)[0], fam)
for title, why in [
    ("Senior Data Analyst", "Senior or lead title"),
    ("Lead Data Scientist", "Senior or lead title"),
    ("Data Analyst Intern", "Internship or placement"),
    ("Data Analyst Apprenticeship (Level 4)", "Apprenticeship or school leaver"),
    ("Trainee Data Analyst", "Trainee title"),
    ("Postdoctoral Research Associate in Statistics", "PhD or academic post"),
    ("Graduate Civil Engineer", "Unrelated graduate role"),
    ("Financial Analyst", "Title is not one of the wanted roles"),
    ("Office Manager", "Senior or lead title"),
]:
    check(f"excluded: {title}", R.classify_title(title)[1], why)

# level
check("years: 3+ excluded", R.assess_level("Analyst (level from advert)", "", "You will have 3+ years of experience in SQL")[1],
      "Asks for 3+ years of experience")
check("years: 1-2 kept", R.assess_level("Analyst (level from advert)", "", "Ideally 1-2 years' experience in analytics"),
      ("Asks 1-2 years", None))
check("years: none stated", R.assess_level("Analyst (level from advert)", "", "Strong SQL and Python."), ("Level not stated", None))
check("entry text", R.assess_level("Analyst (level from advert)", "", "Recent graduates welcome to apply."),
      ("Entry level stated in advert", None))
check("company age is not asked experience", R.experience_asked("With over 25 years of experience in the market, we"), None)

# location
check("uk city", R.uk_place("London, England, United Kingdom"), (True, "London"))
check("uk token", R.uk_place("Remote, UK"), (True, "UK (city not stated)"))
check("cambridge MA", R.uk_place("Cambridge, MA")[0], False)
check("dublin", R.uk_place("Dublin, Ireland")[0], False)
check("belfast", R.uk_place("Belfast, Northern Ireland"), (True, "Belfast"))
check("no location", R.uk_place("", "Leeds"), (None, "Leeds (register address)"))

# dates and status
check("closing long date", R.closing_date("Closing date: 23:55 on Sunday 16th November 2026"), dt.date(2026, 11, 16))
check("closing numeric", R.closing_date("Deadline 01/12/2026. Apply now"), dt.date(2026, 12, 1))
check("closing US order", R.closing_date("Applications close on November 30, 2026."), dt.date(2026, 11, 30))
check("open future", R.open_status("Closing date for receipt of applications: 11 November 2026", today=TODAY)[0:2],
      ("Open", dt.date(2026, 11, 11)))
check("closed past", R.open_status("Closes: 25 October 2026", today=TODAY)[0], "Closed")
check("closed marker", R.open_status("Sorry, this job is no longer available.", today=TODAY)[0], "Closed")
check("validThrough past", R.open_status("Great role", valid_through="2026-10-01T00:00:00Z", today=TODAY)[0], "Closed")
check("rolling", R.open_status("We review applications on a rolling basis.", today=TODAY)[2], "Rolling or ongoing deadline")

# visa and pay
check("no sponsorship", R.visa_note("We are unable to offer visa sponsorship for this role."), "Says no sponsorship")
check("clearance", R.visa_note("You must be eligible for SC clearance."), "Security clearance or UK residence years needed")
check("salary", R.salary_of("Salary: £32,000 - £36,000 per annum plus benefits"), "£32,000 - £36,000 per annum")

# emails
page = "Contact careers@acme.co.uk or john.smith@acme.co.uk, info [at] acme [dot] co [dot] uk, noreply@acme.co.uk, jobs@other.com"
check("role emails", R.role_emails(page, "www.acme.co.uk"), ["careers@acme.co.uk", "info@acme.co.uk"])
check("prefixed role email", R.role_emails("graduate.recruitment@uni.ac.uk hr-services@uni.ac.uk", "www.uni.ac.uk"),
      ["graduate.recruitment@uni.ac.uk", "hr-services@uni.ac.uk"])
check("registrable", R.registrable("careers.hsbc.co.uk"), "hsbc.co.uk")

# whole advert
a = R.assess("Junior Data Analyst", "<p>Closing date: 30 November 2026. Hybrid, 2 days a week in the office. £30,000.</p>",
             "Manchester, UK", today=TODAY)
check("assess kept", (a["exclude"], a["family"], a["city"], a["status"], a["work_mode"], a["salary"]),
      (None, "Junior data analyst", "Manchester", "Open", "Hybrid", "£30,000"))

# crawler parsers (no network)
try:
    import uk_crawl as C
except Exception as e:  # uk_crawl needs requests and bs4
    print("skip crawler parser checks:", e)
else:
    html = """<html><head><title>Acme Analytics | Home</title>
    <script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting","title":"Graduate Data Analyst",
    "datePosted":"2026-10-28","validThrough":"2026-11-30","hiringOrganization":{"@type":"Organization","name":"Acme Analytics"},
    "jobLocation":{"@type":"Place","address":{"addressLocality":"Leeds","addressCountry":"GB"}},"description":"<p>Hybrid role</p>"}</script>
    </head><body><a href="/careers">Careers</a> <a href="https://boards.greenhouse.io/acmeanalytics">Jobs</a>
    <a href="https://acme.wd3.myworkdayjobs.com/en-GB/External">Search jobs</a></body></html>"""
    check("jsonld", [j["title"] for j in C.jsonld_jobs(html, "https://acme.co.uk/careers")], ["Graduate Data Analyst"])
    check("careers links", C.careers_links(html, "https://acme.co.uk/")[:1], ["https://acme.co.uk/careers"])
    check("ats detect", sorted(C.detect_ats(html)), [("greenhouse", "acmeanalytics"), ("workday", "acme|wd3|External")])
    check("domain candidates", C.domain_candidates("Lane Clark & Peacock LLP", "Consulting")[:3],
          ["laneclarkpeacock.co.uk", "laneclarkpeacock.com", "laneclarkpeacock.uk"])
    check("domain candidates t/a", C.domain_candidates("BrightGen Limited, T/A Credera", "Consulting")[0], "credera.co.uk")
    check("domain candidates university", C.domain_candidates("University of Leeds", "University")[0], "leeds.ac.uk")
    check("name tokens", C.name_tokens("The Boston Consulting Group UK LLP"), ["boston"])

print("\n" + ("all checks passed" if not fails else f"{fails} check(s) failed"))
sys.exit(1 if fails else 0)
