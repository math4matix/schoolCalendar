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
3. A systemd timer on the VPS (`schoolcalendar-sync.timer`, 04:00 Europe/Warsaw
   daily) runs `sync.sh`, which does the above and commits + pushes the
   updated feed. GitHub Pages serves `docs/`, so the feed is reachable at:

   ```
   https://<your-github-username>.github.io/schoolcalendar/<ICS_TOKEN>.ics
   ```

   This used to run on GitHub Actions, but the school's MobiDziennik instance
   sits behind Cloudflare, which blocks GitHub Actions' runner IPs (403 on
   login) — the exact same code works fine from a non-datacenter IP, so the
   sync now runs from the VPS instead.

## Setup

1. **Find your school ID**: it's the subdomain you use to log into MobiDziennik,
   e.g. if you log in at `https://przyklad.mobidziennik.pl`, your school ID is
   `przyklad`.

2. **Pick an ICS_TOKEN**: a long random string (e.g. `python3 -c "import secrets; print(secrets.token_urlsafe(24))"`).
   This is *not encryption* — subscribed calendar URLs can't carry auth, so the
   token is the only thing standing between "anyone with the link" and your
   schedule. Don't post it publicly.

3. **Enable GitHub Pages** on this repo: Settings → Pages → Deploy from branch →
   branch `master`, folder `/docs`.

4. **Set up the sync host** (currently a VPS, not GitHub Actions — see note
   above):
   - Clone the repo, create a venv, `pip install -r requirements.txt`.
   - Fill in `.env` (`cp .env.example .env`) with `MOBIDZIENNIK_SCHOOL_ID`,
     `MOBIDZIENNIK_USER`, `MOBIDZIENNIK_PASS`, `ICS_TOKEN`; `chmod 600 .env`.
   - Push access needs its own credentials — this repo uses a repo-scoped SSH
     deploy key (write access) rather than a personal token, with an
     `~/.ssh/config` `Host` alias pointing `git@<alias>` at that key, and the
     `origin` remote set to `git@<alias>:<owner>/<repo>.git`.
   - Install `schoolcalendar-sync.service` + `schoolcalendar-sync.timer` in
     `/etc/systemd/system/` (`Type=oneshot`, `EnvironmentFile=.env`,
     `ExecStart=sync.sh`; timer `OnCalendar=*-*-* 04:00:00 Europe/Warsaw`),
     then `systemctl daemon-reload && systemctl enable --now schoolcalendar-sync.timer`.

5. **Run it once manually** (`systemctl start schoolcalendar-sync.service`, or
   just `./sync.sh` locally) to generate the first feed file.

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
