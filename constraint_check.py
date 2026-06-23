# constraint_check.py
# Checker — validates a schedule against all hard and soft constraints.
# Used after CSP, after GA, and after SA to verify correctness.

from data_struct import Assignment, Professor, Student
from csp_mcv import (
    base_course_id,
    no_modality_mix,
    no_double_booking_professor,
    no_double_booking_room,
    lab_must_be_f2f,
    valid_time_bounds,
    valid_location,
    no_class_sunday,
    time_overlaps,
)


# ── Soft constraint functions ─────────────────────────────────────────────────

def break_duration_score(slots: list[dict]) -> int:
    penalty = 0
    slots_sorted = sorted(slots, key=lambda s: s["time_start"])
    consecutive = 0
    for i in range(len(slots_sorted) - 1):
        curr = slots_sorted[i]
        nxt  = slots_sorted[i + 1]
        gap  = nxt["time_start"] - curr["time_end"]
        if gap < 60:
            penalty += 10
        break_start = curr["time_end"]
        if 720 <= break_start <= 1020 and gap < 90:
            penalty += 5
        consecutive += curr["time_end"] - curr["time_start"]
        if gap >= 60:
            consecutive = 0
        elif consecutive > 240:
            penalty += 15
    return penalty


def modality_switch_gap_score(slots: list[dict]) -> int:
    penalty = 0
    slots_sorted = sorted(slots, key=lambda s: s["time_start"])
    for i in range(len(slots_sorted) - 1):
        curr = slots_sorted[i]
        nxt  = slots_sorted[i + 1]
        if curr["mode"] != nxt["mode"]:
            gap = nxt["time_start"] - curr["time_end"]
            if gap < 180:
                penalty += 20
    return penalty


def power_outage_relocation_score(slot: dict, power_outage_schedule: list[str]) -> int:
    penalty = 0
    if slot["day"] in power_outage_schedule:
        if slot["is_lab"] and slot["room"] != "5th_south_wing":
            penalty += 25
        elif not slot["is_lab"] and slot["room"] != "5th_south_wing":
            penalty += 10
    return penalty


def irregular_priority_score(slot: dict, student: dict) -> int:
    base_cid = base_course_id(slot["course_id"])
    if base_cid in student.get("backlog", []):
        return 5
    return 0


def professor_preference_score(slot: dict, professor) -> int:
    penalty = 0
    if professor.preference_f2f and slot["mode"] != "f2f":
        penalty += 3
    if professor.preference_online and slot["mode"] != "online":
        penalty += 3
    return penalty


def compute_fitness(
    schedule: list[dict],
    professors: list,
    students: list,
    power_outage_schedule: list[str],
) -> int:
    """
    Scores a schedule. Lower = better.
    Hard violations: 500–1000 penalty. Soft: 3–25.
    Used by GA and SA.
    """
    total = 0

    for slot in schedule:
        if not lab_must_be_f2f(slot):       total += 1000
        if not valid_time_bounds(slot):     total += 1000
        if not valid_location(slot):        total += 1000
        if not no_class_sunday(slot):       total += 1000

    for i in range(len(schedule)):
        for j in range(i + 1, len(schedule)):
            if not no_double_booking_professor(schedule[i], schedule[j]): total += 1000
            if not no_double_booking_room(schedule[i], schedule[j]):      total += 1000
            if not no_modality_mix(schedule[i], schedule[j]):             total += 500

    for prof in professors:
        prof_slots = [s for s in schedule if s["prof_id"] == prof.prof_id]
        for day in set(s["day"] for s in prof_slots):
            day_slots = [s for s in prof_slots if s["day"] == day]
            total += break_duration_score(day_slots)
            total += modality_switch_gap_score(day_slots)
            if day_slots:
                total += professor_preference_score(day_slots[0], prof)

    for slot in schedule:
        total += power_outage_relocation_score(slot, power_outage_schedule)

    for student in students:
        if student.status == "irregular":
            for slot in schedule:
                total += irregular_priority_score(slot, student.__dict__)

    return total


# ─────────────────────────────────────────
# HARD CONSTRAINT CHECKS
# ─────────────────────────────────────────

def check_lab_lec_pairs(schedule: list[dict]) -> list[str]:
    """
    Hard constraint: For every course that was split into a __lab and __lec
    component, both must be:
      1. On the same day.
      2. Back-to-back (gap ≤ 30 min).
    """
    from csp_mcv import get_lab_lec_partner, is_lab_component, lab_lec_are_adjacent

    violations = []
    checked_pairs = set()

    for slot in schedule:
        cid = slot["course_id"]
        if not is_lab_component(cid):
            continue
        partner_key = get_lab_lec_partner(cid)
        if partner_key is None or partner_key in checked_pairs:
            continue
        checked_pairs.add(cid)
        checked_pairs.add(partner_key)

        partner_slot = next(
            (s for s in schedule if s["course_id"] == partner_key), None
        )
        if partner_slot is None:
            violations.append(
                f"[LAB_LEC_MISSING] {base_course_id(cid)} (block {slot.get('block','?')}): "
                f"lab component found but lecture component is missing."
            )
            continue

        if slot["day"] != partner_slot["day"]:
            violations.append(
                f"[LAB_LEC_DAY] {base_course_id(cid)} (block {slot.get('block','?')}): "
                f"lab on {slot['day']} but lecture on {partner_slot['day']} — must be same day."
            )
        elif not lab_lec_are_adjacent(slot, partner_slot):
            violations.append(
                f"[LAB_LEC_GAP] {base_course_id(cid)} (block {slot.get('block','?')}): "
                f"lab ends {slot['time_end']} but lecture starts {partner_slot['time_start']} — "
                f"gap exceeds 30 minutes."
            )

    return violations


def check_hard_constraints(schedule: list[dict]) -> list[str]:
    violations = []

    for slot in schedule:
        display_id = base_course_id(slot['course_id'])
        if not lab_must_be_f2f(slot):
            violations.append(f"[LAB_MODE] {display_id} on {slot['day']} is lab but not F2F.")
        if not valid_time_bounds(slot):
            violations.append(f"[TIME_BOUNDS] {display_id} on {slot['day']} is outside allowed hours.")
        if not valid_location(slot):
            violations.append(f"[LOCATION] {display_id} assigned to invalid room: {slot['room']}.")
        if not no_class_sunday(slot):
            violations.append(f"[SUNDAY] {display_id} scheduled on Sunday illegally.")

    for i in range(len(schedule)):
        for j in range(i + 1, len(schedule)):
            s1, s2 = schedule[i], schedule[j]
            d1, d2 = base_course_id(s1['course_id']), base_course_id(s2['course_id'])
            if not no_double_booking_professor(s1, s2):
                violations.append(
                    f"[PROF_CONFLICT] Prof {s1['prof_id']} double-booked: "
                    f"{d1} and {d2} on {s1['day']}."
                )
            if not no_double_booking_room(s1, s2):
                violations.append(
                    f"[ROOM_CONFLICT] Room {s1['room']} double-booked: "
                    f"{d1} and {d2} on {s1['day']}."
                )
            if not no_modality_mix(s1, s2):
                violations.append(
                    f"[MODALITY_MIX] {d1} and {d2} "
                    f"mix modality without 3-hour gap on {s1['day']}."
                )

    # Lab+lecture co-scheduling check
    violations.extend(check_lab_lec_pairs(schedule))

    return violations


# ─────────────────────────────────────────
# SOFT CONSTRAINT CHECKS
# ─────────────────────────────────────────

def check_soft_constraints(
    schedule: list[dict],
    professors: list,
    students: list,
    power_outage_schedule: list[str],
) -> list[str]:
    warnings = []

    for prof in professors:
        prof_slots = [s for s in schedule if s["prof_id"] == prof.prof_id]
        for day in set(s["day"] for s in prof_slots):
            day_slots = [s for s in prof_slots if s["day"] == day]
            if break_duration_score(day_slots) > 0:
                warnings.append(f"[BREAK] Prof {prof.prof_id} on {day} has insufficient breaks.")
            if modality_switch_gap_score(day_slots) > 0:
                warnings.append(f"[MODALITY_GAP] Prof {prof.prof_id} on {day} switches modality without 3hr gap.")
            if day_slots and professor_preference_score(day_slots[0], prof) > 0:
                warnings.append(f"[PREFERENCE] Prof {prof.prof_id} has slots against modality preference.")

    for slot in schedule:
        if power_outage_relocation_score(slot, power_outage_schedule) > 0:
            warnings.append(
                f"[POWER_OUTAGE] {base_course_id(slot['course_id'])} on {slot['day']} needs relocation "
                f"(room={slot['room']})."
            )

    for student in students:
        if student.status == "irregular":
            for slot in schedule:
                if irregular_priority_score(slot, student.__dict__) > 0:
                    warnings.append(
                        f"[IRREGULAR] {student.name}: retaken course "
                        f"{base_course_id(slot['course_id'])} "
                        f"may not be adjacent to year-level courses."
                    )

    return warnings


# ─────────────────────────────────────────
# FULL CHECKER (entry point)
# ─────────────────────────────────────────

def run_checker(
    schedule: list[dict],
    professors: list,
    students: list,
    power_outage_schedule: list[str],
    verbose: bool = True,
) -> dict:
    hard_violations = check_hard_constraints(schedule)
    soft_warnings   = check_soft_constraints(schedule, professors, students, power_outage_schedule)

    if verbose:
        if not hard_violations:
            print("✅ All hard constraints passed.")
        else:
            print(f"❌ {len(hard_violations)} hard constraint violation(s):")
            for v in hard_violations:
                print(f"   {v}")
        if soft_warnings:
            print(f"ℹ️  {len(soft_warnings)} soft suggestion(s):")
            for w in soft_warnings:
                print(f"   {w}")
        else:
            print("✅ No soft suggestions.")

    return {
        "hard_violations": hard_violations,
        "soft_warnings":   soft_warnings,
        "soft_suggestions": soft_warnings,
        "passed":          len(hard_violations) == 0,
    }
