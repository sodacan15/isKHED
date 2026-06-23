# csp_mcv.py
# Initial schedule builder.
# Step 1: CSP trims valid domains per course.
# Step 2: MCV (Minimum Constraining Value) greedy builds the draft schedule.

import heapq
from data_struct import Course, Professor, Room, Assignment


# ─────────────────────────────────────────
# HELPERS: composite key parsing
# ─────────────────────────────────────────

def base_course_id(composite_id: str) -> str:
    """
    Returns the original course_id without any block/lab/lec/irr suffixes.
    Examples:
        'C1__1-A'         → 'C1'
        'C1__1-A__lab'    → 'C1'
        'C1__1-A__lec'    → 'C1'
        'C1__1-A__irr'    → 'C1'
    """
    return composite_id.split("__")[0]


def get_block_from_key(composite_id: str) -> str:
    """
    Returns the block code embedded in the composite key.
    'C1__1-A__lab' → '1-A'
    'C1__1-A'      → '1-A'
    """
    parts = composite_id.split("__")
    return parts[1] if len(parts) >= 2 else ""


def get_lab_lec_partner(composite_id: str) -> str | None:
    """
    If composite_id ends with '__lab' return the '__lec' partner and vice versa.
    Returns None if the course is not part of a lab+lec pair.

    'C1__1-A__lab' → 'C1__1-A__lec'
    'C1__1-A__lec' → 'C1__1-A__lab'
    'C1__1-A'      → None
    """
    parts = composite_id.split("__")
    if len(parts) < 3:
        return None
    suffix = parts[-1]
    if suffix == "lab":
        parts[-1] = "lec"
        return "__".join(parts)
    if suffix == "lec":
        parts[-1] = "lab"
        return "__".join(parts)
    return None


def is_lab_component(composite_id: str) -> bool:
    return composite_id.endswith("__lab")


def is_lec_component(composite_id: str) -> bool:
    return composite_id.endswith("__lec")


# ─────────────────────────────────────────
# CSP — HARD CONSTRAINT FUNCTIONS
# ─────────────────────────────────────────

def time_overlaps(slot1: dict, slot2: dict) -> bool:
    """Check if two time slots overlap on the same day."""
    if slot1["day"] != slot2["day"]:
        return False
    return slot1["time_start"] < slot2["time_end"] and slot2["time_start"] < slot1["time_end"]


def no_modality_mix(slot1: dict, slot2: dict) -> bool:
    """No mix of modality unless 3-4 hour gap exists."""
    if slot1["mode"] != slot2["mode"]:
        gap = abs(slot1["time_start"] - slot2["time_start"])
        return gap >= 180
    return True


def no_double_booking_professor(slot1: dict, slot2: dict) -> bool:
    """One unique time slot per block each professor."""
    if slot1["prof_id"] == slot2["prof_id"]:
        return not time_overlaps(slot1, slot2)
    return True


def no_double_booking_room(slot1: dict, slot2: dict) -> bool:
    """No two classes in the same room at the same time."""
    if slot1["room"] == slot2["room"]:
        return not time_overlaps(slot1, slot2)
    return True


def lab_must_be_f2f(slot: dict) -> bool:
    """Laboratory classes must be conducted face-to-face."""
    if slot["is_lab"]:
        return slot["mode"] == "f2f"
    return True


def valid_time_bounds(slot: dict) -> bool:
    """F2F: 8AM-8PM (480-1200), Online: 7:30AM-9PM (450-1260)."""
    start, end = slot["time_start"], slot["time_end"]
    if slot["mode"] == "f2f":
        return start >= 480 and end <= 1200
    elif slot["mode"] == "online":
        return start >= 450 and end <= 1260
    return True


def valid_location(slot: dict) -> bool:
    """
    F2F rooms:
      - Lecture/GEED → 4th Floor East Wing (E4xx)
      - Lab          → 5th Floor South Wing (S5xx) or lab_room
      - PATHFIT      → gymnasium
    Online: no physical room restriction.
    """
    if slot["mode"] == "f2f":
        room = slot["room"]
        if slot["is_lab"]:
            return room.startswith("S5") or room == "lab_room"
        else:
            return room.startswith("E4") or room == "gymnasium"
    return True


def no_class_sunday(slot: dict) -> bool:
    """Sunday is a no-class day except NSTP for first years."""
    if slot["day"] == "Sunday":
        return slot.get("is_nstp", False) and slot.get("year_level") == 1
    return True


def slot_is_adjacent_to_regular(slot: dict, regular_slot: dict, tolerance: int = 90) -> bool:
    """True when two slots are on the same day and are close enough to be considered adjacent."""
    if slot["day"] != regular_slot["day"]:
        return False
    return (
        (slot["time_end"] <= regular_slot["time_start"]
         and regular_slot["time_start"] - slot["time_end"] <= tolerance)
        or
        (regular_slot["time_end"] <= slot["time_start"]
         and slot["time_start"] - regular_slot["time_end"] <= tolerance)
    )


def lab_lec_are_adjacent(lab_slot: dict, lec_slot: dict, max_gap: int = 30) -> bool:
    """
    Lab and lecture components of the same course must be:
      1. On the same day.
      2. Back-to-back (or separated by ≤ max_gap minutes).
    """
    if lab_slot["day"] != lec_slot["day"]:
        return False
    gap = abs(lab_slot["time_start"] - lec_slot["time_end"])
    gap2 = abs(lec_slot["time_start"] - lab_slot["time_end"])
    return min(gap, gap2) <= max_gap


def irregular_course_matches_student(slot: dict, course_id: str, student, schedule: list[dict]) -> bool:
    """
    For irregular students retaking a course, the backlog slot must be on one of
    their existing class days and close to their regular class times.
    """
    base_cid = base_course_id(course_id)
    if base_cid not in student.backlog:
        return True

    regular_slots = [
        s for s in schedule
        if base_course_id(s["course_id"]) in student.courses
        and base_course_id(s["course_id"]) not in student.backlog
    ]

    if not regular_slots:
        return True

    return any(
        slot_is_adjacent_to_regular(slot, regular_slot)
        for regular_slot in regular_slots
    )


# ─────────────────────────────────────────
# DURATION MATCHING
# For lab/lec split courses, only allow time slots that match
# the course's declared duration (time_for_lab / time_for_lec).
# ─────────────────────────────────────────

def duration_matches(slot_start: int, slot_end: int, course) -> bool:
    """
    If the course has a declared component duration, only accept
    time slots whose length equals that duration.
    Falls back to accepting any slot if both durations are 0.
    """
    duration = slot_end - slot_start
    if is_lab_component(course.course_id) and course.time_for_lab > 0:
        return duration == course.time_for_lab
    if is_lec_component(course.course_id) and course.time_for_lec > 0:
        return duration == course.time_for_lec
    # Single-component course with explicit duration
    if course.has_lab and not course.has_lec and course.time_for_lab > 0:
        return duration == course.time_for_lab
    if course.has_lec and not course.has_lab and course.time_for_lec > 0:
        return duration == course.time_for_lec
    return True   # no declared duration — accept any valid slot


# ─────────────────────────────────────────
# CSP — DOMAIN BUILDER
# ─────────────────────────────────────────

def build_csp(
    courses: list,
    professors: list,
    rooms: list,
    time_slots: list[dict],
    existing_schedule: list[dict] = None,
    students: list = None,
) -> dict:
    """
    Trims valid (room, time, day, mode) candidates per course.
    Returns a plain dict: { course_id: [valid_slot_dicts] }
    """
    domains = {}

    for course in courses:
        domain = []
        for prof in professors:
            if base_course_id(course.course_id) not in prof.subjects_handled:
                continue
            for day in prof.days_available:
                if day == "Sunday":
                    continue
                for slot in time_slots:
                    # Duration must match declared lab/lec time if set
                    if not duration_matches(slot["start"], slot["end"], course):
                        continue
                    for room in rooms:
                        if day not in room.available_days:
                            continue

                        candidate = {
                            "course_id":  course.course_id,
                            "prof_id":    prof.prof_id,
                            "room":       room.location_code,
                            "day":        day,
                            "time_start": slot["start"],
                            "time_end":   slot["end"],
                            "mode":       course.mode,
                            "is_lab":     course.has_lab,
                            "year_level": course.year_level,
                            "block":      course.block if course.block else f"Year {course.year_level}",
                            "is_nstp":    base_course_id(course.course_id).upper().startswith("NSTP"),
                        }
                        if not valid_time_bounds(candidate):
                            continue
                        if not valid_location(candidate):
                            continue
                        if not lab_must_be_f2f(candidate):
                            continue
                        if not no_class_sunday(candidate):
                            continue
                        if existing_schedule:
                            blocked = any(
                                not no_double_booking_professor(candidate, ex)
                                or not no_double_booking_room(candidate, ex)
                                or not no_modality_mix(candidate, ex)
                                for ex in existing_schedule
                            )
                            if blocked:
                                continue

                        if existing_schedule and students:
                            if not all(
                                irregular_course_matches_student(
                                    candidate,
                                    course.course_id,
                                    student,
                                    existing_schedule,
                                )
                                for student in students
                                if student.status == "irregular"
                            ):
                                continue

                        domain.append(candidate)

        domains[course.course_id] = domain

    return domains


# ─────────────────────────────────────────
# MCV PRIORITY QUEUE
# ─────────────────────────────────────────

def build_priority_queue(domains: dict) -> list:
    heap = []
    for course_id, slots in domains.items():
        heapq.heappush(heap, (len(slots), course_id))
    return heap


# ─────────────────────────────────────────
# LCV — LEAST CONSTRAINING VALUE
# ─────────────────────────────────────────

def count_conflicts(candidate: dict, assigned: list[dict], remaining_domains: dict) -> int:
    return sum(
        1
        for ex in assigned
        if (
            not no_double_booking_professor(candidate, ex)
            or not no_double_booking_room(candidate, ex)
            or not no_modality_mix(candidate, ex)
        )
    )


def order_by_lcv(candidates: list[dict], assigned: list[dict], remaining_domains: dict) -> list[dict]:
    return sorted(
        candidates,
        key=lambda c: (
            count_conflicts(c, assigned, remaining_domains),
            c["time_start"],
            c["day"],
            c["room"],
        ),
    )


# ─────────────────────────────────────────
# FORWARD CHECKING (with lab+lec same-day pruning)
# ─────────────────────────────────────────

def forward_check(assigned_slot: dict, remaining_domains: dict) -> dict | None:
    """
    After assigning a slot:
    1. Prune any slot that conflicts on professor or room from all remaining domains.
    2. If the assigned slot is a lab or lec component, also prune the partner domain
       to only same-day slots (enforcing lab+lec co-scheduling on the same day).
    Returns updated domains, or None if any domain becomes empty.
    """
    course_id = assigned_slot["course_id"]
    partner_key = get_lab_lec_partner(course_id)

    updated = {}
    for cid, slots in remaining_domains.items():
        pruned = [
            s for s in slots
            if no_double_booking_professor(assigned_slot, s)
            and no_double_booking_room(assigned_slot, s)
            and no_modality_mix(assigned_slot, s)
        ]

        # Lab+lec same-day constraint: if this is the partner, keep only same-day slots
        if partner_key and cid == partner_key:
            pruned = [s for s in pruned if s["day"] == assigned_slot["day"]]

        if not pruned:
            return None   # domain wipeout — trigger backtrack
        updated[cid] = pruned

    return updated


# ─────────────────────────────────────────
# GREEDY MCV SCHEDULER (with backtracking)
# ─────────────────────────────────────────

def candidate_conflicts(candidate: dict, assigned: list[dict]) -> bool:
    return any(
        not no_double_booking_professor(candidate, ex)
        or not no_double_booking_room(candidate, ex)
        or not no_modality_mix(candidate, ex)
        for ex in assigned
    )


def greedy_mcv(
    domains: dict,
    existing_schedule: list[dict] = None,
) -> list[dict] | None:
    """
    Builds an initial schedule draft using MCV + LCV + Forward Checking.
    Lab+lec partner pairs are constrained to the same day via forward_check.
    """
    assigned = []
    remaining_domains = dict(domains)

    def backtrack(remaining: dict, current: list) -> list | None:
        if not remaining:
            return current

        course_id = min(remaining, key=lambda c: len(remaining[c]))
        candidates = remaining[course_id]
        rest = {k: v for k, v in remaining.items() if k != course_id}
        ordered = order_by_lcv(candidates, current, rest)

        for candidate in ordered:
            if candidate_conflicts(candidate, current):
                continue

            # Extra check: if partner is already assigned, enforce same-day adjacency
            partner_key = get_lab_lec_partner(course_id)
            if partner_key:
                already_assigned_partner = next(
                    (a for a in current if a["course_id"] == partner_key), None
                )
                if already_assigned_partner:
                    if not lab_lec_are_adjacent(
                        candidate if is_lab_component(course_id) else already_assigned_partner,
                        already_assigned_partner if is_lab_component(course_id) else candidate,
                    ):
                        continue

            pruned = forward_check(candidate, rest)
            if pruned is None:
                continue

            result = backtrack(pruned, current + [candidate])
            if result is not None:
                return result

        return None

    return backtrack(remaining_domains, assigned)


# ─────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────

def build_initial_schedule(
    courses: list,
    professors: list,
    rooms: list,
    time_slots: list[dict],
    existing_schedule: list[dict] = None,
    students: list = None,
) -> list[dict]:
    """
    Full pipeline:
    1. CSP builds valid domains per course.
    2. Greedy MCV picks the draft schedule from those domains.
       Lab+lec pairs are constrained to the same day and adjacent times.
    """
    domains = build_csp(
        courses,
        professors,
        rooms,
        time_slots,
        existing_schedule,
        students=students,
    )

    empty = [c for c, d in domains.items() if not d]
    if empty:
        raise ValueError(f"CSP found no valid slots for: {empty}")

    schedule = greedy_mcv(domains, existing_schedule)

    if schedule is None:
        raise RuntimeError("MCV greedy could not build a valid initial schedule.")

    print(f"✅ Initial schedule built: {len(schedule)} assignments.")
    return schedule
