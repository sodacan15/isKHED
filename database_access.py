# database_access.py
# Extracts data from SQLite DB or Excel and returns data_struct objects.

import sqlite3
from copy import deepcopy
import pandas as pd
from data_struct import Professor, Course, Room, Block, Student, TimeSlot


# ─────────────────────────────────────────
# ROOM EXPANSION
# Converts wing-level entries into specific room codes.
# East Wing:  E401–E417  (17 rooms)
# South Wing: S501–S514  (14 rooms)
# Gymnasium / lab_room / others: kept as-is
# ─────────────────────────────────────────

def expand_rooms(rooms: list) -> list:
    expanded = []
    for room in rooms:
        if room.location_code == "4th_east_wing":
            for i in range(1, 18):          # E401 – E417
                r = deepcopy(room)
                r.location_code = f"E4{i:02d}"
                r.location_map  = f"East Wing E4{i:02d}"
                r.schedule      = {}
                expanded.append(r)
        elif room.location_code == "5th_south_wing":
            for i in range(1, 15):          # S501 – S514
                r = deepcopy(room)
                r.location_code = f"S5{i:02d}"
                r.location_map  = f"South Wing S5{i:02d}"
                r.schedule      = {}
                expanded.append(r)
        else:
            expanded.append(room)           # gymnasium, lab_room, etc.
    return expanded


# ─────────────────────────────────────────
# SQLITE LOADERS
# ─────────────────────────────────────────

def get_connection(db_path: str):
    return sqlite3.connect(db_path)


def load_professors_db(db_path: str) -> list[Professor]:
    conn = get_connection(db_path)
    df = pd.read_sql_query("SELECT * FROM professors", conn)
    conn.close()
    professors = []
    for _, row in df.iterrows():
        professors.append(Professor(
            prof_id          = row["prof_id"],
            name             = row["name"],
            days_available   = row["days_available"].split(","),
            f2f_start        = int(row["f2f_start"]),
            f2f_end          = int(row["f2f_end"]),
            online_start     = int(row["online_start"]),
            online_end       = int(row["online_end"]),
            days_f2f         = row["days_f2f"].split(","),
            preference_online= bool(row["preference_online"]),
            preference_f2f   = bool(row["preference_f2f"]),
            subjects_handled = row["subjects_handled"].split(","),
        ))
    return professors


def load_courses_db(db_path: str) -> list[Course]:
    conn = get_connection(db_path)
    df = pd.read_sql_query("SELECT * FROM courses", conn)
    conn.close()
    courses = []
    for _, row in df.iterrows():
        courses.append(Course(
            course_id      = row["course_id"],
            mode           = row["mode"],
            has_lab        = bool(row["has_lab"]),
            has_lec        = bool(row["has_lec"]),
            time_for_lab   = int(row["time_for_lab"]),
            time_for_lec   = int(row["time_for_lec"]),
            year_level     = int(row["year_level"]),
            units          = int(row["units"]),
            college_name   = row["college_name"],
            hour_allocation= int(row["hour_allocation"]),
        ))
    return courses


def load_rooms_db(db_path: str) -> list[Room]:
    conn = get_connection(db_path)
    df = pd.read_sql_query("SELECT * FROM rooms", conn)
    conn.close()
    rooms = []
    for _, row in df.iterrows():
        rooms.append(Room(
            location_code  = row["location_code"],
            location_map   = row["location_map"],
            capacity       = int(row["capacity"]),
            available_days = row["available_days"].split(","),
        ))
    return expand_rooms(rooms)


def load_blocks_db(db_path: str) -> list[Block]:
    conn = get_connection(db_path)
    df = pd.read_sql_query("SELECT * FROM blocks", conn)
    conn.close()
    blocks = []
    for _, row in df.iterrows():
        blocks.append(Block(
            year_level         = int(row["year_level"]),
            block_code         = row["block_code"],
            amount_of_students = int(row["amount_of_students"]),
            classes            = row["classes"].split(","),
        ))
    return blocks


def load_students_db(db_path: str) -> list[Student]:
    conn = get_connection(db_path)
    df = pd.read_sql_query("SELECT * FROM students", conn)
    conn.close()
    students = []
    for _, row in df.iterrows():
        students.append(Student(
            name       = row["name"],
            year_level = int(row["year_level"]),
            block      = row["block"],
            status     = row["status"],
            backlog    = row["backlog"].split(",") if row["backlog"] else [],
            courses    = row["courses"].split(","),
        ))
    return students


# ─────────────────────────────────────────
# EXCEL LOADERS
# ─────────────────────────────────────────

def load_professors_excel(path: str) -> list[Professor]:
    df = pd.read_excel(path, sheet_name="Professors")
    professors = []
    for _, row in df.iterrows():
        professors.append(Professor(
            prof_id          = str(row["prof_id"]),
            name             = row["name"],
            days_available   = str(row["days_available"]).split(","),
            f2f_start        = int(row["f2f_start"]),
            f2f_end          = int(row["f2f_end"]),
            online_start     = int(row["online_start"]),
            online_end       = int(row["online_end"]),
            days_f2f         = str(row["days_f2f"]).split(","),
            preference_online= bool(row["preference_online"]),
            preference_f2f   = bool(row["preference_f2f"]),
            subjects_handled = str(row["subjects_handled"]).split(","),
        ))
    return professors


def load_courses_excel(path: str) -> list[Course]:
    df = pd.read_excel(path, sheet_name="Courses")
    courses = []
    for _, row in df.iterrows():
        courses.append(Course(
            course_id      = str(row["course_id"]),
            mode           = row["mode"],
            has_lab        = bool(row["has_lab"]),
            has_lec        = bool(row["has_lec"]),
            time_for_lab   = int(row["time_for_lab"]),
            time_for_lec   = int(row["time_for_lec"]),
            year_level     = int(row["year_level"]),
            units          = int(row["units"]),
            college_name   = row["college_name"],
            hour_allocation= int(row["hour_allocation"]),
        ))
    return courses


def load_rooms_excel(path: str) -> list[Room]:
    df = pd.read_excel(path, sheet_name="Rooms")
    rooms = []
    for _, row in df.iterrows():
        rooms.append(Room(
            location_code  = str(row["location_code"]),
            location_map   = row["location_map"],
            capacity       = int(row["capacity"]),
            available_days = str(row["available_days"]).split(","),
        ))
    return expand_rooms(rooms)


def load_blocks_excel(path: str) -> list[Block]:
    df = pd.read_excel(path, sheet_name="Blocks")
    blocks = []
    for _, row in df.iterrows():
        blocks.append(Block(
            year_level         = int(row["year_level"]),
            block_code         = str(row["block_code"]),
            amount_of_students = int(row["amount_of_students"]),
            classes            = str(row["classes"]).split(","),
        ))
    return blocks


def load_students_excel(path: str) -> list[Student]:
    df = pd.read_excel(path, sheet_name="Students")
    students = []
    for _, row in df.iterrows():
        students.append(Student(
            name       = row["name"],
            year_level = int(row["year_level"]),
            block      = str(row["block"]),
            status     = row["status"],
            backlog    = str(row["backlog"]).split(",") if pd.notna(row["backlog"]) else [],
            courses    = str(row["courses"]).split(","),
        ))
    return students


# ─────────────────────────────────────────
# POWER OUTAGE SCHEDULE LOADER
# ─────────────────────────────────────────

def load_power_outage_db(db_path: str) -> list[str]:
    """Returns list of days with scheduled power outages."""
    conn = get_connection(db_path)
    df = pd.read_sql_query("SELECT day FROM power_outage_schedule", conn)
    conn.close()
    return df["day"].tolist()


def load_power_outage_excel(path: str) -> list[str]:
    df = pd.read_excel(path, sheet_name="PowerOutage")
    return df["day"].tolist()


# ─────────────────────────────────────────
# UNIFIED LOADER (auto-detects source)
# ─────────────────────────────────────────

def load_all(source: str) -> dict:
    """
    source: path to .db file or .xlsx file.
    Returns dict with keys: professors, courses, rooms, blocks, students, power_outage.
    """
    if source.endswith(".db"):
        return {
            "professors":   load_professors_db(source),
            "courses":      load_courses_db(source),
            "rooms":        load_rooms_db(source),
            "blocks":       load_blocks_db(source),
            "students":     load_students_db(source),
            "power_outage": load_power_outage_db(source),
        }
    elif source.endswith(".xlsx"):
        return {
            "professors":   load_professors_excel(source),
            "courses":      load_courses_excel(source),
            "rooms":        load_rooms_excel(source),
            "blocks":       load_blocks_excel(source),
            "students":     load_students_excel(source),
            "power_outage": load_power_outage_excel(source),
        }
    else:
        raise ValueError("Unsupported source format. Use .db or .xlsx")
