# csp_mcv.py
# Initial schedule builder.
# Step 1: CSP trims valid domains per course.
# Step 2: MCV (Minimum Constraining Value) greedy builds the draft schedule.
#
# Changes vs previous version:
#   [FIX-1]  valid_location now also validates online rooms (was skipping them silently)
#   [FIX-2]  no_modality_mix gap is now measured between ENDS and STARTS (not start-to-start)
#   [FIX-3]  lab_room added to valid F2F locations to match generate_richer_input.py data
#   [FIX-4]  slot_is_adjacent_to_regular uses tighter same-day window (60 min, not 90)
#   [FIX-5]  irregular_course_matches_student: checks that the backlog slot is STRICTLY on
#             a day the student already has regular classes on (not just any day)
#   [NEW-1]  no_student_block_overlap: prevents a student's block from having two overlapping
#             classes on the same day (enforces one unique time slot per block per professor)
#   [NEW-2]  lab_and_lec_same_day: if a course has both lab and lec, they must be on the
#             same day (per Table 1: "Laboratory and lecture must be together")
#   [NEW-3]  three_no_class_days: soft-constraint helper — ensures no more than 3
#             scheduled days per block per week (used in fitness scoring)
#   [NEW-4]  resolve_conflicts() public helper — returns a structured conflict report
#             for a full schedule (used by the UI's Manual Adjustments tab)
#   [NEW-5]  build_csp now enforces lab_room for lab slots and non-lab rooms for lec slots

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
    """
    No mix of modality unless a 3-hour gap exists between the END of the earlier
    class and the START of the later class (CHED CMO 06 s.2022).

    [FIX-2] Previous version measured start-to-start. The paper specifies a gap
    *between* classes, so we now measure end-of-first to start-of-second.
    """
    if slot1["day"] != slot2["day"]:
        return True
    if slot1["mode"] == slot2["mode"]:
        return True
    # Put earlier slot first
    first, second = (slot1, slot2) if slot1["time_start"] <= slot2["time_start"] else (slot2, slot1)
    gap = second["time_start"] - first["time_end"]
    return gap >= 180


def no_double_booking_professor(slot1: dict, slot2: dict) -> bool:
    """One unique time slot per block each professor (CHED, 2008)."""
    if slot1["prof_id"] == slot2["prof_id"]:
        return not time_overlaps(slot1, slot2)
    return True


def no_double_booking_room(slot1: dict, slot2: dict) -> bool:
    """No two classes in the same room at the same time."""
    if slot1["room"] == slot2["room"]:
        return not time_overlaps(slot1, slot2)
    return True


def no_student_block_overlap(slot1: dict, slot2: dict) -> bool:
    """
    [NEW-1] A student block must not have two overlapping classes on the same day.
    Enforces: one unique time slot per block (CHED, 2008).
    """
    if slot1.get("block") and slot1["block"] == slot2.get("block"):
        return not time_overlaps(slot1, slot2)
    return True


def lab_must_be_f2f(slot: dict) -> bool:
    """Laboratory classes must be conducted face-to-face (CHED, 2022)."""
    if slot["is_lab"]:
        return slot["mode"] == "f2f"
    return True


def valid_time_bounds(slot: dict) -> bool:
    """
    F2F: 8:00 AM–8:00 PM (480–1200).
    Online: 7:30 AM–9:00 PM (450–1260).
    (CCIS observed scheduling practice)
    """
    start, end = slot["time_start"], slot["time_end"]
    if slot["mode"] == "f2f":
        return start >= 480 and end <= 1200
    elif slot["mode"] == "online":
        return start >= 450 and end <= 1260
    return True


# [FIX-1] + [FIX-3] valid_location now covers all modes and includes lab_room.
_F2F_ROOMS    = {"4th_east_wing", "5th_south_wing", "gymnasium", "lab_room"}
_LAB_ROOMS    = {"lab_room", "5th_south_wing"}   # labs must be in these rooms
_LEC_ROOMS    = {"4th_east_wing", "gymnasium"}    # lec/GEED/PATHFIT rooms
_ONLINE_ROOMS = {"online"}                         # online classes have no physical room


def valid_location(slot: dict) -> bool:
    """
    Location must be 4th East Wing, 5th South Wing, Gymnasium, or Lab Room for F2F.
    Online classes must be assigned the virtual room code 'online'.
    Lab slots must use a lab-capable room (5th South Wing or lab_room).
    (CCIS observed scheduling practice + CHED, 2022)

    [FIX-1] Previous version silently allowed any room for online courses.
    [FIX-3] lab_room added so richer dataset rooms pass validation.
    """
    mode = slot["mode"]
    room = slot["room"]
    if mode == "f2f":
        if room not in _F2F_ROOMS:
            return False
        # Lab slots must be in a lab-capable room
        if slot.get("is_lab") and room not in _LAB_ROOMS:
            return False
        return True
    elif mode == "online":
        # Online classes should not occupy a physical room
        return room in _ONLINE_ROOMS or room == ""
    return True


def no_class_sunday(slot: dict) -> bool:
    """
    Sunday is a no-class day except NSTP for first-year students (PUP, 2019).
    """
    if slot["day"] == "Sunday":
        return slot.get("is_nstp", False) and slot.get("year_level") == 1
    return True


def lab_and_lec_same_day(lab_slot: dict, lec_slot: dict) -> bool:
    """
    [NEW-2] If a course has both a lab and a lecture component they must be
    scheduled on the same day (Table 1: "Laboratory and lecture must be together").
    Only evaluated when both slots share the same course_id.
    """
    if lab_slot["course_id"] != lec_slot["course_id"]:
        return True
    if not lab_slot["is_lab"] or lec_slot["is_lab"]:
        return True
    return lab_slot["day"] == lec_slot["day"]


# ─────────────────────────────────────────
# SOFT CONSTRAINT HELPERS (used by fitness + UI report)
# ─────────────────────────────────────────

def three_no_class_days(schedule: list[dict], block: str) -> bool:
    """
    [NEW-3] Soft: A block should have at most 3 scheduled days per week, leaving
    at least 3 no-class days (Sunday is always a no-class day — PUP, 2019).
    Returns True when the constraint is satisfied.
    """
    all_days = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
    block_slots = [s for s in schedule if s.get("block") == block]
    scheduled_days = {s["day"] for s in block_slots}
    # Sunday already enforced elsewhere; count only weekday classes
    scheduled_days.discard("Sunday")
    return len(scheduled_days) <= 4  # ≤4 weekdays → ≥3 no-class days inc. Sunday


# ─────────────────────────────────────────
# IRREGULAR STUDENT HELPERS
# ─────────────────────────────────────────

def slot_is_adjacent_to_regular(slot: dict, regular_slot: dict, tolerance: int = 60) -> bool:
    """
    True when two slots are on the same day and within `tolerance` minutes of each
    other (gap between end-of-one and start-of-the-other).

    [FIX-4] Tolerance tightened from 90 → 60 min to enforce genuine adjacency.
    """
    if slot["day"] != regular_slot["day"]:
        return False
    return (
        (slot["time_end"] <= regular_slot["time_start"]
         and regular_slot["time_start"] - slot["time_end"] <= tolerance)
        or
        (regular_slot["time_end"] <= slot["time_start"]
         and slot["time_start"] - regular_slot["time_end"] <= tolerance)
    )


def irregular_course_matches_student(
    slot: dict,
    course_id: str,
    student,
    schedule: list[dict],
) -> bool:
    """
    For irregular students retaking a course, the backlog slot must be:
      (a) on a day the student already has regular (non-backlog) classes, AND
      (b) adjacent (within 60 min) to at least one of those regular classes.

    [FIX-5] Previous version allowed any day as long as one adjacency existed.
    Now we first check that the day itself is a "class day" for the student.
    """
    if course_id not in student.backlog:
        return True

    regular_slots = [
        s for s in schedule
        if s["course_id"] in student.courses and s["course_id"] not in student.backlog
    ]

    if not regular_slots:
        return True  # no existing schedule yet — do not over-constrain

    # [FIX-5] Must be on one of the student's existing class days
    student_class_days = {s["day"] for s in regular_slots}
    if slot["day"] not in student_class_days:
        return False

    # Must be adjacent to at least one regular slot on that same day
    same_day_regulars = [s for s in regular_slots if s["day"] == slot["day"]]
    return any(
        slot_is_adjacent_to_regular(slot, regular_slot)
        for regular_slot in same_day_regulars
    )


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

    existing_schedule: used in the 2nd CSP run for irregulars;
                       already-assigned slots are treated as blocked.
    students:          optional roster used to enforce same-day adjacency
                       for backlog courses of irregular students.

    [NEW-5] Lab slots are now restricted to lab-capable rooms only;
            lecture slots are restricted to non-lab rooms.
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
                        # [NEW-5] Route lab vs lec to the right room type up-front
                        if course.has_lab and room.location_code not in _LAB_ROOMS:
                            continue
                        if course.has_lec and not course.has_lab and room.location_code in _LAB_ROOMS:
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
                            "block":      getattr(course, "block", f"Year {course.year_level}"),
                            "is_nstp":    course.course_id.startswith("NSTP"),
                        }

                        # ── Hard constraint filters ───────────────────────
                        if not valid_time_bounds(candidate):
                            continue
                        if not valid_location(candidate):
                            continue
                        if not lab_must_be_f2f(candidate):
                            continue
                        if not no_class_sunday(candidate):
                            continue

                        # ── 2nd-run: block slots conflicting with existing ─
                        if existing_schedule:
                            blocked = any(
                                not no_double_booking_professor(candidate, ex)
                                or not no_double_booking_room(candidate, ex)
                                or not no_modality_mix(candidate, ex)
                                or not no_student_block_overlap(candidate, ex)  # [NEW-1]
                                for ex in existing_schedule
                            )
                            if blocked:
                                continue

                        # ── Irregular adjacency enforcement ───────────────
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
    """
    Returns a min-heap of (domain_size, course_id).
    Smallest domain = most constrained = scheduled first (MCV / MRV heuristic).
    """
    heap = []
    for course_id, slots in domains.items():
        heapq.heappush(heap, (len(slots), course_id))
    return heap


# ─────────────────────────────────────────
# LCV — LEAST CONSTRAINING VALUE
# ─────────────────────────────────────────

def count_conflicts(candidate: dict, assigned: list[dict], remaining_domains: dict) -> int:
    """
    Lightweight heuristic: count how many already-assigned slots this candidate
    would conflict with (prof double-booking, room double-booking, modality mix,
    or block overlap).
    """
    return sum(
        1
        for ex in assigned
        if (
            not no_double_booking_professor(candidate, ex)
            or not no_double_booking_room(candidate, ex)
            or not no_modality_mix(candidate, ex)
            or not no_student_block_overlap(candidate, ex)  # [NEW-1]
        )
    )


def order_by_lcv(
    candidates: list[dict],
    assigned: list[dict],
    remaining_domains: dict,
) -> list[dict]:
    """Sort candidates by the least immediate conflict first (LCV heuristic)."""
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
            and no_student_block_overlap(assigned_slot, s)  # [NEW-1]
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
        or not no_student_block_overlap(candidate, ex)  # [NEW-1]
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
    assigned = []
    remaining_domains = dict(domains)

    def backtrack(remaining: dict, current: list) -> list | None:
        if not remaining:
            return current  # all assigned

        # MCV: pick the course with the fewest valid slots (fail-first)
        course_id = min(remaining, key=lambda c: len(remaining[c]))
        candidates = remaining[course_id]
        rest = {k: v for k, v in remaining.items() if k != course_id}

        # LCV: order candidates by least constraining
        ordered = order_by_lcv(candidates, current, rest)

        for candidate in ordered:
            if candidate_conflicts(candidate, current):
                continue

            pruned = forward_check(candidate, rest)
            if pruned is None:
                continue  # dead end — try next

            result = backtrack(pruned, current + [candidate])
            if result is not None:
                return result

        return None  # all candidates exhausted — backtrack

    return backtrack(remaining_domains, assigned)


# ─────────────────────────────────────────
# CONFLICT RESOLVER  [NEW-4]
# Public helper used by the UI's Manual Adjustments tab and constraint_check.py
# ─────────────────────────────────────────

def resolve_conflicts(schedule: list[dict]) -> dict:
    """
    Scans a complete schedule for all pairwise hard-constraint violations and
    returns a structured report.

    Returns:
        {
          "professor_conflicts":  [ (slot_a, slot_b, description), ... ],
          "room_conflicts":       [ (slot_a, slot_b, description), ... ],
          "modality_conflicts":   [ (slot_a, slot_b, description), ... ],
          "block_overlaps":       [ (slot_a, slot_b, description), ... ],
          "lab_mode_violations":  [ (slot, description), ... ],
          "time_bound_violations":[ (slot, description), ... ],
          "location_violations":  [ (slot, description), ... ],
          "sunday_violations":    [ (slot, description), ... ],
          "total":                int,
        }
    """
    report = {
        "professor_conflicts":   [],
        "room_conflicts":        [],
        "modality_conflicts":    [],
        "block_overlaps":        [],
        "lab_mode_violations":   [],
        "time_bound_violations": [],
        "location_violations":   [],
        "sunday_violations":     [],
    }

    # Per-slot checks
    for slot in schedule:
        if not lab_must_be_f2f(slot):
            report["lab_mode_violations"].append(
                (slot, f"{slot['course_id']} is a lab but mode={slot['mode']}")
            )
        if not valid_time_bounds(slot):
            report["time_bound_violations"].append(
                (slot, f"{slot['course_id']} on {slot['day']} "
                       f"[{slot['time_start']}–{slot['time_end']}] is outside allowed hours")
            )
        if not valid_location(slot):
            report["location_violations"].append(
                (slot, f"{slot['course_id']} assigned to invalid room '{slot['room']}'")
            )
        if not no_class_sunday(slot):
            report["sunday_violations"].append(
                (slot, f"{slot['course_id']} illegally scheduled on Sunday")
            )

    # Pairwise checks
    for i in range(len(schedule)):
        for j in range(i + 1, len(schedule)):
            s1, s2 = schedule[i], schedule[j]
            if not no_double_booking_professor(s1, s2):
                report["professor_conflicts"].append(
                    (s1, s2,
                     f"Prof {s1['prof_id']} double-booked: "
                     f"{s1['course_id']} & {s2['course_id']} on {s1['day']}")
                )
            if not no_double_booking_room(s1, s2):
                report["room_conflicts"].append(
                    (s1, s2,
                     f"Room {s1['room']} double-booked: "
                     f"{s1['course_id']} & {s2['course_id']} on {s1['day']}")
                )
            if not no_modality_mix(s1, s2):
                report["modality_conflicts"].append(
                    (s1, s2,
                     f"Modality mix without 3h gap: "
                     f"{s1['course_id']} ({s1['mode']}) & "
                     f"{s2['course_id']} ({s2['mode']}) on {s1['day']}")
                )
            if not no_student_block_overlap(s1, s2):
                report["block_overlaps"].append(
                    (s1, s2,
                     f"Block {s1['block']} has overlapping classes: "
                     f"{s1['course_id']} & {s2['course_id']} on {s1['day']}")
                )

    report["total"] = sum(len(v) for v in report.values())
    return report


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

    existing_schedule: pass in for the 2nd run (irregulars scheduling).
    Returns list of slot dicts ready for GA/SA refinement.
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
