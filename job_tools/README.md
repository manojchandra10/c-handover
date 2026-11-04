# Job tools

Scripts that collect live graduate and junior data jobs in Germany and Austria, check each one twice, and write one Excel workbook per country. They need full network access.

Run from the repository root:

```bash
mkdir -p /tmp/jobs_data
python3 -I job_tools/collect.py /tmp/jobs_data
python3 -I job_tools/verify.py /tmp/jobs_data
python3 -I job_tools/build_xlsx.py /tmp/jobs_data . "4 November 2026"
```

- `collect.py` pulls listings from LinkedIn's public job search, Arbeitnow, the German Federal Employment Agency, company hiring boards (Greenhouse, Lever, Ashby, Personio, SmartRecruiters, Recruitee), karriere.at, devjobs, Berlin Startup Jobs and GermanTechJobs. Pass source names after the data folder to run only some of them.
- `verify.py` applies the rules in `rules.py` (role area, level, language, location, work mode), removes duplicates, then re-opens every kept advert and drops any that are closed.
- `build_xlsx.py` writes `Austria_Data_Jobs.xlsx` and `Germany_Data_Jobs.xlsx`. Run the xlsx skill's `recalc.py` on each afterwards so the count formulas have values.

## UK: sponsor career pages

These scripts work through the Home Office register of licensed sponsors (`uk_data/sponsor_register_2026-11-03.csv`, 143,064 rows). They keep Skilled Worker sponsors in finance, banking, investment, consulting, data, government, universities and research. Each company's own careers page and hiring system is then checked for live graduate and entry-level data roles. Role-based recruitment emails are collected for companies with nothing open. They need a session with full network access.

```bash
python3 -I job_tools/uk_shortlist.py uk_data/sponsor_register_2026-11-03.csv uk_data/uk_shortlist.csv
python3 -I job_tools/uk_sic.py uk_data/sponsor_register_2026-11-03.csv uk_data/uk_shortlist.csv uk_data/uk_shortlist_sic.csv
mkdir -p /tmp/uk_data
nohup python3 -I job_tools/uk_crawl.py uk_data/uk_shortlist_sic.csv /tmp/uk_data --tiers A,B --workers 12 > /tmp/uk_data/run.out 2>&1 &
python3 -I job_tools/uk_crawl.py uk_data/uk_shortlist_sic.csv /tmp/uk_data --tiers C --sources careers --workers 12
python3 -I job_tools/uk_verify.py /tmp/uk_data
python3 -I job_tools/uk_build.py /tmp/uk_data . --label "5 November 2026"
```

- `uk_shortlist.py` classifies every Skilled Worker sponsor by name. It drops names ending in "AI", plus restaurants, cafes, warehouses and other out-of-scope firms, and gives each company a priority tier (A, B or C). The current shortlist has 7,486 companies: 2,258 in tier A, 1,796 in B and 3,432 in C.
- `uk_sic.py` is optional. It downloads the free Companies House bulk file (about 470 MB) and adds sponsors whose industry code fits, even when the name has no sector word.
- `uk_crawl.py` finds each website (known domains, then guessed domains accepted only when the company name is on the page). It reads the careers pages, any linked hiring system (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Personio, Pinpoint, BambooHR, Breezy, Teamtailor, Workday, Oracle, Eightfold) and schema.org job data. It also searches jobs.ac.uk, the Civil Service Analysis Function vacancy list and DWP Find a job. It respects robots.txt, spaces out requests to each host and resumes where it stopped. Progress goes to `/tmp/uk_data/crawl.log`.
- `uk_verify.py` re-opens every kept advert in a separate request, drops any that have closed and removes duplicates.
- `uk_build.py` writes `UK_Data_Jobs.xlsx` (Jobs, Other live roles, Excluded, Companies checked) and `UK_Speculative_Contacts.xlsx` (Contacts, No email found, and the email text). Run the xlsx skill's `recalc.py` on both afterwards.
- `uk_rules.py` holds the title, level, location, deadline, visa-note and email rules. `uk_test.py` and `uk_test_e2e.py` test them offline. The second test runs the whole pipeline against a local web server.
