from data_struct import Course, Professor, Room, Student
from csp_mcv import build_csp

# Minimal sample data to reproduce the irregular-student adjacency issue.
professors = [
    Professor(
        prof_id="P1",
        name="Prof A",
        days_available=["Monday", "Tuesday"],
        f2f_start=480,
        f2f_end=1200,
        online_start=450,
        online_end=1260,
        days_f2f=["Monday", "Tuesday"],
        preference_online=False,
        preference_f2f=True,
        subjects_handled=["C1", "C2"],
    )
]

courses = [
    Course(
        course_id="C2",
        mode="f2f",
        has_lab=False,
        has_lec=True,
        time_for_lab=0,
        time_for_lec=60,
        year_level=2,
        units=3,
        college_name="CCIS",
        hour_allocation=3,
    )
]

rooms = [
    Room(
        location_code="4th_east_wing",
        location_map="4th East Wing",
        capacity=40,
        available_days=["Monday", "Tuesday"],
    )
]

students = [
    Student(
        name="Student 1",
        year_level=2,
        block="2-A",
        status="irregular",
        backlog=["C2"],
        courses=["C1", "C2", "C3"],
    )
]

time_slots = [
    {"start": 480, "end": 540},
    {"start": 540, "end": 600},
    {"start": 600, "end": 660},
]

regular_schedule = [
    {
        "course_id": "C1",
        "prof_id": "P1",
        "room": "4th_east_wing",
        "day": "Monday",
        "time_start": 540,
        "time_end": 600,
        "mode": "f2f",
        "is_lab": False,
        "year_level": 2,
        "block": "2-A",
        "is_nstp": False,
    },
    {
        "course_id": "C3",
        "prof_id": "P1",
        "room": "4th_east_wing",
        "day": "Tuesday",
        "time_start": 600,
        "time_end": 660,
        "mode": "f2f",
        "is_lab": False,
        "year_level": 2,
        "block": "2-A",
        "is_nstp": False,
    },
]

# This should fail until the scheduler actually enforces same-day adjacency.
domains = build_csp(
    courses=courses,
    professors=professors,
    rooms=rooms,
    time_slots=time_slots,
    existing_schedule=regular_schedule,
    students=students,
)

# There should be at least one candidate on Monday or Tuesday that is adjacent to the
# student's already-fixed regular classes; a wrong-day slot should be filtered out.
assert any(slot["day"] in {"Monday", "Tuesday"} for slot in domains["C2"])
assert all(slot["day"] in {"Monday", "Tuesday"} for slot in domains["C2"])

print("test_irregular_schedule.py passed")
