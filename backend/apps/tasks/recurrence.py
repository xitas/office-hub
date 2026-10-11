"""Recurrence rules: the dates a repeating task falls on.

Plain calendar dates in the office's time zone (no times, so no DST or midnight surprises):
- daily:   every `interval` days from the start date
- weekly:  on the chosen weekdays (0 = Monday … 6 = Sunday), every `interval` weeks
- monthly: every `interval` months, either on a day of the month (31 → the month's last day) or on the
           1st/2nd/3rd/4th/last weekday of the month ("last Friday")
Ends after `end_date` or after `count` occurrences (whichever comes first), or never.
"""
import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

DAILY, WEEKLY, MONTHLY = "daily", "weekly", "monthly"
DAY_OF_MONTH, WEEKDAY_OF_MONTH = "day", "weekday"
LAST = -1
MAX_SEARCH = 3660  # days; no valid rule needs more than ~10 years to find its next date


@dataclass
class Rule:
    frequency: str
    start: date
    interval: int = 1
    weekdays: list[int] = field(default_factory=list)
    monthly_mode: str = DAY_OF_MONTH
    month_day: int | None = None
    month_week: int | None = None  # 1..4 or -1 (last)
    month_weekday: int | None = None  # 0..6
    end_date: date | None = None
    count: int | None = None

    def __post_init__(self):
        self.interval = max(1, int(self.interval or 1))
        if self.frequency == WEEKLY and not self.weekdays:
            self.weekdays = [self.start.weekday()]
        if self.frequency == MONTHLY:
            if self.monthly_mode == DAY_OF_MONTH and not self.month_day:
                self.month_day = self.start.day
            if self.monthly_mode == WEEKDAY_OF_MONTH:
                if self.month_weekday is None:
                    self.month_weekday = self.start.weekday()
                if not self.month_week:
                    self.month_week = (self.start.day - 1) // 7 + 1 if self.start.day <= 28 else LAST

    # ------------------------------------------------------------ matching

    def _months_since_start(self, d: date) -> int:
        return (d.year - self.start.year) * 12 + d.month - self.start.month

    def _monthly_date(self, year: int, month: int) -> date:
        last_day = calendar.monthrange(year, month)[1]
        if self.monthly_mode == DAY_OF_MONTH:
            return date(year, month, min(self.month_day, last_day))
        if self.month_week == LAST:
            d = date(year, month, last_day)
            return d - timedelta(days=(d.weekday() - self.month_weekday) % 7)
        first = date(year, month, 1)
        first_match = first + timedelta(days=(self.month_weekday - first.weekday()) % 7)
        return first_match + timedelta(weeks=self.month_week - 1)

    def matches(self, d: date) -> bool:
        if d < self.start:
            return False
        if self.frequency == DAILY:
            return (d - self.start).days % self.interval == 0
        if self.frequency == WEEKLY:
            week0 = self.start - timedelta(days=self.start.weekday())
            week = d - timedelta(days=d.weekday())
            return d.weekday() in self.weekdays and ((week - week0).days // 7) % self.interval == 0
        months = self._months_since_start(d)
        return months % self.interval == 0 and d == self._monthly_date(d.year, d.month)

    # ------------------------------------------------------------ next date

    def next_after(self, after: date, not_before: date | None = None) -> date | None:
        """First date of the rule strictly after `after` (and on or after `not_before`), within its end date."""
        d = after + timedelta(days=1)
        if not_before and d < not_before:
            d = not_before
        if d < self.start:
            d = self.start
        if self.frequency == MONTHLY:
            # Jump month by month instead of day by day.
            year, month = d.year, d.month
            for _ in range(MAX_SEARCH // 28):
                if self._months_since_start(date(year, month, 1)) % self.interval == 0:
                    candidate = self._monthly_date(year, month)
                    if candidate >= d:
                        return self._within_end(candidate)
                month += 1
                if month > 12:
                    year, month = year + 1, 1
            return None
        for _ in range(MAX_SEARCH):
            if self.matches(d):
                return self._within_end(d)
            d += timedelta(days=1)
        return None

    def _within_end(self, d: date) -> date | None:
        return None if self.end_date and d > self.end_date else d

    def first(self) -> date | None:
        """The first occurrence on or after the start date."""
        return self.start if self.matches(self.start) else self.next_after(self.start)
