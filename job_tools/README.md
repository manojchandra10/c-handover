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
