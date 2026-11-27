from dataclasses import dataclass
from datetime import datetime, time, timezone
import os
import re
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class SupportHours:
    start: time | None = None
    end: time | None = None
    weekdays: frozenset[int] = frozenset()
    zone: ZoneInfo = ZoneInfo("Europe/Moscow")
    email: str | None = None

    @classmethod
    def from_values(cls, start: str, end: str, weekdays: str, zone: str, email: str):
        address = email if re.fullmatch(r"[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email) else None
        tz = ZoneInfo(zone)
        if not start and not end:
            return cls(zone=tz, email=address)
        start_time, end_time = time.fromisoformat(start), time.fromisoformat(end)
        days = frozenset(int(day) for day in weekdays.split(","))
        if start_time.tzinfo or end_time.tzinfo or start_time >= end_time or not days <= set(range(1, 8)):
            raise ValueError("Invalid support schedule")
        return cls(start_time, end_time, days, tz, address)

    @classmethod
    def from_env(cls):
        return cls.from_values(
            os.getenv("SUPPORT_HOURS_START", "").strip(),
            os.getenv("SUPPORT_HOURS_END", "").strip(),
            os.getenv("SUPPORT_WEEKDAYS", "1,2,3,4,5"),
            os.getenv("SUPPORT_TIMEZONE", "Europe/Moscow"),
            os.getenv("SUPPORT_EMAIL", "").strip(),
        )

    def status(self, now: datetime | None = None) -> dict:
        message = "Менеджер отвечает в рабочее время."
        if self.start is None or self.end is None:
            return {"status": "unknown", "message": message}
        local = (now or datetime.now(timezone.utc)).astimezone(self.zone)
        working = local.isoweekday() in self.weekdays and self.start <= local.time() < self.end
        status = {
            "status": "working_hours" if working else "outside_working_hours",
            "message": message,
            "schedule": {
                "start": self.start.isoformat(timespec="minutes"), "end": self.end.isoformat(timespec="minutes"),
                "weekdays": sorted(self.weekdays), "timezone": self.zone.key,
            },
        }
        if not working and self.email:
            status["email"] = self.email
        return status
