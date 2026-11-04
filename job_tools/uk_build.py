#!/usr/bin/env python3
"""Write UK_Data_Jobs.xlsx and UK_Speculative_Contacts.xlsx from the crawl results.

Usage: python3 -I job_tools/uk_build.py <data_dir> <out_dir> [--seed web_roles.json] [--label "4 November 2026"]
Reads <data_dir>/roles_checked.jsonl (or roles.jsonl when uk_verify.py has not been run) and <data_dir>/companies.jsonl.
--seed adds roles found by web search (a JSON list in the same shape as roles.jsonl rows).
Run the xlsx skill's recalc.py on both files afterwards so the count formulas carry values.
"""
import sys, json, argparse, datetime as dt
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

FONT = "Arial"
F_BODY = Font(name=FONT, size=10)
F_BOLD = Font(name=FONT, size=10, bold=True)
F_HEAD = Font(name=FONT, size=10, bold=True, color="FFFFFF")
F_TITLE = Font(name=FONT, size=14, bold=True)
F_SUB = Font(name=FONT, size=11, bold=True)
F_NOTE = Font(name=FONT, size=9, italic=True, color="555555")
F_LINK = Font(name=FONT, size=10, color="0563C1", underline="single")
FILL_HEAD = PatternFill("solid", fgColor="1F3A5F")
FILL_INPUT = PatternFill("solid", fgColor="FFF2CC")
FILL_BAND = PatternFill("solid", fgColor="F3F6FA")
BORDER = Border(bottom=Side(style="thin", color="D0D5DD"))
WRAP = Alignment(wrap_text=True, vertical="top")
TOP = Alignment(vertical="top")
MAXROW = 3000

STATUSES = ["To apply", "Applied", "Assessment", "Interview", "Offer", "Rejected", "Not for me"]
SENT = ["Not sent", "Sent", "Replied", "No reply after 2 weeks", "Bounced", "Not for me"]

JOB_COLS = [("No.", 6), ("Employer (sponsor register name)", 30), ("Job title", 40), ("Role family", 22), ("Level", 24),
            ("City", 14), ("Location as advertised", 26), ("Work mode", 11), ("Salary as advertised", 24), ("Closing date", 12),
            ("Deadline note", 24), ("Visa or clearance note", 34), ("Other flags", 30), ("Sector", 14), ("Priority", 8),
            ("How found", 30), ("Check 1", 16), ("Check 2", 16), ("Check 2 result", 26), ("Link", 50),
            ("Status", 13), ("Date applied", 13), ("Your notes", 36)]
INPUT_FROM = 21   # Status, Date applied, Your notes

GRAD_VISA = [
    ("Graduate visa length", "2 years for a master's degree if you apply before 1 January 2027; 18 months for applications from that date",
     "Statement of Changes HC 1333, 14 October 2025 (reported by thepienews.com and university visa pages)"),
    ("Starting a permanent full-time job before the Graduate visa is granted",
     "Allowed once your course is complete (official results issued) and your Graduate visa application is in, if your Student visa was granted on or after 6 April 2022",
     "University guidance pages (for example Leeds, Bristol, Sheffield); check with Nottingham's international student team"),
    ("Skilled Worker visa later",
     "Since 22 July 2025 new applications need a degree-level (RQF 6) occupation and at least £41,700, or the new-entrant rate (70%, often £33,400) for people switching from a Graduate visa",
     "Statement of Changes HC 997 (July 2025); going-rate tables on tarve.co.uk"),
    ("Which titles can be sponsored later",
     "Statistician and data scientist roles usually use degree-level codes such as SOC 2433. Data analyst roles often use SOC 3544, which is below degree level "
     "but is on the Temporary Shortage List published on 22 July 2025 (going rate £34,900, new-entrant rate £28,600), so it can still be sponsored for now. "
     "That list is temporary, so check the code and pay with the employer",
     "gov.uk Skilled Worker visa: temporary shortage list (22 July 2025); tarve.co.uk for SOC 2433 rates"),
    ("Civil Service posts", "Commonwealth citizens (India included) can apply for most posts. Many analyst posts need security clearance, which asks for years of UK residence",
     "Civil Service Nationality Rules; individual adverts"),
]


def ddate(s):
    try:
        return dt.date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def dtime(s):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M") if s else None
    except (ValueError, TypeError):
        return None


def header(ws, cols, row=1):
    for c, (name, width) in enumerate(cols, start=1):
        cell = ws.cell(row=row, column=c, value=name)
        cell.font, cell.fill, cell.alignment = F_HEAD, FILL_HEAD, WRAP
        ws.column_dimensions[get_column_letter(c)].width = width
    ws.row_dimensions[row].height = 30
    ws.freeze_panes = ws.cell(row=row + 1, column=3)


def put(ws, r, c, v, link=False, fmt=None, wrap=False):
    cell = ws.cell(row=r, column=c, value=v)
    cell.font = F_LINK if link and v else F_BODY
    if link and v:
        cell.hyperlink = v
    if fmt:
        cell.number_format = fmt
    cell.alignment = WRAP if wrap else TOP
    cell.border = BORDER
    return cell


def job_rows(ws, rows, employer_key="organisation"):
    header(ws, JOB_COLS)
    for i, r in enumerate(rows, start=2):
        vals = [i - 1, r.get(employer_key) or r.get("employer_on_advert") or "", r["title"], r.get("family", ""), r.get("level", ""),
                r.get("city", ""), r.get("location", ""), r.get("work_mode", ""), r.get("salary", ""), ddate(r.get("closing")),
                r.get("status_note", ""), r.get("visa_note", ""), r.get("flags", ""), r.get("sector", ""), r.get("priority", ""),
                r.get("how", ""), dtime(r.get("checked_at")), dtime(r.get("second_checked_at")),
                (r.get("second_check", "") + (": " + r["second_note"] if r.get("second_note") else "")).strip(": "), r.get("url", "")]
        for c, v in enumerate(vals, start=1):
            fmt = "dd mmm yyyy" if c == 10 else "dd mmm yyyy hh:mm" if c in (17, 18) else None
            put(ws, i, c, v, link=(c == 20), fmt=fmt, wrap=c in (3, 11, 12, 13, 16, 19))
        for c in range(INPUT_FROM, len(JOB_COLS) + 1):
            cell = ws.cell(row=i, column=c)
            cell.fill, cell.font, cell.border = FILL_INPUT, F_BODY, BORDER
        ws.cell(row=i, column=INPUT_FROM).value = "To apply"
        ws.cell(row=i, column=INPUT_FROM + 1).number_format = "dd mmm yyyy"
    last = max(2, len(rows) + 1)
    dv = DataValidation(type="list", formula1='"' + ",".join(STATUSES) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"{get_column_letter(INPUT_FROM)}2:{get_column_letter(INPUT_FROM)}{MAXROW}")
    ws.auto_filter.ref = f"A1:{get_column_letter(len(JOB_COLS))}{last}"


def simple_sheet(ws, cols, rows, links=(), wraps=(), dates=()):
    header(ws, cols)
    for i, vals in enumerate(rows, start=2):
        for c, v in enumerate(vals, start=1):
            put(ws, i, c, v, link=c in links, wrap=c in wraps, fmt="dd mmm yyyy hh:mm" if c in dates else None)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{max(2, len(rows) + 1)}"


def read_first_jobs(ws, label, n_companies, sources):
    ws.title = "Read first"
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 70
    ws.column_dimensions["C"].width = 60
    ws["A1"] = "UK graduate and entry-level data roles"
    ws["A1"].font = F_TITLE
    ws["A2"] = f"Checked {label}. Employers come from the Home Office register of licensed sponsors (Skilled Worker route), " \
               f"filtered to finance, banking, investment, consulting, data, government, universities and research."
    ws["A2"].font = F_NOTE
    rows = [("Live roles on the Jobs sheet", "=COUNTA(Jobs!C2:C3000)"),
            ("  of which entry title (junior, graduate, associate, assistant)", '=COUNTIF(Jobs!E2:E3000,"Entry title*")'),
            ("  of which level read from the advert (no level word in the title)", '=COUNTA(Jobs!C2:C3000)-COUNTIF(Jobs!E2:E3000,"Entry title*")'),
            ("  with a closing date", "=COUNT(Jobs!J2:J3000)"),
            ("  saying no sponsorship", '=COUNTIF(Jobs!L2:L3000,"*no sponsorship*")'),
            ("Live roles at employers not matched to the shortlist", "=COUNTA('Other live roles'!C2:C3000)"),
            ("Adverts left out (with the reason)", "=COUNTA(Excluded!B2:B3000)"),
            ("Companies whose careers pages were checked", n_companies),
            ("Your applications marked Applied or later", '=COUNTA(Jobs!U2:U3000)-COUNTIF(Jobs!U2:U3000,"To apply")-COUNTIF(Jobs!U2:U3000,"Not for me")')]
    r = 4
    ws.cell(row=r, column=1, value="Counts").font = F_SUB
    for k, v in rows:
        r += 1
        ws.cell(row=r, column=1, value=k).font = F_BODY
        c = ws.cell(row=r, column=2, value=v)
        c.font, c.alignment = F_BOLD, Alignment(horizontal="left")
    r += 2
    ws.cell(row=r, column=1, value="How each role was checked").font = F_SUB
    checks = [("Check 1", "The advert was read live on the employer's careers page or hiring system (or jobs.ac.uk, the Civil Service Analysis Function list or DWP Find a job)."),
              ("Check 2", "The same link was opened again in a separate request. Roles closed at either check are on the Excluded sheet.")]
    closing_note = "Taken from the advert. Roles with no closing date were listed live at both checks; apply early, since they can close without notice."
    if not n_companies:
        closing_note = "Taken from the search result. Rows with no closing date were shown as open or rolling; apply early, since they can close without notice."
        checks = [("Check 1", "Found in a web search result that showed a future closing date or an open, rolling application window."),
                  ("Check 2", "Not done yet. This session could not open employer websites. Running uk_crawl.py and uk_verify.py "
                              "in a session with full network access re-opens every link and replaces this sheet.")]
    for k, v in checks + [
                 ("Closing date", closing_note),
                 ("Level", "'Entry title' means the title says junior, graduate, associate, assistant or entry level. Other rows show what the advert asks: years of experience (0-2 kept, 3+ left out), 'Entry level stated in advert', or 'Level not stated'."),
                 ("Sources used", sources)]:
        r += 1
        ws.cell(row=r, column=1, value=k).font = F_BOLD
        c = ws.cell(row=r, column=2, value=v)
        c.font, c.alignment = F_BODY, WRAP
    r += 2
    ws.cell(row=r, column=1, value="Visa facts for your case").font = F_SUB
    ws.cell(row=r, column=3, value="Source").font = F_BOLD
    for k, v, s in GRAD_VISA:
        r += 1
        ws.cell(row=r, column=1, value=k).font = F_BOLD
        c = ws.cell(row=r, column=2, value=v)
        c.font, c.alignment = F_BODY, WRAP
        c = ws.cell(row=r, column=3, value=s)
        c.font, c.alignment = F_NOTE, WRAP
        ws.row_dimensions[r].height = 42
    r += 2
    ws.cell(row=r, column=1, value="Columns you fill in").font = F_SUB
    r += 1
    ws.cell(row=r, column=1, value="Yellow cells").font = F_BODY
    c = ws.cell(row=r, column=2, value="Status (drop-down), Date applied, Your notes. Everything else comes from the adverts.")
    c.fill, c.font = FILL_INPUT, F_BODY


EMAIL_SUBJECT = "Graduate data role enquiry: MSc Data Science (Nottingham), available now"
EMAIL_BODY = """Dear {Company} recruitment team,

I am writing to ask whether you have, or expect to have, any graduate or junior roles in data analysis, data science or statistics. My CV is attached.

I completed an MSc in Data Science at the University of Nottingham in September 2026 (Merit, with 80% in Statistical Machine Learning), after a first-class BSc in Mathematics from the University of Delhi. I work in Python, R and SQL. Recent projects include a road-collision severity model on 29,628 STATS19 records and seasonal ARIMA forecasts of East Midlands house prices.

I live in London and can start straight away. I am applying for the Graduate visa this month. Once granted, it gives me two years' right to work in the UK without sponsorship.

If nothing suitable is open at the moment, I would be grateful if you could keep my CV on file and contact me when a role comes up.

Kind regards,
Manoj Chandra
[mobile] | [email] | manojchandra.co.uk | github.com/manojchandra10"""


def read_first_contacts(ws, label):
    ws.title = "Read first"
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 100
    ws["A1"] = "Companies to email with your CV"
    ws["A1"].font = F_TITLE
    ws["A2"] = f"Checked {label}. These sponsors had no live entry-level data role on their own careers pages at the time of the check."
    ws["A2"].font = F_NOTE
    rows = [("Companies with an email", "=COUNTA(Contacts!A2:A5000)"),
            ("  priority A", '=COUNTIF(Contacts!C2:C5000,"A")'),
            ("  marked Sent", '=COUNTIF(Contacts!K2:K5000,"Sent")+COUNTIF(Contacts!K2:K5000,"Replied")+COUNTIF(Contacts!K2:K5000,"No reply after 2 weeks")'),
            ("  replied", '=COUNTIF(Contacts!K2:K5000,"Replied")'),
            ("Companies with no email found", "=COUNTA('No email found'!A2:A8000)")]
    r = 4
    for k, v in rows:
        ws.cell(row=r, column=1, value=k).font = F_BODY
        c = ws.cell(row=r, column=2, value=v)
        c.font, c.alignment = F_BOLD, Alignment(horizontal="left")
        r += 1
    r += 1
    for k, v in [("Which addresses", "Only role-based addresses published on the company's own website (careers@, recruitment@, hr@, info@ and similar). Personal addresses were left out on purpose."),
                 ("How to send", "One email per company, CV attached as a PDF. Send 20 to 30 a day, priority A first, and mark each row in the yellow Sent column. Follow up once after two weeks if there is no reply."),
                 ("Subject line", EMAIL_SUBJECT),
                 ("Email text", EMAIL_BODY)]:
        ws.cell(row=r, column=1, value=k).font = F_BOLD
        c = ws.cell(row=r, column=2, value=v)
        c.font, c.alignment = F_BODY, WRAP
        if k == "Email text":
            ws.row_dimensions[r].height = 300
        r += 1


CONTACT_COLS = [("Organisation (sponsor register)", 34), ("Sector", 14), ("Priority", 8), ("Town", 14), ("Website", 32),
                ("Careers page", 36), ("Best email", 30), ("Other emails", 34), ("Email found on", 36), ("Checked", 16),
                ("Sent", 18), ("Date sent", 12), ("Reply or notes", 36)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--seed", default="")
    ap.add_argument("--label", default=dt.date.today().strftime("%-d %B %Y"))
    a = ap.parse_args()
    d, out = Path(a.data_dir), Path(a.out_dir)
    src = d / "roles_checked.jsonl" if (d / "roles_checked.jsonl").exists() else d / "roles.jsonl"
    roles = [json.loads(l) for l in src.read_text(encoding="utf8").splitlines() if l.strip()] if src.exists() else []
    if a.seed:
        roles += json.loads(Path(a.seed).read_text(encoding="utf8"))
    comps = [json.loads(l) for l in (d / "companies.jsonl").read_text(encoding="utf8").splitlines() if l.strip()] \
        if (d / "companies.jsonl").exists() else []

    def live(r):
        return not r.get("exclude") and not r.get("duplicate_of") and r.get("second_check", "Open") != "Closed"

    order = {"A": 0, "B": 1, "C": 2}
    key = lambda r: (order.get(r.get("priority"), 3), r.get("closing") or "9999", (r.get("organisation") or r.get("employer_on_advert") or "").lower())
    matched = sorted([r for r in roles if live(r) and r.get("organisation")], key=key)
    other = sorted([r for r in roles if live(r) and not r.get("organisation")], key=key)
    excluded = [r for r in roles if not live(r)]

    wb = Workbook()
    sources = "Employer careers pages and their hiring systems; jobs.ac.uk; Civil Service Analysis Function vacancies; DWP Find a job."
    if a.seed:
        sources += " Rows whose How found starts with 'Web search' came from web search results."
    if not comps:
        sources = "Web search results only: " + ", ".join(sorted({r.get("how", "").replace("Web search: ", "") for r in roles if r.get("how")})) + "."
    read_first_jobs(wb.active, a.label, len(comps), sources)
    job_rows(wb.create_sheet("Jobs"), matched)
    job_rows(wb.create_sheet("Other live roles"), other, employer_key="employer_on_advert")
    simple_sheet(wb.create_sheet("Excluded"),
                 [("Employer", 30), ("Job title", 40), ("Role family", 22), ("Reason left out", 40), ("How found", 30), ("Checked", 16), ("Link", 50)],
                 [[r.get("organisation") or r.get("employer_on_advert") or "", r.get("title", ""), r.get("family") or "",
                   r.get("exclude") or ("Duplicate of " + r["duplicate_of"] if r.get("duplicate_of") else r.get("second_note", "")),
                   r.get("how", ""), dtime(r.get("checked_at")), r.get("url", "")] for r in excluded],
                 links=(7,), wraps=(2, 4), dates=(6,))
    simple_sheet(wb.create_sheet("Companies checked"),
                 [("Organisation", 34), ("Sector", 14), ("Priority", 8), ("Town", 14), ("Website", 32), ("How the website was found", 30),
                  ("Careers pages read", 40), ("Hiring system", 26), ("Adverts seen", 10), ("Roles kept", 10), ("Emails found", 30),
                  ("Note", 40), ("Checked", 16)],
                 [[c["organisation"], c["sector"], c["priority"], c["town"], c["site"], c["site_note"], " | ".join(c["careers_pages"]),
                   ", ".join(c["ats"]), c["jobs_seen"], c["kept"], ", ".join(c["emails"]), c["note"], dtime(c["checked_at"])] for c in comps],
                 links=(5,), wraps=(6, 7, 12), dates=(13,))
    out.mkdir(parents=True, exist_ok=True)
    wb.save(out / "UK_Data_Jobs.xlsx")

    # contacts: companies with no kept role
    with_role = {r.get("organisation") for r in matched}
    no_role = [c for c in comps if c["organisation"] not in with_role]
    wb2 = Workbook()
    read_first_contacts(wb2.active, a.label)
    ws = wb2.create_sheet("Contacts")
    header(ws, CONTACT_COLS)
    has = sorted([c for c in no_role if c["emails"]], key=lambda c: (order.get(c["priority"], 3), c["organisation"].lower()))
    for i, c in enumerate(has, start=2):
        vals = [c["organisation"], c["sector"], c["priority"], c["town"], c["site"], (c["careers_pages"] or [""])[0],
                c["emails"][0], ", ".join(c["emails"][1:]), c["email_page"], dtime(c["checked_at"])]
        for j, v in enumerate(vals, start=1):
            put(ws, i, j, v, link=j in (5, 6, 9), fmt="dd mmm yyyy hh:mm" if j == 10 else None)
        for j in range(11, 14):
            cell = ws.cell(row=i, column=j)
            cell.fill, cell.font, cell.border = FILL_INPUT, F_BODY, BORDER
        ws.cell(row=i, column=11).value = "Not sent"
        ws.cell(row=i, column=12).number_format = "dd mmm yyyy"
    dv = DataValidation(type="list", formula1='"' + ",".join(SENT) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"K2:K{MAXROW * 2}")
    ws.auto_filter.ref = f"A1:M{max(2, len(has) + 1)}"
    simple_sheet(wb2.create_sheet("No email found"),
                 [("Organisation", 34), ("Sector", 14), ("Priority", 8), ("Town", 14), ("Website", 32), ("Careers page", 36), ("Note", 50)],
                 [[c["organisation"], c["sector"], c["priority"], c["town"], c["site"], (c["careers_pages"] or [""])[0],
                   c["note"] or c["site_note"]] for c in sorted([c for c in no_role if not c["emails"]],
                                                               key=lambda c: (order.get(c["priority"], 3), c["organisation"].lower()))],
                 links=(5, 6), wraps=(7,))
    wb2.save(out / "UK_Speculative_Contacts.xlsx")
    print(f"Jobs {len(matched)}, other live roles {len(other)}, excluded {len(excluded)}, companies {len(comps)}, "
          f"contacts with email {len(has)}, without {len(no_role) - len(has)}")


if __name__ == "__main__":
    main()
