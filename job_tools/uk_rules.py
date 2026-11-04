"""Rules for UK adverts: role family, level, location, closing date, open or closed, visa notes, pay, emails.

Pure functions only, so they can be tested without network access (see uk_test.py).
"""
import re
import datetime as dt
from rules import clean_text  # noqa: F401  (re-exported for the UK scripts)

# ---------------------------------------------------------------- role family and level

EXCLUDE_TITLE = [
    ("Senior or lead title", r"\b(senior|snr|sr\.?|lead|principal|staff|head|director|chief|vp|vice[- ]president|partner|"
                             r"architect|expert|manager|managing|supervisor|team leader)\b"),
    ("Internship or placement", r"\b(intern|internship|placement|industrial placement|year in industry|summer|spring week|"
                                r"insight (week|day|programme|program)|work experience|vacation scheme|undergraduate)\b"),
    ("Apprenticeship or school leaver", r"\b(apprentice|apprenticeship|school leaver|level [2-5]\b|t[- ]level|sixth form)\b"),
    ("Trainee title", r"\btrainee\b"),
    ("PhD or academic post", r"\b(phd|ph\.d|postdoc|post-doc|postdoctoral|research fellow|fellowship|lecturer|professor|reader in)\b"),
    ("Part-time, contract or temporary", r"\b(part[- ]time|contractor|freelance|temp|temporary|maternity cover|ad hoc|zero hours?)\b"),
    ("Unrelated graduate role", r"\bgraduate (civil|structural|mechanical|electrical|site|quantity|building|geotechnical|planner|planning|"
                                r"architect|surveyor|solicitor|lawyer|legal|paralegal|teacher|teaching|nurse|pharmacist|chef|sales|"
                                r"recruit\w*|marketing|hr|human resources|property|estate|engineer|engineering|design|designer)\b"),
]
EXCLUDE_TITLE = [(why, re.compile(p, re.I)) for why, p in EXCLUDE_TITLE]

DATA_WORDS = r"(data|bi|business intelligence|insights?|analytics|reporting|mi|management information|quantitative|quant|statistic\w*|" \
             r"research|risk|pricing|actuarial|modell?ing|machine learning|ml|decision|forecasting|performance|commercial|product|" \
             r"marketing|fraud|people|workforce|customer|digital)"
FAMILIES = [
    ("Junior statistician", r"\b(assistant|junior|graduate|associate|entry[- ]level|trainee)\s+statistician\b|"
                            r"\bstatistical (officer|analyst|assistant)\b|\bstatistician\b"),
    ("Associate data scientist", r"\bassociate\b[^,|/()]{0,30}\b(data scien\w*|machine learning scien\w*|ml scien\w*|decision scien\w*)"),
    ("Junior data scientist", r"\b(junior|jr\.?|graduate|entry[- ]level|assistant|early[- ]careers?)\b[^,|/()]{0,30}"
                              r"\b(data scien\w*|machine learning scien\w*|ml scien\w*|decision scien\w*|applied scien\w*)|"
                              r"\bdata scien\w*[^,|/()]{0,20}\b(junior|graduate|entry[- ]level)\b"),
    ("Associate data analyst", r"\bassociate\b[^,|/()]{0,30}\b" + DATA_WORDS + r"\s+analyst\b"),
    ("Junior data analyst", r"\b(junior|jr\.?|graduate|entry[- ]level|assistant|early[- ]careers?)\b[^,|/()]{0,30}\b" + DATA_WORDS +
                            r"\s+analyst\b|\b" + DATA_WORDS + r"\s+analyst\b[^,|/()]{0,20}\b(junior|graduate|entry[- ]level)\b"),
    ("Entry-level consultant", r"\b(junior|graduate|associate|entry[- ]level|assistant|analyst)\b[^,|/()]{0,30}\bconsultant\b|"
                               r"\bconsult(ing|ancy) analyst\b|\bconsultant\b[^,|/()]{0,25}\b(graduate|entry[- ]level|junior)\b"),
    ("Graduate programme", r"\bgraduate\b|\bgrad scheme\b|\bearly careers? programme\b|\bnew grad\b"),
    # No level word in the title: kept only with entry evidence in the text, or labelled "level not stated".
    ("Analyst (level from advert)", r"\b" + DATA_WORDS + r"\s+analyst\b|\banalyst\b[^,|/()]{0,20}\b(data|analytics|insight|bi)\b"),
    ("Data scientist (level from advert)", r"\bdata scien\w*|\bmachine learning scien\w*|\bdecision scien\w*"),
]
FAMILIES = [(f, re.compile(p, re.I)) for f, p in FAMILIES]
GRAD_TOPIC = re.compile(r"\b(data|analy\w*|insight|bi|technology|tech|digital|consult\w*|risk|finance|financial|banking|"
                        r"investment|markets?|quant\w*|statistic\w*|actuar\w*|research|economic\w*|modell?ing|scien\w*|"
                        r"audit|assurance|advisory|strategy|operations|programme|program|scheme|analyst|associate|"
                        r"software|developer|cyber|ai|machine learning|2026|2027)\b", re.I)

YEARS = re.compile(r"(?<![\d.£$-])(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(\d{1,2})\s*)?(?:\+\s*)?years?(?:'|’)?\s+"
                   r"(?:of\s+)?(?:\w+\s+){0,4}?(?:experience|exp\b|in a similar|working)", re.I)
ENTRY_TEXT = re.compile(r"\b(no (prior |previous )?experience (is )?(required|needed|necessary)|recent graduates?|graduates? welcome|"
                        r"entry[- ]level|early[- ]careers?|first role|new graduates?|graduate (role|position|opportunity|level)|"
                        r"0\s*(?:-|–|to)\s*[12]\s*years?|up to (1|2|one|two) years?|career starter|recently graduated|"
                        r"junior (role|position|level))\b", re.I)


def experience_asked(text):
    """(lowest minimum, its upper bound or None) for the years of experience asked, or None."""
    asks = []
    for m in YEARS.finditer(text or ""):
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else None
        if lo <= 15 and (hi is None or hi >= lo):
            asks.append((lo, hi))
    return min(asks) if asks else None


def _years_label(ask):
    lo, hi = ask
    return f"Asks {lo}-{hi} years" if hi else f"Asks {lo}+ years" if lo else "Asks 0 years"


def classify_title(title):
    """Return (family, None) for a wanted title or (None, reason) when the title is out of scope."""
    t = " ".join((title or "").split())
    for why, rx in EXCLUDE_TITLE:
        if rx.search(t):
            # "Graduate Consultant – Data & Analytics, Manager-led team" is rare; titles naming a senior grade are dropped.
            return None, why
    for fam, rx in FAMILIES:
        if rx.search(t):
            if fam == "Graduate programme" and not GRAD_TOPIC.search(t):
                return None, "Graduate role outside data, analytics, consulting, finance or research"
            return fam, None
    return None, "Title is not one of the wanted roles"


def assess_level(family, title, text):
    """Return (level label, exclusion reason or None)."""
    ask = experience_asked(text)
    if ask and ask[0] >= 3:
        return _years_label(ask), f"Asks for {ask[0]}+ years of experience"
    if "(level from advert)" in family:
        if ask:
            return _years_label(ask), None
        if ENTRY_TEXT.search(text or ""):
            return "Entry level stated in advert", None
        return "Level not stated", None
    if ask:
        return "Entry title, " + _years_label(ask).lower(), None
    return "Entry title", None


# ---------------------------------------------------------------- location

UK_TOKEN_RX = re.compile(r"\b(united kingdom|england|scotland|wales|northern ireland|great britain|uk|gb|gbr)\b", re.I)
NON_UK = re.compile(r"\b(usa|united states|u\.s\.|canada|ontario|australia|new zealand|india|ireland|dublin|singapore|"
                    r"hong kong|germany|france|netherlands|spain|poland|portugal|south africa|dubai|uae|"
                    r"(ma|ct|nh|nc|va|pa|al|ky|ny|nj|tx|ca|wa|il|oh|mi|ga|fl)\s*$)\b", re.I)


def _multiword_place_regex():
    words = []
    for line in """london|city of london|canary wharf|manchester|birmingham|leeds|bradford|sheffield|york|hull|newcastle|
sunderland|durham|middlesbrough|liverpool|chester|preston|lancaster|nottingham|leicester|derby|loughborough|coventry|
warwick|wolverhampton|stoke|bristol|bath|exeter|plymouth|cardiff|swansea|newport|edinburgh|glasgow|aberdeen|dundee|
stirling|st andrews|inverness|belfast|cambridge|oxford|reading|slough|bracknell|guildford|woking|milton keynes|
northampton|luton|watford|st albans|stevenage|hatfield|southampton|portsmouth|bournemouth|poole|brighton|crawley|
horsham|maidstone|canterbury|chelmsford|colchester|southend|basildon|ipswich|norwich|peterborough|lincoln|swindon|
cheltenham|gloucester|worcester|harwell|didcot|farnborough|basingstoke|winchester|taunton|chippenham|leamington|
telford|shrewsbury|huddersfield|wakefield|harrogate|darlington|knutsford|macclesfield|warrington|wigan|bolton|
blackburn|ilford|harrow|wembley|uxbridge|hounslow|richmond|kingston|wimbledon|sutton|bromley|romford|enfield|barnet|
hammersmith|camden|islington|croydon|stratford|westminster|salford|stockport""".split("\n"):
        words += [w.strip() for w in line.split("|") if w.strip()]
    return re.compile(r"\b(" + "|".join(sorted(set(words), key=len, reverse=True)) + r")\b", re.I)


UK_PLACE_RX = _multiword_place_regex()


def uk_place(location, fallback_town=""):
    """Return (is_uk: True/False/None, city label). None means the advert gives no location."""
    loc = " ".join((location or "").split())
    if not loc:
        return None, ((fallback_town or "").title() + " (register address)") if fallback_town else ""
    low = " " + loc.lower() + " "
    m = UK_PLACE_RX.search(low)
    uk_token = bool(UK_TOKEN_RX.search(low))
    if NON_UK.search(loc) and not uk_token:
        return False, ""
    if m:
        return True, m.group(1).title().replace("Of", "of")
    if uk_token:
        return True, "UK (city not stated)"
    if re.search(r"\b(remote|hybrid|home[- ]based|flexible)\b", low):
        return None, "Remote or flexible (country not stated)"
    return False, ""


def work_mode(text, location=""):
    low = ((location or "") + " " + (text or "")).lower()
    if re.search(r"\b(fully remote|100% remote|remote[- ]first|work from home|home[- ]based|remote \(uk\)|uk remote|remote uk)\b", low):
        return "Remote"
    if re.search(r"\bhybrid\b|\b\d\s*(days?)\s*(a|per)\s*week\s*(in|at)\s*(the|our)?\s*office\b|\bflexible working\b", low):
        return "Hybrid"
    if re.search(r"\b(on[- ]site|office[- ]based|in[- ]office|onsite)\b", low):
        return "Office"
    return "Not stated"


# ---------------------------------------------------------------- dates, open or closed

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9
MON_RX = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
DATE_RXS = [
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + MON_RX + r",?\s+(\d{4})\b", re.I),   # 30 November 2026
    re.compile(r"\b" + MON_RX + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.I),           # November 30, 2026
    re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b"),                                         # 30/11/2026 (UK order)
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),                                                   # 2026-11-30
]
CLOSE_KEYS = re.compile(r"(closing date|closes|closing|close date|deadline|apply by|applications? (close|must be received)|"
                        r"application deadline|advert closes|vacancy closes|end date for applications|last date)", re.I)
ROLLING = re.compile(r"\b(rolling basis|ongoing recruitment|deadline:?\s*ongoing|no closing date|open until filled|"
                     r"until the role is filled|reserve the right to close)\b", re.I)
CLOSED_MARKERS = re.compile(
    r"(no longer accepting applications|this (job|vacancy|role|position|advert|posting) (has|is) (now )?(closed|expired|filled|no longer)|"
    r"applications? (are|is|have) (now )?closed|the closing date (for this (job|vacancy|role) )?has passed|position has been filled|"
    r"(job|vacancy|role|position|posting) is no longer available|this job is closed|job (has )?expired|vacancy (has )?closed|"
    r"no longer open for applications|we are no longer recruiting for this|this role has now closed|sorry,? this (job|vacancy) "
    r"(has|is)|the job you are looking for (is|has)|job not found|page not found|could not find (the|this) (job|page))", re.I)


def _mk(y, mo, d):
    try:
        return dt.date(int(y), int(mo), int(d))
    except ValueError:
        return None


def dates_in(text):
    out = []
    for i, rx in enumerate(DATE_RXS):
        for m in rx.finditer(text or ""):
            g = m.groups()
            if i == 0:
                d = _mk(g[2], MONTHS[g[1].lower()[:4] if g[1].lower().startswith("sept") else g[1].lower()[:3]], g[0])
            elif i == 1:
                d = _mk(g[2], MONTHS[g[0].lower()[:4] if g[0].lower().startswith("sept") else g[0].lower()[:3]], g[1])
            elif i == 2:
                d = _mk(g[2], g[1], g[0])
            else:
                d = _mk(g[0], g[1], g[2])
            if d:
                out.append((m.start(), d))
    return sorted(out)


def closing_date(text):
    """The first date that follows a closing-date phrase within 80 characters, else None."""
    text = text or ""
    found = []
    for k in CLOSE_KEYS.finditer(text):
        window = text[k.end(): k.end() + 80]
        ds = dates_in(window)
        if ds:
            found.append(ds[0][1])
    return min(found) if found else None


def open_status(text, valid_through=None, today=None):
    """Return (status, closing date or None, note). Status is Open, Closed or Unclear."""
    today = today or dt.date.today()
    text = text or ""
    if CLOSED_MARKERS.search(text):
        return "Closed", None, "Advert says it is closed"
    vt = None
    if valid_through:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(valid_through))
        vt = _mk(*m.groups()) if m else None
    cd = closing_date(text)
    when = min([d for d in (vt, cd) if d], default=None)
    if when:
        if when < today:
            return "Closed", when, "Closing date has passed"
        return "Open", when, "Closing date in the future"
    if ROLLING.search(text):
        return "Open", None, "Rolling or ongoing deadline"
    return "Open", None, "Listed live with no closing date"


# ---------------------------------------------------------------- visa, clearance, pay

def visa_note(text):
    low = (text or "").lower()
    notes = []
    if re.search(r"(unable to|cannot|can't|do not|don't|will not|won't|not able to) (offer|provide|support|sponsor)\w*[^.]{0,40}"
                 r"(sponsor|visa)|no (visa )?sponsorship|sponsorship (is )?not (available|offered|provided)|"
                 r"without (the need for|requiring|needing) (visa )?sponsorship|now or in the future", low):
        notes.append("Says no sponsorship")
    elif re.search(r"(we|can|will|are able to|happy to|able to) (offer|provide|consider) (visa )?sponsorship|sponsorship (is )?"
                   r"(available|offered|considered)|skilled worker (visa )?sponsor|visa sponsorship available", low):
        notes.append("Mentions sponsorship available")
    if re.search(r"\b(sc|dv|security|counter[- ]terrorist|ctc|developed vetting|nato)\b[^.]{0,20}\b(clearance|cleared|vetting|check)\b|"
                 r"\beligible for (sc|dv|security clearance)\b|resided in the uk for (at least |the (last|past) )?\d+ years?", low):
        notes.append("Security clearance or UK residence years needed")
    if re.search(r"\b(uk|british) (nationals?|citizens?) only\b|\bsole british\b|\bmust be a british (citizen|national)\b", low):
        notes.append("British nationals only")
    if re.search(r"civil service nationality rules", low):
        notes.append("Civil Service nationality rules (Commonwealth citizens can apply to most posts)")
    return "; ".join(notes)


def salary_of(text):
    """First GBP salary phrase, e.g. '£32,000 - £36,000 per annum'."""
    m = re.search(r"£\s?\d[\d,.]*\s?k?(?:\s*(?:-|–|to)\s*£?\s?\d[\d,.]*\s?k?)?(?:\s*(?:per annum|p\.?a\.?|a year|per year|pro rata))?",
                  text or "", re.I)
    return " ".join(m.group(0).split()).rstrip(".,") if m else ""


# ---------------------------------------------------------------- emails

EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ROLE_LOCAL = re.compile(r"^(?:[a-z]+[._-])?(careers?|jobs?|recruit\w*|talent\w*|hr|humanresources|people\w*|vacanc\w*|join\w*|"
                        r"hiring|graduates?|earlycareers|resourcing|workwithus|opportunities|cvs?|info|enquir\w*|hello|"
                        r"contact\w*|office|admin|mail|team|general|reception)(?:[._-][a-z]+)?$", re.I)
SKIP_LOCAL = re.compile(r"(no-?reply|donotreply|privacy|dpo|gdpr|data\.?protection|complaint|press|media|investor|^ir$|sales|"
                        r"marketing|support|helpdesk|accounts|billing|invoice|abuse|webmaster|security|legal|compliance|"
                        r"unsubscribe|newsletter|events|sponsor)", re.I)
EMAIL_RANK = ["careers", "career", "recruitment", "recruiting", "recruit", "jobs", "job", "talent", "hr", "people", "graduates",
              "earlycareers", "resourcing", "vacancies", "join", "hiring", "work", "cv", "info", "enquiries", "hello", "contact",
              "office", "admin", "mail", "team", "general", "reception"]


def deobfuscate(text):
    t = text or ""
    t = re.sub(r"\s*[\[(]\s*at\s*[\])]\s*", "@", t, flags=re.I)
    t = re.sub(r"\s*[\[(]\s*dot\s*[\])]\s*", ".", t, flags=re.I)
    return t


def registrable(host):
    host = (host or "").lower().split(":")[0].strip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "org", "ac", "gov", "nhs", "ltd", "plc", "me", "net", "sch", "police", "mod") and parts[-1] == "uk":
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def role_emails(text, site_host):
    """Role-based addresses on the company's own domain, best first. Personal addresses are left out."""
    want = registrable(site_host)
    seen = {}
    for e in EMAIL_RX.findall(deobfuscate(text)):
        e = e.strip(".").lower()
        local, _, dom = e.partition("@")
        role = ROLE_LOCAL.match(local)
        if registrable(dom) != want or SKIP_LOCAL.search(local) or not role:
            continue
        if re.search(r"\.(png|jpg|jpeg|gif|svg|webp)$", dom):
            continue
        seen[e] = min([i for i, k in enumerate(EMAIL_RANK) if role.group(1).startswith(k)], default=99)
    return [e for e, _ in sorted(seen.items(), key=lambda kv: (kv[1], kv[0]))]


# ---------------------------------------------------------------- one call for a whole advert

TRAIN_AND_PLACE = re.compile(r"\b(fdm group|sparta global|grayce|mthree|wiley edge|revature|it career switch|"
                             r"academy programme|train(ing)?[- ]and[- ]place)\b", re.I)


def assess(title, text, location="", fallback_town="", valid_through=None, today=None):
    """Classify one advert. Returns a dict; 'exclude' holds the reason when the advert is not kept."""
    text = clean_text(text)
    out = {"family": None, "level": "", "exclude": None, "is_uk": None, "city": "", "status": "", "closing": None,
           "status_note": "", "visa_note": "", "salary": "", "work_mode": "", "flags": ""}
    fam, why = classify_title(title)
    if not fam:
        out["exclude"] = why
        return out
    out["family"] = fam
    level, why = assess_level(fam, title, text)
    out["level"] = level
    if why:
        out["exclude"] = why
        return out
    is_uk, city = uk_place(location, fallback_town)
    out["is_uk"], out["city"] = is_uk, city
    if is_uk is False:
        out["exclude"] = "Not in the UK"
        return out
    status, closing, note = open_status(text, valid_through, today)
    out["status"], out["closing"], out["status_note"] = status, closing, note
    if status == "Closed":
        out["exclude"] = note
        return out
    out["visa_note"] = visa_note(text)
    if "British nationals only" in out["visa_note"]:
        out["exclude"] = "British nationals only"
        return out
    out["salary"] = salary_of(text)
    out["work_mode"] = work_mode(text, location)
    if TRAIN_AND_PLACE.search(title + " " + text[:3000]):
        out["flags"] = "Train-and-place programme: check any tie-in or repayment clause"
    return out
