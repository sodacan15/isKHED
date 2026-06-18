# csp_mcv.py
# Initial schedule builder.
# Step 1: CSP trims valid domains per course.
# Step 2: MCV (Minimum Constraining Value) greedy builds the draft schedule.

import heapq
from data_struct import Course, Professor, Room, Assignment


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
    """Location must be 4th East Wing, 5th South Wing, or Gymnasium."""
    allowed = {"4th_east_wing", "5th_south_wing", "gymnasium"}
    if slot["mode"] == "f2f":
        return slot["room"] in allowed
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


def irregular_course_matches_student(slot: dict, course_id: str, student, schedule: list[dict]) -> bool:
    """
    For irregular students retaking a course, the backlog slot must be on one of
    their existing class days and close to their regular class times.
    """
    if course_id not in student.backlog:
        return True

    regular_slots = [
        s for s in schedule
        if s["course_id"] in student.courses and s["course_id"] not in student.backlog
    ]

    # If there is no regular schedule info yet, do not over-constrain.
    if not regular_slots:
        return True

    return any(
        slot_is_adjacent_to_regular(slot, regular_slot)
        for regular_slot in regular_slots
    )


# ─────────────────────────────────────────
# CSP — DOMAIN BUILDER (returns plain dict, no external library needed)
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

    existing_schedule: used in the 2nd CSP run for irregulars,
                       already-assigned slots are treated as blocked.
    students: optional irregular/regular student roster used to enforce
              same-day adjacency for backlog courses.
    """
    domains = {}

    for course in courses:
        domain = []
        for prof in professors:
            if course.course_id not in prof.subjects_handled:
                continue
            for day in prof.days_available:
                if day == "Sunday":
                    continue
                for slot in time_slots:
                    for room in rooms:
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
                            "block":      getattr(course, "block", f"Year {course.year_level}"),
                            "is_nstp":    course.course_id.startswith("NSTP"),
                        }
                        if not valid_time_bounds(candidate):
                            continue
                        if not valid_location(candidate):
                            continue
                        if not lab_must_be_f2f(candidate):
                            continue
                        if not no_class_sunday(candidate):
                            continue
                        # 2nd CSP run: block any candidate that conflicts with an
                        # already-scheduled slot on professor, room, or modality.
                        if existing_schedule:
                            blocked = any(
                                not no_double_booking_professor(candidate, ex)
                                or not no_double_booking_room(candidate, ex)
                                or not no_modality_mix(candidate, ex)
                                for ex in existing_schedule
                            )
                            if blocked:
                                continue

                        # Enforce same-day adjacency for retaken courses when
                        # student regular schedules are already known.
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
# MCV = course with fewest valid slots gets scheduled first
# ─────────────────────────────────────────

def build_priority_queue(domains: dict) -> list:
    """
    Returns a min-heap of (domain_size, course_id).
    Smallest domain = most constrained = scheduled first.
    """
    heap = []
    for course_id, slots in domains.items():
        heapq.heappush(heap, (len(slots), course_id))
    return heap


# ─────────────────────────────────────────
# LCV — LEAST CONSTRAINING VALUE
# Among valid slots, pick the one that blocks fewest neighbors
# ─────────────────────────────────────────

def count_conflicts(candidate: dict, assigned: list[dict], remaining_domains: dict) -> int:
    """
    Lightweight heuristic: count how many already-assigned slots
    this candidate would conflict with.

    The full-domain scan used previously was too expensive for the
    larger richer dataset and caused the CSP stage to stall.
    """
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
    """Sort candidates by the least immediate conflict first."""
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
# FORWARD CHECKING
# After assigning a slot, prune it from other domains
# ─────────────────────────────────────────

def forward_check(assigned_slot: dict, remaining_domains: dict) -> dict | None:
    """
    Removes slots from remaining domains that conflict with assigned_slot.
    Returns updated domains, or None if any domain becomes empty (dead end).
    """
    updated = {}
    for course_id, slots in remaining_domains.items():
        pruned = [
            s for s in slots
            if no_double_booking_professor(assigned_slot, s)
            and no_double_booking_room(assigned_slot, s)
            and no_modality_mix(assigned_slot, s)
        ]
        if not pruned:
            return None  # domain wipeout — trigger backtrack
        updated[course_id] = pruned
    return updated


# ─────────────────────────────────────────
# GREEDY MCV SCHEDULER (with backtracking on wipeout)
# ─────────────────────────────────────────

def candidate_conflicts(candidate: dict, assigned: list[dict]) -> bool:
    """True if candidate conflicts with any already-assigned slot."""
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

    domains:           {course_id: [valid_slot_dicts]} from build_csp()
    existing_schedule: already-assigned slots (used in 2nd CSP run for irregulars)

    Returns list of assigned slot dicts, or None if unsolvable.
    """
    # Existing schedule entries are constraints for the current run,
    # not extra assignments that should be copied into the output.
    assigned = []
    remaining_domains = dict(domains)

    def backtrack(remaining: dict, current: list) -> list | None:
        if not remaining:
            return current  # all assigned

        # MCV: pick course with fewest valid slots
        course_id = min(remaining, key=lambda c: len(remaining[c]))
        candidates = remaining[course_id]

        # Remove from remaining before trying
        rest = {k: v for k, v in remaining.items() if k != course_id}

        # LCV: order candidates by least constraining
        ordered = order_by_lcv(candidates, current, rest)

        for candidate in ordered:
            # Ensure the candidate does not conflict with anything already assigned.
            if candidate_conflicts(candidate, current):
                continue

            # Forward check: prune conflicts from rest
            pruned = forward_check(candidate, rest)
            if pruned is None:
                continue  # dead end, try next candidate

            result = backtrack(pruned, current + [candidate])
            if result is not None:
                return result

        return None  # all candidates exhausted

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
    1. CSP builds valid domains per course (plain dict, no external library).
    2. Greedy MCV picks the draft schedule from those domains.

    existing_schedule: pass in for the 2nd run (irregulars scheduling).
    Returns list of slot dicts ready for GA/SA refinement.
    """
    # Step 1: CSP domain trimming
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

    # Step 2: Greedy MCV draft
    schedule = greedy_mcv(domains, existing_schedule)

    if schedule is None:
        raise RuntimeError("MCV greedy could not build a valid initial schedule.")

    print(f"✅ Initial schedule built: {len(schedule)} assignments.")
    return schedule