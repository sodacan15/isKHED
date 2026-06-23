"""
migrate_master_to_input.py
Copies the constraint sheets already stored in masterSchedule.xlsx
directly into a new inputSheet.xlsx — no inference needed.
"""
import pandas as pd

INPUT_SHEETS = ["Professors", "Courses", "Rooms", "Blocks", "Students", "PowerOutage"]

def migrate(master_path: str, output_path: str = "inputSheet.xlsx") -> dict:
    wb = pd.ExcelFile(master_path)
    available = wb.sheet_names

    counts = {}
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet in INPUT_SHEETS:
            if sheet in available:
                df = pd.read_excel(master_path, sheet_name=sheet)
                df.to_excel(writer, sheet_name=sheet, index=False)
                counts[sheet] = len(df)
            else:
                # Write empty sheet with correct headers so the algo doesn't crash
                EMPTY_SCHEMAS = {
                    "Professors":  ["prof_id","name","days_available","f2f_start","f2f_end","online_start","online_end","days_f2f","preference_online","preference_f2f","subjects_handled"],
                    "Courses":     ["course_id","mode","has_lab","has_lec","time_for_lab","time_for_lec","year_level","units","college_name","hour_allocation"],
                    "Rooms":       ["location_code","location_map","capacity","available_days"],
                    "Blocks":      ["year_level","block_code","amount_of_students","classes"],
                    "Students":    ["name","year_level","block","status","backlog","courses"],
                    "PowerOutage": ["day"],
                }
                pd.DataFrame(columns=EMPTY_SCHEMAS.get(sheet, [])).to_excel(writer, sheet_name=sheet, index=False)
                counts[sheet] = 0

    return counts
