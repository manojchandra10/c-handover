#!/usr/bin/env python3
"""Add Companies House industry (SIC) codes to the sponsor register and widen the shortlist with them.

Usage: python3 -I job_tools/uk_sic.py <register.csv> <shortlist.csv> <out.csv> [--zip BasicCompanyDataAsOneFile.zip]
Without --zip it downloads the free Companies House bulk file (about 470 MB) from download.companieshouse.gov.uk.
Every Skilled Worker sponsor whose registered company has a SIC code in finance, insurance, fund management,
management consultancy, data processing, market research, research and development, public administration or
higher education is added to the shortlist, including firms whose names carry no sector word. The output keeps
the shortlist's columns and adds 'SIC codes' and 'Found by' (Name, SIC code, or Name and SIC code).
"""
import sys, re, io, csv, zipfile, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from uk_shortlist import ends_with_ai, HARD_EXCLUDE   # same exclusions as the name-based pass

SIC_SECTORS = [  # (prefix, sector, tier)
    ("6411", "Banking", "A"), ("6419", "Banking", "A"), ("6430", "Investment", "A"), ("6491", "Finance", "B"),
    ("6492", "Finance", "B"), ("6499", "Finance", "B"), ("6511", "Finance", "A"), ("6512", "Finance", "A"),
    ("6520", "Finance", "A"), ("6530", "Investment", "A"), ("6611", "Investment", "A"), ("6612", "Investment", "A"),
    ("6619", "Finance", "B"), ("6621", "Finance", "A"), ("6622", "Finance", "B"), ("6629", "Finance", "B"),
    ("6630", "Investment", "A"), ("7022", "Consulting", "B"), ("6920", "Finance", "C"), ("6311", "Data", "A"),
    ("6399", "Data", "B"), ("7211", "Research", "A"), ("7219", "Research", "A"), ("7220", "Research", "A"),
    ("7320", "Data", "A"), ("8411", "Government", "A"), ("8412", "Government", "A"), ("8413", "Government", "A"),
    ("8542", "University", "A"),
]
BULK_PAGE = "https://download.companieshouse.gov.uk/en_output.html"


def norm(s):
    s = (s or "").lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(limited|ltd|llp|plc|the|uk|company|co)\b", " ", s)
    return " ".join(s.split())


def sector_of_sics(sics):
    for code in sics:
        for prefix, sector, tier in SIC_SECTORS:
            if code.startswith(prefix):
                return sector, tier
    return None, None


def open_bulk(zip_path):
    if zip_path:
        return zipfile.ZipFile(zip_path)
    import requests
    page = requests.get(BULK_PAGE, timeout=60).text
    m = re.search(r'href="(BasicCompanyDataAsOneFile-[\d-]+\.zip)"', page)
    if not m:
        sys.exit("Could not find the bulk file link on " + BULK_PAGE)
    url = BULK_PAGE.rsplit("/", 1)[0] + "/" + m.group(1)
    dest = Path(m.group(1))
    if not dest.exists():
        print("downloading", url)
        with requests.get(url, stream=True, timeout=120) as r, open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return zipfile.ZipFile(dest)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("register")
    ap.add_argument("shortlist")
    ap.add_argument("out")
    ap.add_argument("--zip", default="")
    a = ap.parse_args()

    with open(a.register, newline="", encoding="utf8") as f:
        reg = [r for r in csv.DictReader(f) if r["Route"].strip() == "Skilled Worker"]
    want = {}
    for r in reg:
        want.setdefault(norm(r["Organisation Name"]), []).append(r)
    print("Skilled Worker rows:", len(reg), "distinct names:", len(want))

    sics = {}
    z = open_bulk(a.zip)
    member = next(n for n in z.namelist() if n.lower().endswith(".csv"))
    with z.open(member) as raw:
        rd = csv.reader(io.TextIOWrapper(raw, encoding="utf8", errors="replace"))
        head = [h.strip() for h in next(rd)]
        i_name, i_status = head.index("CompanyName"), head.index("CompanyStatus")
        i_sic = [i for i, h in enumerate(head) if h.startswith("SICCode.SicText")]
        for row in rd:
            if len(row) <= max(i_sic):
                continue
            k = norm(row[i_name])
            if k in want and row[i_status].strip().lower() == "active":
                codes = [row[i].split(" - ")[0].strip() for i in i_sic if row[i].strip() and row[i][:1].isdigit()]
                if codes:
                    sics[k] = codes
    print("sponsors matched to an active company:", len(sics))

    with open(a.shortlist, newline="", encoding="utf8") as f:
        short = list(csv.DictReader(f))
    fields = list(short[0].keys()) + ["SIC codes", "Found by"]
    have = set()
    for s in short:
        codes = sics.get(norm(s["Organisation"]), [])
        s["SIC codes"] = "; ".join(codes)
        s["Found by"] = "Name and SIC code" if sector_of_sics(codes)[0] else "Name"
        have.add((s["Organisation"], s["Town/City"].lower()))
    added = 0
    for k, codes in sics.items():
        sector, tier = sector_of_sics(codes)
        if not sector:
            continue
        for r in want[k]:
            name, town = r["Organisation Name"].strip(), r["Town/City"].strip()
            low = " ".join(name.lower().split())
            if (name, town.lower()) in have or ends_with_ai(name) or HARD_EXCLUDE.search(low):
                continue
            if "B rating" in r["Type & Rating"]:
                tier = {"A": "B", "B": "C", "C": "C"}[tier]
            short.append({"Organisation": name, "Town/City": town.title(), "County": r["County"].strip().title(),
                          "Licence rating": r["Type & Rating"].strip(), "Primary sector": sector, "All sectors": sector,
                          "Priority": tier, "Known employer": "", "SIC codes": "; ".join(codes), "Found by": "SIC code"})
            have.add((name, town.lower()))
            added += 1
    order = {"A": 0, "B": 1, "C": 2}
    short.sort(key=lambda s: (order.get(s["Priority"], 3), s["Primary sector"], s["Organisation"].lower()))
    with open(a.out, "w", newline="", encoding="utf8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(short)
    print(f"added by SIC code: {added}; shortlist now {len(short)} -> {a.out}")


if __name__ == "__main__":
    main()
