#!/usr/bin/env python3
"""Write one Excel workbook per country from final.json and excluded.json.

Usage: python3 -I build_xlsx.py <data_dir> <out_dir> [checked_label]
"""
import sys, json, datetime as dt
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.comments import Comment
from openpyxl.utils import get_column_letter

DATA = Path(sys.argv[1]).resolve()
OUTDIR = Path(sys.argv[2]).resolve()
CHECKED = sys.argv[3] if len(sys.argv) > 3 else dt.date.today().strftime("%-d %B %Y")

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
THIN = Side(style="thin", color="D0D5DD")
BORDER = Border(bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
TOP = Alignment(vertical="top")

STATUSES = ["To apply", "Applied", "Assessment", "Interview", "Offer", "Rejected", "Not for me"]
COLUMNS = [
    ("No.", 6), ("Employer", 26), ("Job title", 40), ("City", 13), ("Location as advertised", 28),
    ("Work mode", 11), ("Role area", 17), ("Level", 22), ("Experience asked (years)", 12),
    ("Language", 18), ("Language evidence", 44), ("Salary as advertised", 30), ("Work permit note", 46),
    ("Posted", 12), ("Days since posted", 10), ("Check 1 (found live)", 17), ("Check 2 (re-opened)", 17),
    ("Second check result", 26), ("Source", 22), ("Also listed on", 22), ("Link", 50),
    ("Status", 13), ("Date applied", 13), ("Your notes", 40),
]
COUNTRY = {
    "AT": {"name": "Austria", "file": "Austria_Data_Jobs.xlsx",
           "cities": ["Vienna", "Graz", "Linz", "Salzburg", "Innsbruck", "Klagenfurt", "Villach", "Wels", "St. Pölten", "Dornbirn", "Other"],
           "permits": [
               ("EU Blue Card minimum pay, 2026", "EUR 55,678 a year",
                "migration.gv.at (Blaue Karte EU); oesterreich.gv.at", "No points and no language certificate needed."),
               ("Red-White-Red Card, other key workers, minimum pay 2026", "EUR 3,465 a month plus special payments",
                "migration.gv.at (sonstige Schlüsselkräfte)", "Also needs 55 of 90 points: you score 45-46 without a language certificate."),
               ("Red-White-Red Card, shortage occupation", "Collective-agreement pay; 55 of 90 points",
                "migration.gv.at (Fachkräfte in Mangelberufen); Fachkräfteverordnung 2026, BGBl. II Nr. 316/2025",
                "Item 34 (Diplomingenieur/innen für Datenverarbeitung) matches your MSc level."),
               ("English certificate points", "B1 or above = 10 points",
                "migration.gv.at; Work in Austria points system", "Takes you from 45-46 to 55-56 points."),
           ]},
    "DE": {"name": "Germany", "file": "Germany_Data_Jobs.xlsx",
           "cities": ["Berlin", "Hamburg", "Munich", "Cologne", "Frankfurt", "Stuttgart", "Düsseldorf", "Leipzig", "Dortmund",
                      "Essen", "Bremen", "Dresden", "Hanover", "Nuremberg", "Duisburg", "Other"],
           "permits": [
               ("EU Blue Card, standard minimum pay 2026", "EUR 50,700 a year",
                "Make it in Germany, salary thresholds PDF (2026)", "No German and no points needed."),
               ("EU Blue Card, career starters (degree within 3 years), 2026", "EUR 45,934.20 a year",
                "Make it in Germany, salary thresholds PDF (2026)", "Your September 2026 MSc counts until about September 2029. Federal Employment Agency approval needed."),
               ("Skilled-worker permit for graduates (section 18b)", "No set minimum under age 45",
                "Section 18b Residence Act (visaright.eu summary)", "Pay must match comparable German workers; Federal Employment Agency approval."),
               ("Opportunity Card (job search, up to 12 months)", "About EUR 1,091 a month in funds",
                "Make it in Germany, Opportunity Card requirements", "Needs English B2 or German A1 and a recognised degree."),
           ]},
}


def ddate(s):
    try:
        return dt.date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def ddatetime(s):
    try:
        return dt.datetime.strptime(s, "%Y-%m-%d %H:%M") if s else None
    except ValueError:
        return None


def jobs_sheet(ws, rows):
    ws.title = "Jobs"
    for c, (name, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=c, value=name)
        cell.font, cell.fill, cell.alignment = F_HEAD, FILL_HEAD, Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(c)].width = width
    for name in ("Status", "Date applied", "Your notes"):
        c = [n for n, _ in COLUMNS].index(name) + 1
        ws.cell(row=1, column=c).fill = PatternFill("solid", fgColor="B7791F")
    ws.row_dimensions[1].height = 32
    col = {n: i + 1 for i, (n, _) in enumerate(COLUMNS)}
    for r, x in enumerate(rows, start=2):
        vals = {
            "No.": r - 1, "Employer": x.get("company"), "Job title": x.get("title"), "City": x.get("city"),
            "Location as advertised": x.get("location"), "Work mode": x.get("mode"), "Role area": x.get("area"),
            "Level": x.get("level"), "Experience asked (years)": x.get("years") if x.get("years") is not None else "not stated",
            "Language": x.get("language"), "Language evidence": x.get("lang_evidence"),
            "Salary as advertised": x.get("salary_text") or "not stated", "Work permit note": x.get("permit"),
            "Posted": ddate(x.get("posted")), "Check 1 (found live)": ddatetime(x.get("collected_at")),
            "Check 2 (re-opened)": ddatetime(x.get("check2_at")), "Second check result": x.get("check2_note"),
            "Source": x.get("source"), "Also listed on": ", ".join(x.get("also_on") or []) or "",
            "Link": x.get("url"), "Status": "To apply", "Date applied": None, "Your notes": None,
        }
        for name, v in vals.items():
            cell = ws.cell(row=r, column=col[name], value=v)
            cell.font = F_BODY
            cell.alignment = WRAP if name in ("Job title", "Language evidence", "Work permit note", "Salary as advertised",
                                              "Location as advertised", "Your notes") else TOP
            cell.border = BORDER
        posted = ws.cell(row=r, column=col["Posted"])
        posted.number_format = "DD/MM/YYYY"
        p_letter = get_column_letter(col["Posted"])
        dcell = ws.cell(row=r, column=col["Days since posted"], value=f'=IF({p_letter}{r}="","",TODAY()-{p_letter}{r})')
        dcell.font, dcell.alignment, dcell.number_format = F_BODY, TOP, "0"
        for name in ("Check 1 (found live)", "Check 2 (re-opened)"):
            ws.cell(row=r, column=col[name]).number_format = "DD/MM/YYYY HH:MM"
        link = ws.cell(row=r, column=col["Link"])
        if x.get("url"):
            link.hyperlink = x["url"]
            link.font = F_LINK
        for name in ("Status", "Date applied", "Your notes"):
            ws.cell(row=r, column=col[name]).fill = FILL_INPUT
        ws.cell(row=r, column=col["Date applied"]).number_format = "DD/MM/YYYY"
    last = max(2, len(rows) + 1)
    s_letter = get_column_letter(col["Status"])
    dv = DataValidation(type="list", formula1='"' + ",".join(STATUSES) + '"', allow_blank=True,
                        showErrorMessage=True, errorTitle="Status", error="Pick a status from the list.")
    ws.add_data_validation(dv)
    dv.add(f"{s_letter}2:{s_letter}{last + 200}")
    for r in range(len(rows) + 2, last + 201):
        for name in ("Status", "Date applied", "Your notes"):
            ws.cell(row=r, column=col[name]).fill = FILL_INPUT
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{last}"
    return col, last


def excluded_sheet(wb, rows):
    ws = wb.create_sheet("Excluded")
    heads = [("Employer", 28), ("Job title", 44), ("City", 13), ("Source", 22), ("Reason", 60), ("Link", 50)]
    for c, (name, w) in enumerate(heads, start=1):
        cell = ws.cell(row=1, column=c, value=name)
        cell.font, cell.fill = F_HEAD, FILL_HEAD
        ws.column_dimensions[get_column_letter(c)].width = w
    for r, x in enumerate(rows, start=2):
        vals = [x.get("company"), x.get("title"), x.get("city"), x.get("source"), "; ".join(x.get("reasons") or []), x.get("url")]
        for c, v in enumerate(vals, start=1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.font, cell.alignment, cell.border = F_BODY, WRAP if c in (2, 5) else TOP, BORDER
        if x.get("url"):
            ws.cell(row=r, column=6).hyperlink = x["url"]
            ws.cell(row=r, column=6).font = F_LINK
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:F{max(2, len(rows) + 1)}"
    return ws, max(2, len(rows) + 1)


REASON_KEYS = [
    ("German required", "German required"),
    ("Asks for 3 or more years, or not open to graduates", "Asks for 3 or more years"),
    ("Remote only", "Remote only"),
    ("Closed at first check", "Closed (first check)"),
    ("Closing date passed", "Closing date passed"),
    ("Closed or unreachable on second check", "Closed or unreachable on second check"),
    ("Advert text could not be read", "Advert text could not be read"),
]


def read_first(wb, cc, n_jobs, last_job_row, col, n_excl, last_excl_row):
    ws = wb.create_sheet("Read first", 0)
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 26
    ws.column_dimensions["C"].width = 48
    ws.column_dimensions["D"].width = 60
    r = 1
    ws.cell(row=r, column=1, value=f"{cc['name']} data jobs: graduate and junior, English-speaking").font = F_TITLE
    r += 1
    ws.cell(row=r, column=1, value=f"Every vacancy on the Jobs sheet was found live and then re-opened on {CHECKED}. "
                                   "Adverts close without notice, so open the link before you apply.").font = F_NOTE
    r += 2

    def section(title):
        nonlocal r
        ws.cell(row=r, column=1, value=title).font = F_SUB
        r += 1

    def line(a, b=None, c=None, d=None, bold=False):
        nonlocal r
        for i, v in enumerate([a, b, c, d], start=1):
            if v is not None:
                cell = ws.cell(row=r, column=i, value=v)
                cell.font = F_BOLD if (bold and i == 1) else F_BODY
                cell.alignment = WRAP
        r += 1

    section("Rules applied")
    for txt in [
        "Country: " + cc["name"] + ". Office or hybrid only; remote-only roles left out.",
        "Role: data analyst, data scientist, BI analyst, analytics engineer or ML engineer titles.",
        "Level: junior or graduate titles, or adverts asking for 0 to 2 years, or listed as entry level. Senior, lead, manager, "
        "internship, working-student, thesis and trainee adverts left out.",
        "Language: English only, German a plus, or no language stated in an English advert. Adverts in German, or asking "
        "for German at B2, C1 or 'fluent', left out.",
        "Active: found live on the source, then re-opened at the end of the run; anything closed, expired or unreachable "
        "on either check was dropped.",
    ]:
        line(txt)
    r += 1
    section("How each vacancy was checked")
    for txt in [
        "Check 1: the listing was live on its source when collected (company hiring board, job board or LinkedIn).",
        "Check 2: the advert itself was opened again at the end of the run and read for 'closed', 'expired' or "
        "'no longer accepting applications'. The time of each check is on the Jobs sheet.",
        "Where the same job appeared on several sources, the employer's own page was kept and the others are listed under "
        "'Also listed on'.",
    ]:
        line(txt)
    r += 1
    section("Counts (live formulas from the Jobs sheet)")
    jr = f"Jobs!$B$2:$B${last_job_row}"
    lang_col = get_column_letter(col["Language"])
    area_col = get_column_letter(col["Role area"])
    city_col = get_column_letter(col["City"])
    status_col = get_column_letter(col["Status"])
    rng = lambda letter: f"Jobs!${letter}$2:${letter}${last_job_row}"
    line("Vacancies on the Jobs sheet", f"=COUNTA({jr})", bold=True)
    for lab in ["English only", "German a plus", "Language not stated"]:
        line("Language: " + lab, f'=COUNTIF({rng(lang_col)},"{lab}")')
    for lab in ["Data analyst", "BI analyst", "Analytics engineer", "Data scientist", "ML engineer"]:
        line("Role area: " + lab, f'=COUNTIF({rng(area_col)},"{lab}")')
    for lab in cc["cities"]:
        line("City: " + lab, f'=COUNTIF({rng(city_col)},"{lab}")')
    for lab in STATUSES:
        line("Your status: " + lab, f'=COUNTIF({rng(status_col)},"{lab}")')
    r += 1
    section("Roles checked and left out (live formulas from the Excluded sheet)")
    er = f"Excluded!$E$2:$E${last_excl_row}"
    line("Checked and left out, total", f"=COUNTA(Excluded!$A$2:$A${last_excl_row})", bold=True)
    for lab, key in REASON_KEYS:
        line(lab, f'=COUNTIF({er},"*{key}*")')
    r += 1
    section("Filling in the Jobs sheet")
    line("Yellow columns are yours to fill in: Status (pick from the list), Date applied and Your notes. "
         "Everything else came from the adverts.")
    line("Example", "Status: Applied", "Date applied: 06/11/2026", "Your notes: Sent CV and cover letter on the company site")
    r += 1
    section("Work-permit figures used in the notes")
    line("Item", "Figure", "Source", "What it means for you", bold=True)
    for a, b, c, d in cc["permits"]:
        line(a, b, c, d)
    ws.cell(row=r, column=1, value="General information, not immigration advice. Figures change each January; check them before you accept an offer.").font = F_NOTE
    r += 2
    section("Limits")
    for txt in [
        "Pay is shown only where the advert states it; Austrian adverts must state the collective-agreement minimum.",
        "Language and level are read from the advert text by rules, so read each advert yourself before applying.",
        "Days since posted uses TODAY(), so it updates whenever the file is opened.",
    ]:
        line(txt)
    return ws


def build(country, final, excluded):
    cc = COUNTRY[country]
    rows = [x for x in final if x.get("country") == country]
    rows.sort(key=lambda x: (cc["cities"].index(x["city"]) if x.get("city") in cc["cities"] else 99,
                             {"Graduate": 0, "Junior": 1}.get(x.get("level"), 2), (x.get("company") or "").lower()))
    ex = [x for x in excluded if x.get("country") == country and x.get("area")]
    wb = Workbook()
    col, last = jobs_sheet(wb.active, rows)
    _, last_ex = excluded_sheet(wb, ex)
    read_first(wb, cc, len(rows), last, col, len(ex), last_ex)
    wb.active = 0
    out = OUTDIR / cc["file"]
    wb.save(out)
    print("wrote", out, "jobs", len(rows), "excluded", len(ex))
    return out


if __name__ == "__main__":
    final = json.loads((DATA / "final.json").read_text(encoding="utf8"))
    excluded = json.loads((DATA / "excluded.json").read_text(encoding="utf8"))
    OUTDIR.mkdir(parents=True, exist_ok=True)
    for c in ("AT", "DE"):
        build(c, final, excluded)
