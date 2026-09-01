"""Unofficial MobiDziennik web scraper.

MobiDziennik has no public API. This replicates the login flow and the
lesson-plan ("planlekcji") HTML parsing used by the reference open-source
clients szkolny-android (github.com/szkolny-eu/szkolny-android) and
MobidziennikSDK (github.com/Norbiros/MobidziennikSDK). The timetable page
renders lessons as absolutely-positioned <div>s inside a CSS grid, so the
date/time of each lesson has to be reconstructed from pixel-percentage
positions rather than read directly off the cell.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum

import requests
from bs4 import BeautifulSoup

MONTHS_PL = [
    "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
    "lipca", "sierpnia", "września", "października", "listopada", "grudnia",
]

# Matches the header row that maps horizontal position -> day of week.
RE_TIMETABLE_TOP = re.compile(r'<div class="plansc_top">.+?</div></div>', re.DOTALL)
# Matches the left-hand column that maps vertical position -> lesson hour.
RE_TIMETABLE_LEFT = re.compile(r'<div class="plansc_godz">.+?</div></div>', re.DOTALL)
# Matches each lesson cell: outer style, inner style, title (full date), inner content.
RE_TIMETABLE_CELL = re.compile(
    r'<div class="plansc_cnt_w" style="(.+?)">.+?style="(.+?)".+?title="(.+?)".+?>\s+(.+?)\s+</div>',
    re.DOTALL,
)

CLASSROOM_RE = re.compile(r"\((.*)\)")


class LessonType(Enum):
    NORMAL = "normal"
    CHANGE = "change"          # zastępstwo (substitution)
    CANCELLED = "cancelled"    # lekcja odwołana


@dataclass
class Lesson:
    date: date
    start: time
    end: time
    lesson_number: int | None
    subject: str | None
    teacher: str | None
    classroom: str | None
    team: str | None
    type: LessonType

    @property
    def start_dt(self) -> datetime:
        return datetime.combine(self.date, self.start)

    @property
    def end_dt(self) -> datetime:
        return datetime.combine(self.date, self.end)


class MobidziennikError(RuntimeError):
    pass


def _parse_css(style: str) -> dict[str, str]:
    result = {}
    for chunk in style.split(";"):
        if ":" not in chunk:
            continue
        key, _, value = chunk.partition(":")
        result[key.strip()] = value.strip()
    return result


def _parse_pl_date(text: str) -> date | None:
    # e.g. "poniedziałek, 1 września 2026"
    parts = text.strip().split(" ")
    if len(parts) < 3:
        return None
    try:
        day = int(parts[-3])
        month = MONTHS_PL.index(parts[-2]) + 1
        year = int(parts[-1])
        return date(year, month, day)
    except (ValueError, IndexError):
        return None


class MobidziennikClient:
    def __init__(self, school_id: str, timeout: float = 20.0):
        self.school_id = school_id
        self.base_url = f"https://{school_id}.mobidziennik.pl"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) "
                    "Gecko/20100101 Firefox/128.0"
                )
            }
        )

    def login(self, username: str, password: str) -> None:
        response = self.session.post(
            f"{self.base_url}/dziennik",
            data={"login": username, "haslo": password},
            timeout=self.timeout,
        )
        response.raise_for_status()
        text = response.text
        if (
            text.strip() == "Nie jestes zalogowany"
            or "przypomnij_haslo_email" in text
            or "Podano niepoprawny login i/lub hasło" in text
        ):
            raise MobidziennikError("MobiDziennik login failed — check credentials/school id")

    def _get(self, path: str) -> str:
        response = self.session.get(f"{self.base_url}{path}", timeout=self.timeout)
        response.raise_for_status()
        text = response.text
        if text.strip() == "Nie jestes zalogowany":
            raise MobidziennikError("Session expired / not logged in — call login() first")
        return text

    def get_timetable_html(self, week_start: date, typ: str = "podstawowy") -> str:
        return self._get(f"/dziennik/planlekcji?typ={typ}&tydzien={week_start.isoformat()}")

    def get_lessons(self, week_start: date, typ: str = "podstawowy") -> list[Lesson]:
        html = self.get_timetable_html(week_start, typ)
        return parse_timetable(html)


def parse_timetable(html: str) -> list[Lesson]:
    ranges_h: list[tuple[float, float, date]] = []
    top_match = RE_TIMETABLE_TOP.search(html)
    if top_match:
        soup = BeautifulSoup(top_match.group(0), "html.parser")
        pos = 0.0
        for el in soup.select("div > div"):
            css = _parse_css(el.get("style", ""))
            width_str = css.get("width", "").rstrip("%")
            try:
                width = float(width_str)
            except ValueError:
                continue
            day = _parse_pl_date(el.get("title", ""))
            if day is None:
                continue
            ranges_h.append((pos, pos + width, day))
            pos += width

    hours_v: dict[int, tuple[time, int | None]] = {}
    left_match = RE_TIMETABLE_LEFT.search(html)
    if left_match:
        soup = BeautifulSoup(left_match.group(0), "html.parser")
        for el in soup.select("div > div"):
            css = _parse_css(el.get("style", ""))
            top_str = css.get("top", "").rstrip("%")
            try:
                top = float(top_str)
            except ValueError:
                continue
            span = el.find("span")
            if span is None:
                continue
            # The time text is the first direct text node; the lesson number
            # (only present on "start" rows) lives in a nested <b> right
            # after a <br/>. get_text() would run these together with no
            # separator (e.g. "09:05" + "3" -> "09:053"), so read them apart.
            time_text = next(
                (c for c in span.contents if isinstance(c, str)), ""
            ).strip()
            try:
                hh, mm = time_text.split(":")
                t = time(int(hh), int(mm))
            except ValueError:
                continue
            b_tag = span.find("b")
            b_text = b_tag.get_text().strip() if b_tag else ""
            num = int(b_text) if b_text.isdigit() else None
            hours_v[int(round(top * 100))] = (t, num)

    def range_for(h: float) -> date | None:
        for lo, hi, day in ranges_h:
            if lo <= h <= hi:
                return day
        return None

    lessons: list[Lesson] = []
    for match in RE_TIMETABLE_CELL.finditer(html):
        outer_style, inner_style, title, _content = match.groups()
        # top/height live in the outer style, left/width in the inner one.
        css = _parse_css(f"{outer_style};{inner_style}")
        try:
            left = float(css.get("left", "").rstrip("%"))
            top = float(css.get("top", "").rstrip("%"))
            width = float(css.get("width", "").rstrip("%"))
            height = float(css.get("height", "").rstrip("%"))
        except ValueError:
            continue

        pos_h = left + width / 2
        top_int = int(round(top * 100))
        bottom_int = int(round((top + height) * 100))

        lesson_date = range_for(pos_h)
        start = hours_v.get(top_int)
        end = hours_v.get(bottom_int)
        if lesson_date is None or start is None or end is None:
            continue
        start_time, lesson_number = start
        end_time, _ = end

        lesson = _parse_cell_content(title)
        lessons.append(
            Lesson(
                date=lesson_date,
                start=start_time,
                end=end_time,
                lesson_number=lesson_number,
                subject=lesson.get("subject"),
                teacher=lesson.get("teacher"),
                classroom=lesson.get("classroom"),
                team=lesson.get("team"),
                type=lesson.get("type", LessonType.NORMAL),
            )
        )

    return lessons


TYPE_MARKER_RE = re.compile(r"\$(.*?)\$")
# A standalone "HH:MM - HH:MM" line — redundant with the position-derived time.
TIME_RANGE_RE = re.compile(r"^\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}$")


def _parse_cell_content(title_attr: str) -> dict:
    """Parse a lesson cell's ``title`` attribute.

    The cell's visible ``<span>`` content has inconsistent inline markup
    (stray ``style=`` on ``<small>``, abbreviated teacher names, etc.), but
    its ``title`` attribute carries the same information as a plain,
    consistently HTML-entity-escaped string: an optional
    ``<small>TYPE</small>`` marker, then ``HH:MM - HH:MM``, subject, and
    ``TEAM - TEACHER (ROOM)``, each separated by ``<br />``. That's what this
    parses.
    """
    text = (
        title_attr.replace("&lt;small&gt;", "$")
        .replace("&lt;/small&gt;", "$")
        .replace("&lt;br /&gt;", "\n")
        .replace("&lt;br/&gt;", "\n")
        .replace("&lt;br&gt;", "\n")
        .replace("<br />", "\n")
        .replace("<br/>", "\n")
        .replace("<br>", "\n")
        .replace("<b>", "")
        .replace("</b>", "")
        .replace("<span>", "")
        .replace("</span>", "")
    )

    type_name = None
    marker = TYPE_MARKER_RE.search(text)
    if marker:
        type_name = marker.group(1).strip()
        text = TYPE_MARKER_RE.sub("", text, count=1)

    classroom = None
    classroom_match = CLASSROOM_RE.search(text)
    if classroom_match:
        classroom = classroom_match.group(1).strip()
        text = text.replace(f"({classroom})", "")

    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if line and not TIME_RANGE_RE.match(line)]

    subject = lines.pop(0) if lines else None

    team = None
    teacher = None
    if lines:
        if " - " in lines[0]:
            team, teacher = (part.strip() for part in lines[0].split(" - ", 1))
        else:
            team = lines[0]
            if len(lines) > 1:
                teacher = lines[1]

    type_name_lower = (type_name or "").lower()
    if "zastęp" in type_name_lower:
        lesson_type = LessonType.CHANGE
    elif "odwoł" in type_name_lower:
        lesson_type = LessonType.CANCELLED
    else:
        lesson_type = LessonType.NORMAL

    return {
        "subject": subject,
        "teacher": teacher,
        "classroom": classroom,
        "team": team,
        "type": lesson_type,
    }


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())
