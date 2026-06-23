# data_struct.py
# Stores all object templates used across the scheduler system.

from dataclasses import dataclass, field
from typing import List, Optional
import datetime


# ─────────────────────────────────────────
# PROFESSOR
# ─────────────────────────────────────────

@dataclass
class Professor:
    prof_id: str
    name: str
    days_available: List[str]           # e.g. ["Monday", "Wednesday", "Friday"]
    f2f_start: int                      # minutes from midnight, e.g. 480 = 8:00 AM
    f2f_end: int                        # e.g. 1200 = 8:00 PM
    online_start: int                   # e.g. 450 = 7:30 AM
    online_end: int                     # e.g. 1260 = 9:00 PM
    days_f2f: List[str]                 # days they come to campus
    preference_online: bool
    preference_f2f: bool
    subjects_handled: List[str]         # list of course_ids


# ─────────────────────────────────────────
# COURSE
# ─────────────────────────────────────────

@dataclass
class Course:
    course_id: str
    mode: str                           # 'f2f' | 'online' | 'hybrid'
    has_lab: bool
    has_lec: bool
    time_for_lab: int                   # duration in minutes
    time_for_lec: int                   # duration in minutes
    year_level: int
    units: int
    college_name: str
    hour_allocation: int                # total hours per week
    block: str = ""                     # block_code when expanded per-block, e.g. "1-A"


# ─────────────────────────────────────────
# ROOM
# ─────────────────────────────────────────

@dataclass
class Room:
    location_code: str                  # e.g. 'E401', 'S501', 'gymnasium'
    location_map: str                   # human-readable label
    capacity: int
    available_days: List[str]
    schedule: dict = field(default_factory=dict)  # {day: [time_slots_used]}


# ─────────────────────────────────────────
# BLOCK
# ─────────────────────────────────────────

@dataclass
class Block:
    year_level: int
    block_code: str                     # e.g. '2-A', '3-B'
    amount_of_students: int
    classes: List[str] = field(default_factory=list)  # list of course_ids


# ─────────────────────────────────────────
# STUDENT
# ─────────────────────────────────────────

@dataclass
class Student:
    name: str
    year_level: int
    block: str                          # block_code
    status: str                         # 'regular' | 'irregular'
    backlog: List[str] = field(default_factory=list)   # course_ids being retaken
    courses: List[str] = field(default_factory=list)   # all enrolled course_ids


# ─────────────────────────────────────────
# TIME SLOT
# ─────────────────────────────────────────

@dataclass
class TimeSlot:
    start: int      # minutes from midnight
    end: int        # minutes from midnight

    def duration(self) -> int:
        return self.end - self.start

    def to_readable(self) -> str:
        def fmt(m):
            h, mn = divmod(m, 60)
            period = "AM" if h < 12 else "PM"
            h = h if h <= 12 else h - 12
            h = 12 if h == 0 else h
            return f"{h}:{mn:02d} {period}"
        return f"{fmt(self.start)} - {fmt(self.end)}"


# ─────────────────────────────────────────
# ASSIGNMENT (output unit)
# ─────────────────────────────────────────

@dataclass
class Assignment:
    course_id: str
    prof_id: str
    room: str
    day: str
    time_start: int
    time_end: int
    mode: str
    is_lab: bool
    year_level: int
    block: str
    is_nstp: bool = False

    def to_dict(self) -> dict:
        return {
            "course_id":  self.course_id,
            "prof_id":    self.prof_id,
            "room":       self.room,
            "day":        self.day,
            "time_start": self.time_start,
            "time_end":   self.time_end,
            "mode":       self.mode,
            "is_lab":     self.is_lab,
            "year_level": self.year_level,
            "block":      self.block,
            "is_nstp":    self.is_nstp,
        }


# ─────────────────────────────────────────
# MASTER LIST (final output)
# ─────────────────────────────────────────

@dataclass
class MasterList:
    """Final schedule output — one per block, indexed by day."""
    block: str
    schedule: dict = field(default_factory=dict)  # {day: [Assignment]}

    def add(self, assignment: Assignment):
        self.schedule.setdefault(assignment.day, []).append(assignment)

    def get_day(self, day: str) -> List[Assignment]:
        return sorted(self.schedule.get(day, []), key=lambda a: a.time_start)
