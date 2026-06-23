"""
migrate_master_to_input.py

The masterSchedule.xlsx does NOT store constraint sheets — those only
live in inputSheet.xlsx. So migration simply verifies inputSheet.xlsx
is already present and usable. If a companion inputSheet is found, we
leave it as-is. If not, we raise a clear error so the user knows they
need to supply one.

Why not reconstruct from All_Assignments?
  The assignments sheet lacks critical constraint detail: professor
  availability windows, room capacity, student rosters, irregular
  student backlogs, etc. Reconstructing would lose that info and likely
  cause the algo to produce a degraded schedule.
"""

import os
import shutil
import pandas as pd

REQUIRED_SHEETS = ["Professors", "Courses", "Rooms", "Blocks", "Students", "PowerOutage"]


def migrate(master_path: str, output_path: str = "inputSheet.xlsx") -> dict:
    """
    Ensures a valid inputSheet.xlsx exists at output_path before the algo runs.

    Strategy (in order):
    1. If inputSheet.xlsx already exists on disk and has all required sheets → use it as-is.
    2. If the masterSchedule itself contains all required sheets → copy them out.
    3. Otherwise → raise a clear error.
    """

    # ── Strategy 1: inputSheet already on disk ────────────────────────────────
    if os.path.exists(output_path):
        try:
            existing_sheets = pd.ExcelFile(output_path).sheet_names
            if all(s in existing_sheets for s in REQUIRED_SHEETS):
                counts = {}
                for sheet in REQUIRED_SHEETS:
                    df = pd.read_excel(output_path, sheet_name=sheet)
                    counts[sheet] = len(df)
                return counts
        except Exception:
            pass  # fall through to next strategy

    # ── Strategy 2: master contains constraint sheets ─────────────────────────
    try:
        master_sheets = pd.ExcelFile(master_path).sheet_names
        if all(s in master_sheets for s in REQUIRED_SHEETS):
            counts = {}
            with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
                for sheet in REQUIRED_SHEETS:
                    df = pd.read_excel(master_path, sheet_name=sheet)
                    df.to_excel(writer, sheet_name=sheet, index=False)
                    counts[sheet] = len(df)
            return counts
    except Exception:
        pass

    # ── Strategy 3: nothing usable found ─────────────────────────────────────
    raise FileNotFoundError(
        "Cannot re-run the algorithm: no valid inputSheet.xlsx was found on disk, "
        "and the imported masterSchedule does not contain the constraint sheets "
        "(Professors, Courses, Rooms, Blocks, Students, PowerOutage).\n\n"
        "Please upload the original inputSheet.xlsx via the top sidebar uploader "
        "and click 'Generate Schedule' instead."
    )
