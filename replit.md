# IskHED — Automated Class Scheduling System

An automated academic scheduling system for the Polytechnic University of the Philippines – College of Computer and Information Sciences (PUP CCIS), built with a hybrid CSP + Genetic Algorithm + Simulated Annealing pipeline.

## Running the app

```bash
streamlit run UI.py
```

## Project structure

```
UI.py                 # Streamlit admin dashboard (entry point)
main.py               # Full scheduling pipeline orchestrator
csp_mcv.py            # CSP domain builder + MCV greedy scheduler + conflict resolver
constraint_check.py   # Hard and soft constraint validator + fitness scorer
ga_sa.py              # Genetic Algorithm + Simulated Annealing refinement
database_access.py    # Excel / SQLite data loaders
data_struct.py        # Core data models (Professor, Course, Room, Block, Student, Assignment)
inputSheet.xlsx       # Sample input constraints file
requirements.txt      # Python dependencies
.streamlit/config.toml
```

## Input format

Upload an `inputSheet.xlsx` file with the following sheets:
- **Professors** — prof_id, name, days_available, f2f_start/end, online_start/end, days_f2f, preference_online, preference_f2f, subjects_handled
- **Courses** — course_id, mode, has_lab, has_lec, time_for_lab, time_for_lec, year_level, units, college_name, hour_allocation
- **Rooms** — location_code, location_map, capacity, available_days
- **Blocks** — year_level, block_code, amount_of_students, classes
- **Students** — name, year_level, block, status, backlog, courses
- **PowerOutage** — day

## Output

Generates `masterSchedule.xlsx` with:
- **Summary** sheet — total assignments, hard violations, soft suggestions, status
- **All_Assignments** sheet — full flat schedule used by the UI
- **Block_\*** sheets — one sheet per block with day-by-day layout

## Deploying to Streamlit Cloud

1. Push this repository to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io) and connect the repo
3. Set the main file path to `UI.py`
4. No secrets or environment variables required

## User preferences

- Keep constraint logic in `csp_mcv.py`; keep checker/fitness in `constraint_check.py`
- Room codes: `4th_east_wing` expands to `E401–E417`, `5th_south_wing` expands to `S501–S514` via `database_access.expand_rooms()`
- Constraint helpers must handle both original and expanded room codes
