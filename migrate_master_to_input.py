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
                # Write empty sheet so the algo doesn't crash on a missing tab
                pd.DataFrame().to_excel(writer, sheet_name=sheet, index=False)
                counts[sheet] = 0

    return counts
