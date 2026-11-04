#!/usr/bin/env python3
"""Filter the UK register of licensed sponsors to the user's sectors.

Usage: python3 -I uk_shortlist.py <register.csv> <out.csv>

Reads every row of the register, keeps Skilled Worker sponsors whose names point to finance, banking,
investment, consulting, data, government, universities or research, and gives each a priority tier:
  A  universities, research institutes, government bodies, banks, insurers, asset managers, data firms,
     economics consultancies and well-known employers in these fields
  B  other consultancies, advisers, fintech, lenders, brokers, wealth managers, local councils
  C  small accountancy and tax practices, and names with only a weak finance word (for example "Investments Ltd")
Sponsors with a B rating drop one tier. Names that end in "AI", and food, hospitality, warehouse, care,
property, construction and similar firms are dropped. The register has no websites or industry codes,
so this is a name-based first pass. uk_sic.py can add Companies House industry codes in a networked session.
"""
import sys, re
import pandas as pd

LEGAL_SUFFIX = re.compile(r"[\s,.]*\b(ltd|limited|llp|plc|inc|lp|l\.l\.p|uk|u\.k|group|holdings?|co|company|the|"
                          r"international|services|solutions|europe|global)\b\.?[\s,.]*$")

def strip_legal(name):
    s = re.sub(r"\(.*?\)", " ", name.lower()).strip()
    for _ in range(4):
        s = LEGAL_SUFFIX.sub("", s).strip()
    return s

def ends_with_ai(name):
    return bool(re.search(r"(^|[\s\-.])ai$", strip_legal(name)))

# Known employers in the user's sectors (word-boundary patterns, matched on the lower-case name).
BRANDS = {
    "Consulting": [r"\bdeloitte\b", r"\bpricewaterhousecoopers\b", r"\bernst & young\b", r"\bkpmg llp\b", r"\baccenture\b",
                   r"\bmckinsey\b", r"\bboston consulting\b", r"\bbain & company\b", r"\boliver wyman\b", r"\bcapgemini\b",
                   r"\bgrant thornton\b", r"^bdo llp$", r"\bforvis mazars\b", r"^rsm (uk|international)\b", r"\bbaringa\b",
                   r"\bkubrick group\b", r"\bfrontier economics\b", r"\boxera\b", r"\blane clark\b", r"\bhymans robertson\b",
                   r"^mercer (ltd|limited|risk)", r"^aon uk\b", r"\ba t kearney\b", r"\bcapital markets company\b",
                   r"\bslalom consulting\b", r"\bcredera\b", r"\bjman group\b", r"\bgerson lehrman\b", r"\bl\.?e\.?k\.? consulting\b",
                   r"\balvarez & marsal\b", r"\bfti consulting\b", r"\bprotiviti\b", r"\bcrowe u\.?k\b", r"\bazets\b",
                   r"\bnewton europe\b", r"\belixirr\b", r"\bsimon-kucher\b", r"\broland berger\b", r"\bpa consulting\b",
                   r"\bthoughtworks\b", r"\bnera economic\b", r"\bcambridge econometrics\b", r"\beurope economics\b",
                   r"\bcopenhagen economics\b", r"\balma economics\b", r"\bcepa\b", r"\bbarnett waddingham\b", r"\bisio\b",
                   r"\bxps pensions\b", r"\bwillis towers watson\b", r"\bmott macdonald\b", r"\bsia partners\b"],
    "Data":       [r"\bexperian\b", r"\bequifax\b", r"\btransunion\b", r"\bdunnhumby\b", r"\bkantar\b", r"\bipsos\b", r"\byougov\b",
                   r"\ba\.?c\.? ?nielsen\b", r"\bnielsen media\b", r"\bcircana\b", r"\biqvia\b", r"\bpalantir\b", r"\bdatabricks\b",
                   r"\bsnowflake computing\b", r"\bbloomberg\b", r"\blondon stock exchange\b", r"\bfactset\b", r"^msci\b",
                   r"\bmoody'?s\b", r"\bs&p global\b", r"\bfitch ratings\b", r"\bmorningstar\b", r"\bclear ?score\b", r"\bquantexa\b",
                   r"\belsevier\b", r"\brelx\b", r"\blexisnexis\b", r"\bwood mackenzie\b", r"\boxford economics\b",
                   r"\bcapital economics\b", r"\bverisk\b", r"\bfaculty science\b", r"\bsagacity\b"],
    "Banking":    [r"^barclays\b", r"^hsbc\b", r"\blloyds bank", r"\blloyds banking\b", r"\bnatwest\b", r"\bsantander\b",
                   r"\bmonzo\b", r"\bstarling bank\b", r"^revolut\b", r"\bmetro bank\b", r"\bvirgin money\b",
                   r"\bnationwide building society\b", r"^tsb bank\b", r"\bgoldman sachs\b", r"\bmorgan stanley\b",
                   r"\bjpmorgan\b|\bj\.? ?p\.? ?morgan\b", r"\bcitigroup\b|\bcitibank\b", r"\bdeutsche bank\b", r"^ubs\b",
                   r"\bbnp paribas\b", r"\bsociete generale\b", r"\bnomura\b", r"\bmizuho\b", r"\bmufg\b", r"\bstandard chartered\b",
                   r"^jefferies\b", r"\blazard\b", r"\brothschild\b", r"\bevercore\b", r"\bmacquarie\b", r"\binvestec\b",
                   r"\bclose brothers\b", r"\boaknorth\b", r"\batom bank\b", r"\bzopa\b", r"\ballica bank\b", r"^wise payments\b",
                   r"^checkout ltd$", r"\bgocardless\b", r"\bfunding circle\b", r"\bcapital one \(europe\)", r"\bbank of england\b"],
    "Investment": [r"\bblackrock investment\b", r"\bschroder", r"\babrdn\b", r"\blegal & general\b", r"\bm&g\b", r"^aviva plc$",
                   r"\bprudential\b", r"\bhargreaves lansdown\b", r"^man group\b", r"\bjane street\b", r"\bcitadel enterprise\b",
                   r"\btwo sigma\b", r"\bg-research\b", r"\bwinton (capital|group)\b", r"\bpoint72\b", r"\bmillennium capital\b", r"\bbalyasny\b",
                   r"\bbrevan howard\b", r"\bmarshall wace\b", r"\bfidelity international\b|\bfil investment", r"\bvanguard asset\b", r"\binvesco\b",
                   r"\bbaillie gifford\b", r"\bruffer\b", r"\bjupiter asset\b", r"\bliontrust\b", r"\brathbones?\b", r"\bquilter\b",
                   r"\bst\.? james'?s place\b", r"\bbain capital\b", r"\bdimensional fund\b", r"\bpimco\b", r"\binsight investment\b",
                   r"\bcolumbia threadneedle\b", r"\bhiscox\b", r"\bbeazley\b", r"\bzurich (insurance|assurance|management)\b", r"\ballianz\b", r"^eui limited$",
                   r"\bhastings insurance\b", r"\bdirect line\b", r"\bsimply business\b", r"\bswiss re\b", r"\bmunich re\b",
                   r"^marsh (ltd|limited)\b", r"\bmarsh mclennan\b", r"\barthur j\.? gallagher\b", r"\bhowden (insurance|group|broking)\b",
                   r"^drw\b", r"\boptiver\b", r"^imc\b", r"\bflow traders\b", r"\bsusquehanna\b", r"\bhudson river trading\b", r"\bxtx markets\b",
                   r"\bqube research\b", r"\bsquarepoint\b", r"\bmaven securities\b", r"\btower research\b", r"\bjump trading\b", r"\bschonfeld\b",
                   r"\bcapula\b", r"\brokos\b", r"\btudor capital\b", r"\bcitadel securities\b", r"\bmillennium (capital|global|management)\b"],
}

# Public bodies: kept even when another rule would drop them.
GOV_BODIES = [r"\boffice for national statistics\b", r"\bhm revenue\b", r"^department (for|of)\b", r"^ministry of (defence|justice|housing)",
              r"^cabinet office$", r"^hm treasury$", r"\bfinancial conduct authority\b", r"\bcompetition and markets authority\b",
              r"^met office$", r"^ordnance survey\b", r"\buk health security agency\b", r"^environment agency$",
              r"^food standards (agency|scotland)$", r"^nhs england$", r"\bnhs business services authority\b", r"^scottish government$",
              r"^welsh government$", r"\bgreater london authority\b", r"^transport for london$", r"\boffice of rail and road\b",
              r"^ofcom$", r"\(ofwat\)", r"\binformation commissioner", r"^civil aviation authority$", r"\buk research and innovation\b",
              r"\bnational audit office\b", r"\bgovernment actuary", r"^companies house$", r"^hm land registry$", r"^audit scotland$",
              r"\belectoral commission\b", r"\bcare quality commission\b", r"\bfinancial reporting council\b", r"\bnatural england\b",
              r"\bhealth and safety executive\b", r"\bprudential regulation\b", r"\bpensions regulator\b", r"\bgambling commission\b",
              r"\bofgem\b", r"\bpublic health scotland\b", r"\bnhs national services scotland\b", r"\bnorthern ireland civil service\b",
              r"\b(borough|city|county|district|metropolitan borough|town) council\b", r"^(the )?council of\b", r"\bcombined authority\b",
              r"\bunited kingdom atomic energy authority\b", r"\bnuclear decommissioning authority\b", r"\bsolicitors regulation authority\b"]
RESEARCH_BODIES = [r"\balan turing institute\b", r"\bfrancis crick institute\b", r"\binstitute for fiscal studies\b", r"\bresolution foundation\b",
                   r"\bnuffield (foundation|trust)\b", r"\bwellcome trust\b", r"^cancer research uk$", r"\binstitute of cancer research\b",
                   r"\bnational institute of economic and social research\b", r"\binstitute for strategic studies\b",
                   r"\binstitute and faculty of actuaries\b", r"\bwellcome sanger\b", r"\brothamsted\b", r"\bjohn innes\b",
                   r"\bearlham institute\b", r"\bbabraham\b", r"\bnatcen\b", r"\bnational centre for social research\b",
                   r"\binstitute for government\b", r"\bcentre for cities\b", r"\bhealth foundation\b$", r"\bking'?s fund\b"]

SECTORS = [
    ("University", r"\buniversit(y|ies)\b|\bschool of (economics|business|hygiene|oriental|advanced study)|\bbusiness school\b|"
                   r"\bimperial college london\b|\bking'?s college london\b|\buniversity college\b|\bbirkbeck\b|\bcourtauld institute\b|"
                   r"\bcollege of (art|music)\b|\broyal veterinary college\b|\bcranfield\b"),
    ("Research",   r"\bresearch\b|\blaborator(y|ies)\b|\blabs\b|\binstitute\b|\bscientific\b|\bcentre for\b|\bcenter for\b|\bobservatory\b|"
                   r"\bthink tank\b|\bfoundation for\b|\bpolicy\b"),
    ("Government", r"\bgovernment\b|\bregulator\b|\bombudsman\b|\bparliament\b"),
    ("Banking",    r"\bbank\b|\bbanking\b|\bbancorp\b|\bbuilding society\b|\bcredit union\b|\bbanque\b|\bbanco\b|\bbanca\b"),
    ("Investment", r"\binvestment (management|managers|partners|bank|banking|advis|office|trust|company)|\binvestments? llp\b|"
                   r"\binvestors\b|\bcapital\b|\basset management\b|\bassets\b|\bwealth\b|\bfunds?\b|\bequity\b|\bsecurities\b|"
                   r"\bhedge\b|\bportfolio\b|\bprivate markets\b|\bfamily office\b|\bpensions?\b|\breal estate investment\b|"
                   r"\b(proprietary|systematic|algorithmic|commodit\w*|energy|securities|derivatives|fx) trading\b|\btrading (partners|advisors|advisers)\b|"
                   r"\bmarkets (ltd|limited|llp|uk|europe|plc)\b|\bcapital markets\b|\binvest(ments?)?\b|\bventures (llp|partners)\b|"
                   r"\bventure (capital|partners)\b"),
    ("Finance",    r"\bfinanc|\bfintech\b|\bpayments?\b|\blending\b|\bloans?\b|\bmortgages?\b|\binsurance\b|\binsurer|\breinsurance\b|"
                   r"\bunderwrit|\bactuar|\baccountan|\bchartered accountants\b|\baudit\b|\bauditors\b|\btax\b|\bleasing\b|\bcredit\b|"
                   r"\bclearing\b|\bmanaging agency\b|\bforex\b|\bfx\b|\bbrokers?\b|\bbrokerage\b|\btreasury\b|\bfactoring\b|\bmoney\b"),
    ("Consulting", r"\bconsult|\badvis[oe]r|\badvisory\b|\bstrategy\b|\bstrategic\b|\beconomics?\b|\beconomists?\b|\beconometric"),
    ("Data",       r"\bdata\b|\banalytics?\b|\banalysis\b|\bstatistic|\binsights?\b|\bintelligence\b|\bmetrics\b|\bdecision science|"
                   r"\bforecast|\bquant(s|itative)?\b|\bbig data\b|\bdatalab\b|\bmachine learning\b"),
]

# Hard exclusions: the user's own list (restaurants, cafes, warehouses) plus food, hospitality and care firms.
HARD_EXCLUDE = re.compile(
    r"\brestaurant|\bcaf[eé]s?\b|\bcoffee\b|\bkitchens?\b|\bgrill\b|\btakeaway\b|\bpizz|\bcurry\b|\bkebab\b|\bbistro\b|\bbrasserie\b|"
    r"\bdiner\b|\bbaker(y|s)?\b|\bcatering\b|\bfoods?\b|\bpub\b|\btavern\b|\binn\b|\bbar\b|\bhotels?\b|\bwarehous|\bcare homes?\b|"
    r"\bcarers\b|\bnursing\b|\bhome ?care\b|\bdomiciliary\b|\bsupported living\b|\bsupermarket|\bconvenience\b|\bbutchers?\b|"
    r"\bspices?\b|\btandoori\b|\bsweets?\b|\bdesserts?\b|\bhospitality\b|\bweddings?\b|\bt/as?\b|\btrading as\b|\bmoney transfer\b|"
    r"\bremittance\b|\bbureau de change\b|\bpawn|\bdental\b|\bdentist|\bclubs?\b|\bfish\b|\bchips\b|\bhigh commission\b|\bembassy\b|\bconsulate\b|\bstudents'? union\b|\bnhs (foundation )?trust\b")
# Soft exclusions: other industries. A data, research or analytics word in the name overrides these.
SOFT_EXCLUDE = re.compile(
    r"\bstorage\b|\bcare\b|\bconstruction\b|\bbuilders?\b|\bbuilding (services|contractors|maintenance)\b|\broofing\b|\bplumb|"
    r"\belectrical\b|\bcleaning\b|\bcleaners\b|\bcars\b|\bmotors?\b|\bautos?\b|\bautomotive\b|\bgarage\b|\btaxis?\b|\btransport\b|"
    r"\blogistics\b|\bhaulage\b|\bremovals\b|\bcouriers?\b|\btravels?\b|\btours\b|\bbeauty\b|\bsalon\b|\bhair\b|\bbarbers?\b|\bnails\b|"
    r"\bspa\b|\bfashion\b|\bclothing\b|\btextiles?\b|\bjewell?(ery|ers)\b|\bflorist|\bfurniture\b|\binteriors\b|\bproperty\b|"
    r"\bproperties\b|\bestates?\b|\blettings?\b|\bhomes\b|\bhousing\b|\bdental\b|\bdentist|\bpharmac|\bchemists?\b|\bclinics?\b|"
    r"\bsurgery\b|\bvets?\b|\bveterinary\b|\bnursery\b|\bchildcare\b|\btuition\b|\btutors?\b|\bdriving\b|\bsecurity services\b|"
    r"\bguarding\b|\brecruitment\b|\bstaffing\b|\bevents\b|\bfilms?\b|\bmusic\b|\bsports?\b|\bfitness\b|\bgym\b|\bchurch\b|\bmosque\b|"
    r"\btemple\b|\bgurdwara\b|\bfarms?\b|\bprinting\b|\bpackaging\b|\bimmigration\b|\bvisas?\b|\bstudy abroad\b|\boverseas education\b|"
    r"\beducation consultan|\bsolicitors\b|\blaw\b|\blegal\b|\bhospitals?\b|\bcash\b|\bjanitorial\b|\bfacilities management\b|"
    r"\bscaffold|\bshopfit|\bdecorat|\bglazing\b|\bcarpet|\btiles?\b|\bbathrooms?\b|\bfreight\b|\bshipping\b|\bmarine\b|\boffshore\b|\bfishing\b|"
    r"\btrawlers?\b|\bfuels?\b|\bpetrol\b|\bretail(ers)?\b|\bstores?\b|\bshops?\b|\bmart\b|\bbazaar\b|\bwholesale\b|\bimport|\bexport|"
    r"\bgeneral trading\b|\btrading (ltd|limited|co|company|uk)\b|\bmedical centre\b|\bhealth ?care\b|\bdomestic\b|\bphotograph|"
    r"\bcinema\b|\btheatre\b|\bdance\b|\bmodel(s|ling)\b")
OVERRIDE_SOFT = re.compile(r"\buniversit|\bcollege london\b|\bschool of\b|\bresearch\b|\banalytics?\b|\bdata\b|\bstatistic|\binsights?\b|"
                           r"\bintelligence\b|\beconomics?\b|\binstitute\b|\bquant(s|itative)?\b|\bactuar")

ACCOUNTANCY = re.compile(r"\baccountan|\bchartered accountants\b|\btax\b|\bbookkeep|\bpayroll\b|\bauditors\b")
WEAK_ONLY = re.compile(r"^(?:[\w&.'-]+\s){0,3}(investments?|capital|financial services|finance|consult(ing|ancy|ants?)|advisory|ventures)"
                       r"(\s(ltd|limited|uk|group|llp))*\.?$")

TIER_A_SECTORS = {"University", "Research", "Government", "Banking", "Data"}
STRONG_A = re.compile(r"\binsurance\b|\breinsurance\b|\binsurer|\bunderwrit|\bactuar|\basset management\b|\binvestment management\b|"
                      r"\bfund management\b|\bcapital management\b|\bpartners llp\b|\bsecurities\b|\bcapital markets\b|\beconomics?\b|"
                      r"\beconometric|\bresearch\b|\banalytics\b|\bstatistic|\bquant")

def sector_of(low):
    hits = []
    for pat in GOV_BODIES:
        if re.search(pat, low):
            hits.append("Government"); break
    for pat in RESEARCH_BODIES:
        if re.search(pat, low):
            hits.append("Research"); break
    for sec, pats in BRANDS.items():
        if any(re.search(p, low) for p in pats) and sec not in hits:
            hits.append(sec)
    for sec, pat in SECTORS:
        if sec not in hits and re.search(pat, low):
            hits.append(sec)
    return hits

WEAK_RESEARCH = re.compile(r"\bresearch\b|\blaborator|\binstitute\b|\bcentre for\b|\bcenter for\b|\bobservatory\b|\bthink tank\b")

def tier_of(low, secs, rating, whitelisted):
    if secs[0] == "Research" and not whitelisted and not WEAK_RESEARCH.search(low):
        t = "B"   # only "labs", "policy" or "scientific" in the name
    elif whitelisted or secs[0] in TIER_A_SECTORS or STRONG_A.search(low):
        t = "A"
    elif ACCOUNTANCY.search(low) or WEAK_ONLY.match(strip_legal(low) + " ltd"):
        t = "C"
    else:
        t = "B"
    if "B rating" in rating or "B (" in rating:
        t = {"A": "B", "B": "C", "C": "C"}[t]
    return t

def main(src, out):
    df = pd.read_csv(src, dtype=str, keep_default_na=False)
    total_rows = len(df)
    for c in df.columns:
        df[c] = df[c].str.strip()
    sw = df[df["Route"] == "Skilled Worker"].drop_duplicates(subset=["Organisation Name", "Town/City"])
    rows, n_ai, n_excl = [], 0, 0
    for _, r in sw.iterrows():
        name = r["Organisation Name"]
        low = " ".join(name.lower().split())
        if ends_with_ai(name):
            n_ai += 1
            continue
        public = any(re.search(p, low) for p in GOV_BODIES + RESEARCH_BODIES)
        whitelisted = public or any(re.search(p, low) for pats in BRANDS.values() for p in pats)
        if (not public and HARD_EXCLUDE.search(low)) or \
           (not whitelisted and SOFT_EXCLUDE.search(low) and not OVERRIDE_SOFT.search(low)):
            n_excl += 1
            continue
        secs = sector_of(low)
        if not secs:
            continue
        if secs[0] == "Government" and re.search(r"\b(borough|city|county|district|town) council\b|\bcombined authority\b", low):
            secs[0] = "Local government"
        rows.append({"Organisation": name, "Town/City": r["Town/City"].title(), "County": r["County"].title(),
                     "Licence rating": r["Type & Rating"], "Primary sector": secs[0], "All sectors": "; ".join(secs),
                     "Priority": tier_of(low, secs, r["Type & Rating"], whitelisted),
                     "Known employer": "Yes" if whitelisted else ""})
    res = pd.DataFrame(rows)
    order = {"A": 0, "B": 1, "C": 2}
    res = res.sort_values(by=["Priority", "Primary sector", "Organisation"], key=lambda s: s.map(order) if s.name == "Priority" else s.str.lower())
    res.to_csv(out, index=False)
    print("Register rows read:", total_rows)
    print("Skilled Worker organisations (unique name and town):", len(sw))
    print("Dropped, name ends in AI:", n_ai)
    print("Dropped, food, hospitality, warehouse, care, property and similar:", n_excl)
    print("Shortlisted:", len(res))
    print(pd.crosstab(res["Primary sector"], res["Priority"], margins=True).to_string())
    print("Top towns:\n" + res["Town/City"].value_counts().head(15).to_string())

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
