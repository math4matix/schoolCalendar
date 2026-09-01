# schoolcalendar

Pulls your lesson plan out of MobiDziennik (including cancellations/substitutions)
and publishes it as a subscribable `.ics` feed for Apple Calendar / Google Calendar.

MobiDziennik has no official API — this scrapes the same login and timetable
HTML endpoints used by the open-source clients
[szkolny-android](https://github.com/szkolny-eu/szkolny-android) and
[MobidziennikSDK](https://github.com/Norbiros/MobidziennikSDK). If MobiDziennik
changes its page layout, the parser in `scraper/mobidziennik.py` will need
updating.

## How it works

1. `scraper/mobidziennik.py` logs into `https://<school_id>.mobidziennik.pl`
   and parses `/dziennik/planlekcji` (the lesson-plan page) for the current
   and next week, extracting subject/teacher/room/time and whether each
   lesson is normal, a substitution, or cancelled.
2. `generate_ics.py` turns those lessons into an `.ics` file at
   `docs/<ICS_TOKEN>.ics`. Cancelled lessons stay in the feed with
   `STATUS:CANCELLED` so they show up (crossed out) instead of just vanishing.
3. `.github/workflows/sync.yml` runs this once a day via GitHub Actions and
   commits the updated feed. GitHub Pages serves `docs/`, so the feed is
   reachable at:

   ```
   https://<your-github-username>.github.io/schoolcalendar/<ICS_TOKEN>.ics
   ```

## Setup

1. **Find your school ID**: it's the subdomain you use to log into MobiDziennik,
   e.g. if you log in at `https://przyklad.mobidziennik.pl`, your school ID is
   `przyklad`.

2. **Pick an ICS_TOKEN**: a long random string (e.g. `python3 -c "import secrets; print(secrets.token_urlsafe(24))"`).
   This is *not encryption* — subscribed calendar URLs can't carry auth, so the
   token is the only thing standing between "anyone with the link" and your
   schedule. Don't post it publicly.

3. **Enable GitHub Pages** on this repo: Settings → Pages → Deploy from branch →
   branch `main`, folder `/docs`.

4. **Add repo secrets** (Settings → Secrets and variables → Actions):
   - `MOBIDZIENNIK_SCHOOL_ID`
   - `MOBIDZIENNIK_USER`
   - `MOBIDZIENNIK_PASS`
   - `ICS_TOKEN`

5. **Run the workflow once manually** (Actions → Sync MobiDziennik to calendar
   feed → Run workflow) to generate the first feed file.

6. **Subscribe to the feed**:
   - **Apple Calendar**: File → New Calendar Subscription → paste the feed URL.
   - **Google Calendar**: Other calendars (+) → From URL → paste the feed URL.

Both platforms poll the URL on their own schedule (Apple: every few hours,
Google: roughly once a day) — no push integration needed.

## Local development

```bash
cp .env.example .env   # fill in real values
pip install -r requirements.txt
export $(grep -v '^#' .env | xargs)
python generate_ics.py
```

This writes `docs/<ICS_TOKEN>.ics` locally — open it in Calendar.app or
validate it with any `.ics` viewer.
