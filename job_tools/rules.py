"""Rules for classifying job adverts: role area, level, language, location, pay.

Pure functions only, so they can be tested without network access.
"""
import re
import html as htmlmod

# ---------------------------------------------------------------- text helpers

def clean_text(s):
    """HTML or plain text to a single-spaced plain string."""
    if not s:
        return ""
    s = htmlmod.unescape(str(s))
    s = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = htmlmod.unescape(s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r"\n\s*", "\n", s)
    return s.strip()


DE_WORDS = set("""und der die das mit für wir sie ist ein eine zu von auf bei unser unsere deine dein du ihr
ihre sowie oder nicht auch werden wird sind als nach über durch im ins zum zur dich dir uns unseren unserem
kenntnisse erfahrung aufgaben profil bieten suchen arbeiten deutsch mitarbeiter bereich""".split())
EN_WORDS = set("""and the with for we you is a an to of on at our your as or not also will are by in into
from this that be have has who what experience skills team work role about us offer looking""".split())


def language_of(text):
    """Return ('de'|'en'|'unknown', german_share)."""
    words = re.findall(r"[a-zäöüß]+", (text or "").lower())
    de = sum(1 for w in words if w in DE_WORDS)
    en = sum(1 for w in words if w in EN_WORDS)
    if de + en < 15:
        return "unknown", 0.0
    share = de / (de + en)
    if share >= 0.45:
        return "de", share
    if share <= 0.25:
        return "en", share
    return "mixed", share


# ---------------------------------------------------------------- language rules

GERMAN_PLUS = [
    r"german[^.\n;]{0,60}\b(is a plus|a plus|an advantage|advantageous|nice[- ]to[- ]have|beneficial|a bonus|is a bonus|preferred|desirable|helpful|welcome|would be great|not required|not a must|optional)",
    r"\b(plus|advantage|nice[- ]to[- ]have|bonus|beneficial|desirable)[^.\n;]{0,40}\bgerman\b",
    r"german (language )?skills? (are|is) (a )?(plus|bonus|advantage)",
    r"deutschkenntnisse (sind )?(von vorteil|wünschenswert|ein plus)",
]
GERMAN_REQUIRED = [
    r"\b(fluent|fluency|excellent|very good|good|strong|business[- ]fluent|proficient|proficiency|native|full professional)\b[^.\n;]{0,50}\bgerman\b",
    r"\bgerman\b[^.\n;]{0,40}\b(c1|c2|b2|fluent|fluency|required|mandatory|must|essential|native|business level|is a must)\b",
    r"\b(c1|c2|b2)\b[^.\n;]{0,25}\bgerman\b",
    r"\bgerman and english\b",
    r"\benglish and german\b",
    r"(sehr )?gute deutschkenntnisse",
    r"deutsch(kenntnisse)? (auf |mindestens )?(c1|c2|b2|muttersprach|verhandlungssicher|fließend)",
    r"(fließend|verhandlungssicher)[^.\n;]{0,30}deutsch",
    r"deutsch und englisch",
]
ENGLISH_ONLY = [
    r"(company|working|corporate|office|team|official|business) language is english",
    r"english is (our|the) (company|working|corporate|official|main|primary) language",
    r"(no|without) german (is )?(required|needed|necessary)",
    r"german (is )?not (required|needed|necessary|a requirement)",
    r"english[- ]speaking (team|company|environment|workplace|office)",
    r"we (speak|work in) english",
]
ENGLISH_REQ = [
    r"\b(fluent|fluency|excellent|very good|good|strong|business[- ]fluent|proficient|proficiency)\b[^.\n;]{0,40}\benglish\b",
    r"\benglish\b[^.\n;]{0,30}\b(c1|c2|b2|fluent|required|must)\b",
]


def _find(patterns, text):
    for p in patterns:
        m = re.search(p, text, flags=re.I)
        if m:
            start = max(0, m.start() - 40)
            return text[start:m.end() + 40].replace("\n", " ").strip()
    return None


def assess_language(text):
    """Return (label, evidence). label in:
    'English only', 'German a plus', 'Language not stated', 'German required'."""
    t = clean_text(text)
    lang, share = language_of(t)
    if lang == "de":
        return "German required", "Advert written in German"
    plus = _find(GERMAN_PLUS, t)
    req = _find(GERMAN_REQUIRED, t)
    eo = _find(ENGLISH_ONLY, t)
    if req and re.search(r"\b(no|not|without|kein\w*)\b[^.\n;]{0,20}\b(german|deutsch)|\b(german|deutsch)\w*[^.\n;]{0,20}\bnot\b", req, re.I):
        req = None
    if eo and req and not re.search(r"\b(c1|c2|b2)\b|muttersprach|verhandlungssicher|is a must|mandatory|essential|fluent|fließend", req, re.I):
        req = None
    if req and not plus:
        return "German required", req
    if req and plus:
        # Both matched: the 'plus' phrase usually qualifies the same sentence.
        # Treat as required only if the required phrase names a level.
        if re.search(r"\b(c1|c2|b2)\b|muttersprach|verhandlungssicher|is a must|mandatory|essential", req, re.I):
            return "German required", req
        return "German a plus", plus
    if plus:
        return "German a plus", plus
    if eo:
        return "English only", eo
    er = _find(ENGLISH_REQ, t)
    if er:
        return "English only", er + " (no German requirement found)"
    if lang == "en":
        return "Language not stated", "Advert in English; no language requirement found"
    if lang == "mixed":
        return "German required", "Advert partly in German"
    return "Language not stated", "Short advert; no language requirement found"


# ---------------------------------------------------------------- role area and level

EXCLUDE_TITLE = re.compile(
    r"\b(senior|sr\.?|lead|leiter|leitung|principal|head|director|vp|vice president|chief|staff|"
    r"manager|managerin|expert|experte|architect|medior|mid[- ]?level|"
    r"werkstudent\w*|working student|student|studentische|intern|internship|praktik\w*|praktikant\w*|"
    r"thesis|masterarbeit|bachelorarbeit|abschlussarbeit|trainee|apprentice\w*|ausbildung|azubi|"
    r"dual(es)? stud\w*|duales|freelance\w*|freiberuf\w*|phd|doktorand\w*|postdoc|professor\w*|"
    r"teamlead|team lead|consultant|berater\w*|data engineer|software engineer|devops|"
    r"data entry|data steward|data protection|datenschutz)\b",
    re.I,
)
# "Analytics Engineer" is wanted even though "engineer" rules are strict above.
AREA_PATTERNS = [
    ("Analytics engineer", re.compile(r"analytics engineer", re.I)),
    ("Data scientist", re.compile(r"data scien|decision scien|applied scien|quantitative analyst|quant analyst|statistician|data science", re.I)),
    ("ML engineer", re.compile(r"machine learning|\bml\b|\bmlops\b|\bai engineer|\bki[- ]engineer|deep learning|computer vision|\bnlp\b", re.I)),
    ("BI analyst", re.compile(r"business intelligence|\bbi\b|power bi|reporting analyst|bi[- ]analyst|bi[- ]developer", re.I)),
    ("Data analyst", re.compile(r"data analy|datenanaly|analytics|analyst|insights?", re.I)),
]
JUNIOR_TITLE = re.compile(r"\b(junior|jr\.?|graduate|grad|entry[- ]level|entry|einsteiger|berufseinsteiger\w*|young professional|career starter|new grad|associate|absolvent\w*)\b", re.I)


def area_of(title):
    t = title or ""
    if EXCLUDE_TITLE.search(t) and not re.search(r"analytics engineer", t, re.I):
        return None
    for name, pat in AREA_PATTERNS:
        if pat.search(t):
            if name == "Data analyst" and not re.search(r"data|daten|analytics|business intelligence|\bbi\b|reporting|insight|product analyst|marketing analyst|growth analyst|pricing analyst|revenue analyst|crm analyst|web analyst|digital analyst|quant", t, re.I):
                return None
            return name
    return None


YEARS = re.compile(
    r"(?:(?:at least|minimum( of)?|min\.?|mindestens|over|more than|\b)\s*)"
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:(?:-|–|to|bis)\s*(\d{1,2})\s*)?(?:\+\s*)?"
    r"(?:years?|yrs?|jahre?n?)\b[^.\n;]{0,60}?(?:experience|erfahrung|berufserfahrung|work|professional|relevant|in (?:a|the|data|analytics))",
    re.I,
)


def experience_asked(text):
    """Smallest 'N years' figure that reads like an experience requirement, or None."""
    t = clean_text(text)
    vals = []
    for m in YEARS.finditer(t):
        try:
            lo = int(m.group(2))
        except (TypeError, ValueError):
            continue
        if 0 <= lo <= 15:
            vals.append(lo)
    return min(vals) if vals else None


def assess_level(title, text, seniority_hint=None):
    """Return (label, years) or (None, years) when the role is not graduate or entry level."""
    years = experience_asked(text)
    hint = (seniority_hint or "").lower()
    if "mid-senior" in hint or "director" in hint or "executive" in hint:
        return None, years
    if years is not None and years >= 3:
        return None, years
    if JUNIOR_TITLE.search(title or ""):
        if re.search(r"\bgraduate|absolvent|new grad|berufseinsteiger|career starter", title or "", re.I):
            return "Graduate", years
        return "Junior", years
    if years is not None and years <= 2:
        return "Entry (0-2 years asked)", years
    if "entry" in hint or "associate" in hint:
        return "Entry level (per listing)", years
    if re.search(r"\b(recent graduates?|new graduates?|graduates? (are )?welcome|first (professional|work) experience|"
                 r"no (prior )?experience (is )?(required|needed)|berufseinsteiger|career starters?|"
                 r"0[- ]?(to|-|–)[- ]?[12] years|up to (1|2|two) years)\b", clean_text(text), re.I):
        return "Entry (open to graduates)", years
    return None, years


# ---------------------------------------------------------------- location

DE_CITIES = {
    "Berlin": ["berlin"], "Hamburg": ["hamburg"], "Munich": ["munich", "münchen", "muenchen", "munchen"],
    "Cologne": ["cologne", "köln", "koeln", "koln"], "Frankfurt": ["frankfurt"], "Stuttgart": ["stuttgart"],
    "Düsseldorf": ["düsseldorf", "duesseldorf", "dusseldorf"], "Leipzig": ["leipzig"], "Dortmund": ["dortmund"],
    "Essen": ["essen"], "Bremen": ["bremen"], "Dresden": ["dresden"], "Hanover": ["hanover", "hannover"],
    "Nuremberg": ["nuremberg", "nürnberg", "nuernberg", "nurnberg"], "Duisburg": ["duisburg"],
}
AT_CITIES = {
    "Vienna": ["vienna", "wien"], "Graz": ["graz"], "Linz": ["linz"], "Salzburg": ["salzburg"],
    "Innsbruck": ["innsbruck"], "Klagenfurt": ["klagenfurt"], "Villach": ["villach"], "Wels": ["wels"],
    "St. Pölten": ["st. pölten", "st pölten", "sankt pölten", "st. poelten"], "Dornbirn": ["dornbirn"],
}
DE_MARKERS = ["germany", "deutschland", ", de", "bavaria", "bayern", "baden-württemberg", "hesse", "hessen",
              "north rhine", "nordrhein", "saxony", "sachsen", "lower saxony", "niedersachsen"]
AT_MARKERS = ["austria", "österreich", "oesterreich", ", at", "vienna", "wien", "styria", "steiermark",
              "upper austria", "oberösterreich", "tyrol", "tirol", "carinthia", "kärnten", "vorarlberg"]


def place_of(location):
    """Return (country, city) where country is 'DE', 'AT' or None."""
    loc = (location or "").lower()
    for city, keys in AT_CITIES.items():
        if any(k in loc for k in keys):
            return "AT", city
    for city, keys in DE_CITIES.items():
        if any(re.search(r"(^|[^a-zäöü])" + re.escape(k) + r"($|[^a-zäöü])", loc) for k in keys):
            return "DE", city
    if any(m in loc for m in AT_MARKERS):
        return "AT", "Other"
    if any(m in loc for m in DE_MARKERS):
        return "DE", "Other"
    return None, None


def work_mode(location, text, remote_flag=None, workplace=None):
    blob = " ".join([str(location or ""), str(workplace or "")]).lower()
    t = clean_text(text).lower()
    if workplace:
        w = str(workplace).lower()
        if "remote" in w and "hybrid" not in w:
            return "Remote"
        if "hybrid" in w:
            return "Hybrid"
        if "on" in w and "site" in w or "office" in w:
            return "On-site"
    if remote_flag is True and "hybrid" not in t:
        return "Remote"
    if re.search(r"\bhybrid\b", blob + " " + t[:4000]):
        return "Hybrid"
    if re.search(r"\b(100 ?% remote|fully remote|remote[- ]first|work from anywhere|remote only)\b", blob + " " + t[:4000]):
        return "Remote"
    if re.search(r"\b(on[- ]?site|in the office|vor ort|in our office)\b", blob + " " + t[:4000]):
        return "On-site"
    return "Not stated"


# ---------------------------------------------------------------- pay

MONEY = re.compile(r"(?:€|eur\b|euro\b)\s*([0-9][0-9.,]{3,9})|([0-9][0-9.,]{3,9})\s*(?:€|eur\b|euro\b|euros\b)", re.I)


def money_values(text):
    vals = []
    for m in MONEY.finditer(text or ""):
        raw = m.group(1) or m.group(2)
        num = raw.replace(".", "").replace(",", "")
        if raw.count(",") == 1 and len(raw.split(",")[-1]) == 2:  # 3.500,00 style
            num = raw.split(",")[0].replace(".", "")
        try:
            v = float(num)
        except ValueError:
            continue
        if 1500 <= v <= 200000:
            vals.append(v)
    return vals


def salary_of(text, country):
    """Return (lowest annual figure or None, monthly figure or None, raw snippet)."""
    t = clean_text(text)
    m = re.search(r"[^.\n]{0,80}(?:€|eur\b|euro)[^.\n]{0,80}(?:year|jahr|annual|month|monat|gross|brutto|salary|gehalt)[^.\n]{0,40}"
                  r"|[^.\n]{0,60}(?:salary|gehalt|compensation|brutto|gross)[^.\n]{0,100}(?:€|eur\b|euro)[^.\n]{0,40}", t, re.I)
    if not m:
        return None, None, ""
    snip = m.group(0).strip()
    vals = money_values(snip)
    if not vals:
        return None, None, ""
    low = min(vals)
    monthly = bool(re.search(r"month|monat|monthly|monatlich|/m\b|p\.m\.", snip, re.I)) or low < 9000
    if monthly:
        factor = 14 if country == "AT" else 12
        return low * factor, low, snip[:200]
    return low, None, snip[:200]


def permit_note(country, annual, monthly):
    if country == "DE":
        if annual is None:
            return "Pay not shown: ask. Blue Card needs EUR 45,934.20 a year for career starters (2026)."
        if annual >= 50700:
            return "Pay clears the standard EU Blue Card floor (EUR 50,700)."
        if annual >= 45934.2:
            return "Pay clears the career-starter Blue Card floor (EUR 45,934.20); Federal Employment Agency approval needed."
        return "Pay below the Blue Card floors: skilled-worker permit for graduates (section 18b)."
    if country == "AT":
        if monthly is None and annual is not None:
            monthly = annual / 14
        if monthly is None:
            return "Pay not shown: ask. Key-worker card needs EUR 3,465 a month; Blue Card EUR 55,678 a year (2026)."
        if monthly * 14 >= 55678:
            return "Pay clears the EU Blue Card floor (EUR 55,678 a year); no points or language certificate needed."
        if monthly >= 3465:
            return "Pay clears the key-worker floor (EUR 3,465 a month); needs 55 points, so an English certificate."
        return "Pay below both floors: only the shortage-occupation route (item 34) could work."
    return ""
