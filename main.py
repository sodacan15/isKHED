# main.py
# Wires all modules together and runs the full scheduling pipeline.
#
# Pipeline:
#   1. Load data (DB or Excel)
#   2. CSP + MCV → initial draft schedule
#   3. GA + SA   → refined schedule
#   4. Constraint check → validate
#   5. 2nd CSP run → schedule irregulars adjacent to their year-level classes
#   6. Final constraint check → output master list

import sys
from pathlib import Path

import pandas as pd

from database_access import load_all
from data_struct import MasterList, Assignment
from csp_mcv import build_csp, build_initial_schedule
from ga_sa import refine_schedule
from constraint_check import run_checker


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def generate_time_slots(
    start_min: int = 450,   # 7:30 AM (earliest online start)
    end_min:   int = 1260,  # 9:00 PM (latest online end)
    step:      int = 30,    # 30-minute granularity
) -> list[dict]:
    """
    Generates all possible time slot windows in 30-min increments.
    Durations range from 1 hour to 4 hours (matching CHED/CCIS rules).
    """
    slots = []
    for start in range(start_min, end_min, step):
        for duration in [60, 90, 120, 150, 180, 240]:  # 1h to 4h
            end = start + duration
            if end <= end_min:
                slots.append({"start": start, "end": end})
    return slots


def assignments_to_dicts(schedule: list) -> list[dict]:
    """Ensures every item in the schedule is a plain dict."""
    result = []
    for item in schedule:
        if isinstance(item, dict):
            result.append(item)
        elif isinstance(item, Assignment):
            result.append(item.to_dict())
    return result


def build_master_lists(schedule: list[dict]) -> dict[str, MasterList]:
    """Groups the final schedule into MasterList objects per block."""
    master_lists = {}
    for slot in schedule:
        raw_block = slot.get("block") or ""
        block = raw_block.strip() if raw_block.strip() else f"Year {slot.get('year_level', '?')}"
        if block not in master_lists:
            master_lists[block] = MasterList(block=block)
        master_lists[block].add(Assignment(**slot))
    return master_lists


def print_master_lists(master_lists: dict[str, MasterList]):
    """Prints the final schedule grouped by block and day."""
    days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    print("\n" + "=" * 60)
    print("📅  FINAL MASTER SCHEDULE")
    print("=" * 60)
    for block_code, master in sorted(master_lists.items()):
        print(f"\n🔷 Block: {block_code}")
        for day in days_order:
            slots = master.get_day(day)
            if not slots:
                continue
            print(f"  📆 {day}:")
            for s in slots:
                def fmt(m):
                    h, mn = divmod(m, 60)
                    p = "AM" if h < 12 else "PM"
                    h = h if h <= 12 else h - 12
                    h = 12 if h == 0 else h
                    return f"{h}:{mn:02d} {p}"
                label = "LAB" if s.is_lab else "LEC"
                print(
                    f"    [{fmt(s.time_start)}-{fmt(s.time_end)}] "
                    f"{s.course_id} | {label} | {s.mode.upper()} | "
                    f"Room: {s.room} | Prof: {s.prof_id}"
                )


def write_placeholder_excel(output_path: str):
    """Creates a fallback workbook when no input data is available."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    summary_df = pd.DataFrame([
        {
            "status": "No source data found",
            "message": "Provide a .xlsx or .db file, or run the script with a file path.",
        }
    ])
    instructions_df = pd.DataFrame([
        {
            "step": "1",
            "action": "Run: python main.py <path_to_data.xlsx or .db>",
        }
    ])

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        instructions_df.to_excel(writer, sheet_name="Instructions", index=False)


def save_schedule_to_excel(
    schedule: list[dict],
    master_lists: dict[str, MasterList],
    result: dict,
    output_path: str,
):
    """Exports the schedule and summary into an Excel workbook."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    def to_row(item: dict) -> dict:
        return {
            "course_id": item.get("course_id", ""),
            "prof_id": item.get("prof_id", ""),
            "room": item.get("room", ""),
            "day": item.get("day", ""),
            "time_start": item.get("time_start", ""),
            "time_end": item.get("time_end", ""),
            "mode": item.get("mode", ""),
            "is_lab": item.get("is_lab", False),
            "year_level": item.get("year_level", ""),
            "block": item.get("block", ""),
            "is_nstp": item.get("is_nstp", False),
        }

    schedule_df = pd.DataFrame([to_row(item) for item in schedule])
    summary_df = pd.DataFrame(
        [{
            "total_assignments": len(schedule),
            "hard_violations": len(result.get("hard_violations", [])),
            "soft_suggestions": len(result.get("soft_suggestions", result.get("soft_warnings", []))),
            "status": "PASSED" if result.get("passed") else "REQUIRES REVIEW",
        }]
    )

    # If the workbook is open in Excel, Windows may lock it.
    # Delete the old file first so the new one can be recreated safely.
    if output.exists():
        try:
            output.unlink()
        except PermissionError:
            print(f"Warning: could not overwrite {output} because it is open. Please close Excel and rerun.")
            return

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        schedule_df.to_excel(writer, sheet_name="All_Assignments", index=False)

        for block_code, master in sorted(master_lists.items()):
            block_rows = []
            for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]:
                for item in master.get_day(day):
                    block_rows.append({
                        "block": block_code,
                        "day": day,
                        "course_id": item.course_id,
                        "prof_id": item.prof_id,
                        "room": item.room,
                        "time_start": item.time_start,
                        "time_end": item.time_end,
                        "mode": item.mode,
                        "is_lab": item.is_lab,
                        "year_level": item.year_level,
                        "is_nstp": item.is_nstp,
                    })
            sheet_name = f"Block_{block_code.replace(' ', '_').replace('/', '_')}"
            pd.DataFrame(block_rows).to_excel(writer, sheet_name=sheet_name, index=False)


# ─────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────

def find_default_source(project_dir: Path) -> str | None:
    """Finds a real data source automatically if the user didn't pass one."""
    candidates = []
    for pattern in ("*.xlsx", "*.db"):
        candidates.extend(project_dir.rglob(pattern))

    # Prefer files in a data/ folder if present.
    data_dir = project_dir / "data"
    if data_dir.exists():
        for pattern in ("*.xlsx", "*.db"):
            candidates.extend(data_dir.rglob(pattern))

    for path in candidates:
        if not path.is_file():
            continue
        if path.name.lower() == "masterschedule.xlsx":
            continue
        if path.name.startswith("~$"):
            continue
        return str(path)
    return None


def run_pipeline(source: str):
    """
    Full scheduling pipeline.
    source: path to .db or .xlsx file.
    """

    # ── STEP 1: Load Data ──────────────────────────────────────
    print("\n📂 Step 1: Loading data...")
    data = load_all(source)

    professors         = data["professors"]
    courses            = data["courses"]
    rooms              = data["rooms"]
    blocks             = data["blocks"]
    students           = data["students"]
    power_outage       = data["power_outage"]

    print(f"   Professors : {len(professors)}")
    print(f"   Courses    : {len(courses)}")
    print(f"   Rooms      : {len(rooms)}")
    print(f"   Blocks     : {len(blocks)}")
    print(f"   Students   : {len(students)}")
    print(f"   Outage days: {power_outage}")

    time_slots = generate_time_slots()

    # Separate regular courses from irregular students' backlog courses
    regular_students  = [s for s in students if s.status == "regular"]
    irregular_students = [s for s in students if s.status == "irregular"]

    # Collect backlog course IDs (retaken courses, scheduled in 2nd CSP run)
    backlog_course_ids = set()
    for s in irregular_students:
        backlog_course_ids.update(s.backlog)

    # Split courses: main run vs irregular 2nd run
    main_courses     = [c for c in courses if c.course_id not in backlog_course_ids]
    backlog_courses  = [c for c in courses if c.course_id in backlog_course_ids]

    # ── STEP 2: CSP + MCV → Initial Draft ─────────────────────
    print("\n🔍 Step 2: CSP domain trimming + MCV greedy draft...")
    initial_schedule = build_initial_schedule(
        courses=main_courses,
        professors=professors,
        rooms=rooms,
        time_slots=time_slots,
    )
    initial_check = run_checker(
        schedule=assignments_to_dicts(initial_schedule),
        professors=professors,
        students=students,
        power_outage_schedule=power_outage,
        verbose=False,
    )
    print(
        f"   [Initial schedule] hard={len(initial_check['hard_violations'])} | "
        f"soft={len(initial_check['soft_warnings'])}"
    )

    # ── STEP 3: GA + SA → Refined Schedule ────────────────────
    print("\n🧬 Step 3: GA + SA refinement...")

    # Rebuild domains for GA/SA (needed for mutation/neighbor search)
    domains = build_csp(main_courses, professors, rooms, time_slots)

    refined_schedule = refine_schedule(
        base_schedule=initial_schedule,
        domains=domains,
        professors=professors,
        students=students,
        power_outage_schedule=power_outage,
    )
    refined_check = run_checker(
        schedule=assignments_to_dicts(refined_schedule),
        professors=professors,
        students=students,
        power_outage_schedule=power_outage,
        verbose=False,
    )
    print(
        f"   [Refined schedule] hard={len(refined_check['hard_violations'])} | "
        f"soft={len(refined_check['soft_warnings'])}"
    )

    # ── STEP 4: Constraint Check ───────────────────────────────
    print("\n✅ Step 4: Constraint validation...")
    result = run_checker(
        schedule=assignments_to_dicts(refined_schedule),
        professors=professors,
        students=students,
        power_outage_schedule=power_outage,
    )

    if not result["passed"]:
        print("\n❌ Hard constraint violations found. Review before proceeding.")
        print("   Violations:")
        for v in result["hard_violations"]:
            print(f"   - {v}")
        # Pipeline continues — GA/SA should have minimized these,
        # but manual review flag is raised per system design.

    # ── STEP 5: 2nd CSP Run → Irregulars ──────────────────────
    final_schedule = list(refined_schedule)

    if backlog_courses:
        print(f"\n🔄 Step 5: 2nd CSP run for {len(backlog_courses)} backlog course(s)...")
        irregular_schedule = build_initial_schedule(
            courses=backlog_courses,
            professors=professors,
            rooms=rooms,
            time_slots=time_slots,
            existing_schedule=assignments_to_dicts(refined_schedule),  # treated as constraints
            students=irregular_students,
        )
        irregular_check = run_checker(
            schedule=assignments_to_dicts(irregular_schedule),
            professors=professors,
            students=irregular_students,
            power_outage_schedule=power_outage,
            verbose=False,
        )
        print(
            f"   [Irregular draft] hard={len(irregular_check['hard_violations'])} | "
            f"soft={len(irregular_check['soft_warnings'])}"
        )

        # Refine irregular schedule too
        irr_domains = build_csp(
            backlog_courses,
            professors,
            rooms,
            time_slots,
            existing_schedule=assignments_to_dicts(refined_schedule),
            students=irregular_students,
        )

        refined_irregular = refine_schedule(
            base_schedule=irregular_schedule,
            domains=irr_domains,
            professors=professors,
            students=irregular_students,
            power_outage_schedule=power_outage,
        )
        final_schedule.extend(refined_irregular)
        irregular_final_check = run_checker(
            schedule=assignments_to_dicts(final_schedule),
            professors=professors,
            students=students,
            power_outage_schedule=power_outage,
            verbose=False,
        )
        print(
            f"   [After irregular merge] hard={len(irregular_final_check['hard_violations'])} | "
            f"soft={len(irregular_final_check['soft_warnings'])}"
        )
    else:
        print("\n⏭️  Step 5: No irregular backlog courses. Skipping 2nd CSP run.")

    # ── STEP 6: Final Constraint Check ────────────────────────
    print("\n✅ Step 6: Final constraint validation...")
    final_result = run_checker(
        schedule=assignments_to_dicts(final_schedule),
        professors=professors,
        students=students,
        power_outage_schedule=power_outage,
        verbose=True,
    )

    # ── STEP 7: Build + Display Master Lists ──────────────────
    print("\n📋 Step 7: Building master lists...")
    master_lists = build_master_lists(assignments_to_dicts(final_schedule))
    print_master_lists(master_lists)

    # ── DONE ───────────────────────────────────────────────────
    project_dir = Path(__file__).resolve().parent
    output_path = project_dir / "masterSchedule.xlsx"
    save_schedule_to_excel(
        schedule=assignments_to_dicts(final_schedule),
        master_lists=master_lists,
        result=final_result,
        output_path=str(output_path),
    )

    soft_suggestions = len(
        final_result.get("soft_suggestions", final_result.get("soft_warnings", []))
    )

    print("\n" + "=" * 60)
    status = "✅ PASSED" if final_result["passed"] else "❌ NEEDS REVIEW"
    print(f"🏁 Pipeline complete. Status: {status}")
    print(f"   Total assignments     : {len(final_schedule)}")
    print(f"   Hard violations       : {len(final_result['hard_violations'])}")
    print(f"   Soft suggestions       : {soft_suggestions}")
    print(f"   Excel report          : {output_path}")
    print("=" * 60)

    return {
        "schedule":     final_schedule,
        "master_lists": master_lists,
        "check_result": final_result,
        "output_path":  str(output_path),
    }


# ─────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────

if __name__ == "__main__":
    project_dir = Path(__file__).resolve().parent
    output_path = project_dir / "masterSchedule.xlsx"

    if len(sys.argv) >= 2:
        source_path = sys.argv[1]
    else:
        source_path = find_default_source(project_dir)

    if source_path is None:
        print("No input data file found.")
        print("Generating a placeholder output workbook instead.")
        write_placeholder_excel(str(output_path))
        print(f"Excel report      : {output_path}")
    else:
        print(f"Using input source: {source_path}")
        run_pipeline(source_path)