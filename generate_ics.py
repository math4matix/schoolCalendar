"""Fetch the MobiDziennik lesson plan and write it out as an .ics feed."""
from __future__ import annotations

import hashlib
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event
from icalendar.prop import vText

from scraper.mobidziennik import Lesson, LessonType, MobidziennikClient, week_start

TZ = ZoneInfo("Europe/Warsaw")
WEEKS_AHEAD = 2  # current week + next week
WEEKS_BEHIND = 0


def build_uid(lesson: Lesson, school_id: str) -> str:
    key = f"{lesson.date.isoformat()}-{lesson.lesson_number}-{lesson.subject}-{lesson.team or ''}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"{digest}@{school_id}.mobidziennik-calendar"


def lesson_to_event(lesson: Lesson, school_id: str) -> Event:
    event = Event()
    event.add("uid", build_uid(lesson, school_id))
    event.add("dtstart", lesson.start_dt.replace(tzinfo=TZ))
    event.add("dtend", lesson.end_dt.replace(tzinfo=TZ))
    event.add("dtstamp", lesson.start_dt.replace(tzinfo=TZ))

    subject = lesson.subject or "Lekcja"
    if lesson.type == LessonType.CANCELLED:
        event.add("summary", f"ODWOŁANE: {subject}")
        event.add("status", "CANCELLED")
    elif lesson.type == LessonType.CHANGE:
        event.add("summary", f"ZASTĘPSTWO: {subject}")
        event.add("status", "CONFIRMED")
    else:
        event.add("summary", subject)
        event.add("status", "CONFIRMED")

    if lesson.classroom:
        event.add("location", vText(lesson.classroom))

    description_lines = []
    if lesson.teacher:
        description_lines.append(f"Nauczyciel: {lesson.teacher}")
    if lesson.team:
        description_lines.append(f"Klasa/grupa: {lesson.team}")
    if lesson.lesson_number is not None:
        description_lines.append(f"Numer lekcji: {lesson.lesson_number}")
    if description_lines:
        event.add("description", "\n".join(description_lines))

    return event


def fetch_all_lessons(client: MobidziennikClient) -> list[Lesson]:
    today = date.today()
    start = week_start(today) - timedelta(weeks=WEEKS_BEHIND)
    all_lessons: list[Lesson] = []
    seen_dates_weeks = set()
    for i in range(WEEKS_BEHIND + WEEKS_AHEAD):
        w = start + timedelta(weeks=i)
        if w in seen_dates_weeks:
            continue
        seen_dates_weeks.add(w)
        all_lessons.extend(client.get_lessons(w))
    return all_lessons


def main() -> int:
    school_id = os.environ["MOBIDZIENNIK_SCHOOL_ID"]
    username = os.environ["MOBIDZIENNIK_USER"]
    password = os.environ["MOBIDZIENNIK_PASS"]
    ics_token = os.environ["ICS_TOKEN"]
    output_dir = Path(os.environ.get("ICS_OUTPUT_DIR", "docs"))

    client = MobidziennikClient(school_id)
    client.login(username, password)
    lessons = fetch_all_lessons(client)

    if not lessons:
        print("No lessons parsed — MobiDziennik page layout may have changed.", file=sys.stderr)
        return 1

    cal = Calendar()
    cal.add("prodid", "-//schoolcalendar//mobidziennik-sync//PL")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "Plan lekcji")
    cal.add("x-wr-timezone", "Europe/Warsaw")
    cal.add("method", "PUBLISH")

    for lesson in lessons:
        cal.add_component(lesson_to_event(lesson, school_id))

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{ics_token}.ics"
    out_path.write_bytes(cal.to_ical())
    print(f"Wrote {len(lessons)} lessons to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
