import streamlit as st
import pandas as pd
import subprocess
import os
import re

st.set_page_config(page_title="IskHED Admin", layout="wide", initial_sidebar_state="expanded")

# ==========================================
# CONSTANTS
# ==========================================
DAYS_OF_WEEK   = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
TIME_BINS      = list(range(420, 1290, 30))
TIME_LABELS    = []
for _t in TIME_BINS:
    _h, _m = divmod(_t, 60)
    _p = "AM" if _h < 12 else "PM"
    _h12 = _h % 12; _h12 = 12 if _h12 == 0 else _h12
    TIME_LABELS.append(f"{_h12}:{_m:02d} {_p}")

# CHED max teaching load per week in hours
CHED_MAX_HOURS    = 21      # hard cap — cannot exceed
CHED_WARN_HOURS   = 18      # soft warning threshold

DURATION_OPTIONS  = {
    "1h":      60,
    "1h 30m":  90,
    "2h":     120,
    "2h 30m": 150,
    "3h":     180,
    "4h":     240,
}

# Valid F2F room options by type
LAB_ROOMS = [f"S5{i:02d}" for i in range(1, 15)] + ["lab_room"]
LEC_ROOMS = [f"E4{i:02d}" for i in range(1, 18)] + ["gymnasium"]

# Course-color palette
COURSE_COLORS = [
    "#C62828","#1565C0","#2E7D32","#6A1B9A","#E65100",
    "#00695C","#4527A0","#AD1457","#0277BD","#558B2F",
    "#6D4C41","#37474F","#BF360C","#01579B","#33691E",
    "#880E4F","#4E342E","#1A237E","#004D40","#F57F17",
    "#263238","#FF6F00","#0D47A1","#1B5E20","#4A148C",
]


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def format_minutes(minutes):
    try:
        m_int = int(minutes)
        h, mn = divmod(m_int, 60)
        p = "AM" if h < 12 else "PM"
        h12 = h % 12; h12 = 12 if h12 == 0 else h12
        return f"{h12}:{mn:02d} {p}"
    except:
        return minutes


def parse_time_to_minutes(val):
    if isinstance(val, (int, float)) and not pd.isna(val):
        return int(val)
    try:
        return int(float(str(val)))
    except:
        pass
    match = re.match(r'(\d+):(\d+)\s*(AM|PM)', str(val).strip().upper())
    if match:
        h, m, period = int(match.group(1)), int(match.group(2)), match.group(3)
        if period == "PM" and h != 12:
            h += 12
        elif period == "AM" and h == 12:
            h = 0
        return h * 60 + m
    return val


def format_room_name(name):
    if not isinstance(name, str):
        return name
    if len(name) >= 4 and name[0] in ("E", "S") and name[1].isdigit():
        wing = "East Wing" if name[0] == "E" else "South Wing"
        return f"{wing} {name}"
    formatted = name.replace("_", " ").title()
    fixes = {"1St":"1st","2Nd":"2nd","3Rd":"3rd","4Th":"4th","5Th":"5th","6Th":"6th"}
    for w, r in fixes.items():
        formatted = formatted.replace(w, r)
    return formatted


def strip_wing_prefix(display_name: str) -> str:
    """'East Wing E401' → 'E401'"""
    for prefix in ("East Wing ", "South Wing "):
        if display_name.startswith(prefix):
            return display_name[len(prefix):]
    return display_name


def get_course_color_map(df: pd.DataFrame) -> dict:
    courses = sorted(df["course_id"].dropna().unique().tolist())
    return {c: COURSE_COLORS[i % len(COURSE_COLORS)] for i, c in enumerate(courses)}


def make_style_fn(course_color_map: dict):
    def style_timetable(val):
        if val != "":
            cid = str(val).split("|")[0].strip()
            color = course_color_map.get(cid, "#880000")
            return (
                f"background-color: {color}; color: #FFFFFF; font-weight: 700; "
                f"border: 1px solid rgba(255,255,255,0.25); text-align: center;"
            )
        return "background-color: #FFFFFF; color: #333333; border: 1px solid #E0E0E0;"
    return style_timetable


def render_legend(course_color_map: dict):
    if not course_color_map:
        return
    st.markdown("**🎨 Course Legend**")
    items_html = "".join(
        f"<span style='background:{color}; color:#fff; padding:4px 12px; "
        f"border-radius:6px; font-weight:700; margin:3px; display:inline-block;'>"
        f"{course}</span>"
        for course, color in course_color_map.items()
    )
    st.markdown(f"<div style='line-height:2.2;'>{items_html}</div>", unsafe_allow_html=True)


def build_timetable_grid(df_filtered, cell_fn):
    grid = pd.DataFrame("", index=TIME_LABELS, columns=DAYS_OF_WEEK)
    for _, row in df_filtered.iterrows():
        day = row.get("day")
        if day not in DAYS_OF_WEEK:
            continue
        try:
            start = int(row["time_start"])
            end   = int(row["time_end"])
            text  = cell_fn(row)
            for t, t_label in zip(TIME_BINS, TIME_LABELS):
                if start <= t < end:
                    if grid.at[t_label, day] == "":
                        grid.at[t_label, day] = text
                    else:
                        grid.at[t_label, day] += f"\n🛑 {text}"
        except Exception:
            pass
    return grid


# ==========================================
# WORKLOAD HELPERS
# ==========================================

def compute_professor_workload(df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns a DataFrame: prof_id | hours_assigned | status
    Hours = sum((time_end - time_start) / 60) per professor.
    """
    if "prof_id" not in df.columns:
        return pd.DataFrame()
    rows = []
    for prof_id, grp in df.groupby("prof_id"):
        mins = 0
        for _, r in grp.iterrows():
            try:
                mins += int(r["time_end"]) - int(r["time_start"])
            except:
                pass
        hours = mins / 60
        if hours > CHED_MAX_HOURS:
            status = "🔴 Over limit"
        elif hours >= CHED_WARN_HOURS:
            status = "🟡 Near limit"
        else:
            status = "🟢 OK"
        rows.append({"prof_id": prof_id, "hours": round(hours, 1), "status": status})
    return pd.DataFrame(rows).sort_values("hours", ascending=False).reset_index(drop=True)


def prof_hours_from_df(df: pd.DataFrame, prof_id: str, exclude_idx: int = None) -> float:
    sub = df[df["prof_id"] == prof_id]
    if exclude_idx is not None:
        sub = sub.drop(index=exclude_idx, errors="ignore")
    mins = 0
    for _, r in sub.iterrows():
        try:
            mins += int(r["time_end"]) - int(r["time_start"])
        except:
            pass
    return mins / 60


def check_conflicts(df: pd.DataFrame, changed_idx: int, new_row: dict) -> list[str]:
    """
    Returns a list of conflict strings if new_row would violate hard constraints
    against any other row in df (ignoring changed_idx itself).
    """
    issues = []
    others = df.drop(index=changed_idx, errors="ignore")

    new_start = int(new_row.get("time_start", 0))
    new_end   = int(new_row.get("time_end",   0))
    new_day   = new_row.get("day", "")
    new_prof  = new_row.get("prof_id", "")
    new_room  = new_row.get("room", "")
    new_mode  = new_row.get("mode", "")
    is_lab    = bool(new_row.get("is_lab", False))
    course    = new_row.get("course_id", "?")

    def overlaps(r):
        if r.get("day") != new_day:
            return False
        rs, re_ = int(r.get("time_start", 0)), int(r.get("time_end", 0))
        return new_start < re_ and rs < new_end

    for _, r in others.iterrows():
        if r.get("prof_id") == new_prof and overlaps(r):
            issues.append(f"Prof **{new_prof}** is already teaching **{r.get('course_id','?')}** on {new_day} at that time.")
        if r.get("room") == new_room and new_mode == "f2f" and overlaps(r):
            issues.append(f"Room **{new_room}** is already occupied by **{r.get('course_id','?')}** on {new_day} at that time.")

    # Time bounds
    if new_mode == "f2f" and (new_start < 480 or new_end > 1200):
        issues.append("F2F classes must be between **8:00 AM and 8:00 PM**.")
    if new_mode == "online" and (new_start < 450 or new_end > 1260):
        issues.append("Online classes must be between **7:30 AM and 9:00 PM**.")

    # Lab room constraint
    if is_lab and new_mode == "f2f":
        if not (new_room.startswith("S5") or new_room == "lab_room"):
            issues.append("Lab classes must be in the **5th Floor South Wing** or lab room.")

    # Lec room constraint
    if not is_lab and new_mode == "f2f":
        if not (new_room.startswith("E4") or new_room == "gymnasium"):
            issues.append("Lecture classes must be in the **4th Floor East Wing** or gymnasium.")

    return issues


# ==========================================
# CSS STYLING
# ==========================================
st.markdown("""
<style>
#MainMenu {visibility:hidden;}
footer {visibility:hidden;}
.stAppDeployButton {display:none;}

:root{
    --pup-maroon:#880000;
    --pup-dark:#660000;
    --pup-gold:#FFD700;
    --text-dark:#333333;
}

header { background-color: var(--pup-maroon) !important; }
[data-testid="stHeader"]{ background-color: var(--pup-maroon) !important; }
.stApp{ background-color:#F5F5F5 !important; }
[data-testid="stSidebar"]{ background-color:var(--pup-dark) !important; }

[data-testid="stAppViewContainer"] h1,
[data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3,
[data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] label,
[data-testid="stMetricValue"] div { color: var(--text-dark) !important; }
[data-testid="stMetricLabel"] p { color: #555555 !important; font-weight: 600 !important; }

.custom-header h1, .custom-header span { color: white !important; font-size:64px !important; font-weight:900 !important; }
.custom-header p { color: var(--pup-gold) !important; font-size:20px !important; font-weight:600 !important; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3,
[data-testid="stSidebar"] p, [data-testid="stSidebar"] label, [data-testid="stSidebar"] span { color: white !important; }

div[data-testid="stFileUploaderDropzone"]{ background-color:#111827 !important; border:1px solid #444 !important; border-radius:12px !important; }
div[data-testid="stFileUploaderDropzone"] * { color: white !important; }
div.stButton > button:first-child{ background-color:var(--pup-gold) !important; border:none !important; border-radius:12px !important; height:50px !important; }
div.stButton > button:first-child * { color:var(--pup-dark) !important; font-weight:700 !important; font-size:16px !important; }
div.stButton > button:first-child:hover{ background-color:#FFF2A8 !important; transform:translateY(-1px); }

[data-testid="stUploadedFile"] * { color: var(--text-dark) !important; font-weight: 600 !important; }
[data-testid="stFileUploaderFile"] * { color: var(--text-dark) !important; font-weight: 600 !important; }

.custom-header{ background:linear-gradient(135deg, #880000, #AA0000); border-radius:15px; padding:35px; margin-bottom:25px; box-shadow: 0px 4px 12px rgba(0,0,0,0.15); }
[data-testid="stAlert"]{ border-radius:12px !important; }
[data-testid="stDataFrame"]{ border-radius:10px; overflow:hidden; }

.workload-bar-wrap{ background:#e0e0e0; border-radius:8px; height:14px; width:100%; margin:4px 0 8px 0; }
.workload-bar{ height:14px; border-radius:8px; }
.edit-card{ background:#FFFFFF; border:1.5px solid #E0E0E0; border-radius:14px; padding:20px 24px; margin-bottom:16px; box-shadow:0 2px 8px rgba(0,0,0,0.06); }
</style>
""", unsafe_allow_html=True)

# ==========================================
# HEADER
# ==========================================
st.markdown("""
<div class="custom-header">
    <h1>IskHED</h1>
    <p>
        An Automated Scheduling System for Polytechnic University of the Philippines
        <br>
        College of Computer and Information Sciences (PUP CCIS)
    </p>
</div>
""", unsafe_allow_html=True)

# ==========================================
# SESSION STATE
# ==========================================
if "schedule_generated" not in st.session_state:
    st.session_state.schedule_generated = False
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Master Schedule"
if "edit_idx" not in st.session_state:
    st.session_state.edit_idx = None
# Undo/redo history: list of {"df": DataFrame, "label": str, "ts": str}
if "edit_history" not in st.session_state:
    st.session_state.edit_history = []
if "history_idx" not in st.session_state:
    st.session_state.history_idx = -1   # -1 = nothing in history yet

MAX_HISTORY = 20


def push_history(df: pd.DataFrame, label: str):
    """
    Snapshot the current DataFrame into the undo stack.
    Discards any redo entries above the current pointer.
    """
    import datetime
    snapshot = {
        "df":    df.copy(),
        "label": label,
        "ts":    datetime.datetime.now().strftime("%H:%M:%S"),
    }
    # Trim future entries if user undid then made a new change
    st.session_state.edit_history = st.session_state.edit_history[: st.session_state.history_idx + 1]
    st.session_state.edit_history.append(snapshot)
    # Keep at most MAX_HISTORY snapshots
    if len(st.session_state.edit_history) > MAX_HISTORY:
        st.session_state.edit_history = st.session_state.edit_history[-MAX_HISTORY:]
    st.session_state.history_idx = len(st.session_state.edit_history) - 1


def write_df_to_excel(df: pd.DataFrame, path: str):
    """Write updated df to masterSchedule.xlsx preserving Summary sheet."""
    try:
        existing_summary = pd.read_excel(path, sheet_name="Summary")
    except Exception:
        existing_summary = None
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        if existing_summary is not None:
            existing_summary.to_excel(writer, sheet_name="Summary", index=False)
        df.to_excel(writer, sheet_name="All_Assignments", index=False)

# ==========================================
# SIDEBAR
# ==========================================
st.sidebar.markdown("### 📌 Navigation Menu")
st.sidebar.divider()

if st.sidebar.button("📊 Master Schedule", use_container_width=True):
    st.session_state.active_tab = "Master Schedule"
if st.sidebar.button("🏢 Room Allocations", use_container_width=True):
    st.session_state.active_tab = "Room Allocations"
if st.sidebar.button("⚠️ Manual Adjustments", use_container_width=True):
    st.session_state.active_tab = "Manual Adjustments"

if st.session_state.schedule_generated:
    st.sidebar.markdown("<br>", unsafe_allow_html=True)
    master_path_sidebar = "masterSchedule.xlsx"
    if os.path.exists(master_path_sidebar):
        with open(master_path_sidebar, "rb") as _f_sidebar:
            st.sidebar.download_button(
                "⬇️ Export Master Schedule (.xlsx)",
                _f_sidebar,
                "masterSchedule.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
    st.sidebar.markdown("<br>", unsafe_allow_html=True)
    if st.sidebar.button("🗑️ Delete Generation", use_container_width=True):
        st.session_state.schedule_generated = False
        st.rerun()

# ==========================================
# UPLOAD & GENERATE
# ==========================================
st.markdown("### ⚙️ System Parameters")
st.write("Upload the latest constraints to generate the schedule.")

upload_col, btn_col = st.columns([3, 1])
with upload_col:
    uploaded_file = st.file_uploader("Upload inputSheet.xlsx", type=["xlsx"], label_visibility="collapsed")
with btn_col:
    st.markdown("<div style='margin-top: 2px;'></div>", unsafe_allow_html=True)
    run_algorithms = st.button("Generate Schedule", use_container_width=True)

if run_algorithms:
    if uploaded_file is not None:
        with st.spinner("Running the Algorithm... Please wait."):
            with open("inputSheet.xlsx", "wb") as f:
                f.write(uploaded_file.getbuffer())
            subprocess.run(["python", "main.py"])
            st.session_state.schedule_generated = True
            st.session_state.edit_idx = None
        st.success("✨ Schedule finalized successfully!")
    else:
        st.error("Please upload the input constraints file first.")
        st.session_state.schedule_generated = False

st.divider()


# ==========================================
# VIEW 1: MASTER SCHEDULE
# ==========================================
if st.session_state.active_tab == "Master Schedule":
    st.subheader("Firm Master Schedules")

    master_path = "masterSchedule.xlsx"
    if st.session_state.schedule_generated and os.path.exists(master_path):
        try:
            df_raw = pd.read_excel(master_path, sheet_name="All_Assignments")
            if "room" in df_raw.columns:
                df_raw["room"] = df_raw["room"].apply(format_room_name)

            prof_cols  = [c for c in df_raw.columns if any(k in c.lower() for k in ("prof","instructor","faculty"))]
            block_cols = [c for c in df_raw.columns if any(k in c.lower() for k in ("block","section"))]
            prof_col_name  = prof_cols[0]  if prof_cols  else None
            block_col_name = block_cols[0] if block_cols else None

            course_color_map = get_course_color_map(df_raw)

            schedule_view = st.radio(
                "Generate Firm Schedule For:",
                ["Students (By Block)", "Professors"],
                horizontal=True,
            )

            df_filtered = df_raw

            if schedule_view == "Students (By Block)" and block_col_name:
                block_list = ["All Blocks"] + sorted(df_raw[block_col_name].dropna().unique().tolist())
                selected_entity = st.selectbox("🔍 Select Block/Section:", block_list)
                if selected_entity != "All Blocks":
                    df_filtered = df_raw[df_raw[block_col_name] == selected_entity]
                    st.markdown(f"### 🎓 Official Schedule: {selected_entity}")

            elif schedule_view == "Professors" and prof_col_name:
                prof_list = ["All Professors"] + sorted(df_raw[prof_col_name].dropna().unique().tolist())
                selected_entity = st.selectbox("🔍 Select Professor:", prof_list)
                if selected_entity != "All Professors":
                    df_filtered = df_raw[df_raw[prof_col_name] == selected_entity]
                    st.markdown(f"### 👨‍🏫 Official Schedule: {selected_entity}")

            def student_cell(row):
                course = str(row.get("course_id",""))
                prof   = str(row.get(prof_col_name,"")) if prof_col_name else ""
                room   = str(row.get("room",""))
                return f"{course} | {prof} | {room}"

            def prof_cell(row):
                course = str(row.get("course_id",""))
                block  = str(row.get(block_col_name,"")) if block_col_name else ""
                room   = str(row.get("room",""))
                return f"{course} | {block} | {room}"

            cell_fn  = student_cell if schedule_view == "Students (By Block)" else prof_cell
            grid_df  = build_timetable_grid(df_filtered, cell_fn)
            style_fn = make_style_fn(course_color_map)

            try:
                styled = grid_df.style.map(style_fn)
            except AttributeError:
                styled = grid_df.style.applymap(style_fn)

            st.dataframe(styled, use_container_width=True, height=500)
            render_legend(course_color_map)

            st.markdown("### 📋 Detailed Records")
            df_table = df_filtered.copy()
            if "time_start" in df_table.columns:
                df_table["time_start"] = df_table["time_start"].apply(format_minutes)
            if "time_end" in df_table.columns:
                df_table["time_end"] = df_table["time_end"].apply(format_minutes)
            st.dataframe(df_table, use_container_width=True, height=350)

            with open(master_path, "rb") as f_dl:
                st.download_button(
                    "⬇️ Download Master Schedule",
                    f_dl,
                    "masterSchedule.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

        except Exception as e:
            st.warning(f"Could not load master schedule. Error: {e}")
    else:
        st.info("Upload the input file and click 'Generate Schedule' to view the timetable.")


# ==========================================
# VIEW 2: ROOM ALLOCATIONS
# ==========================================
elif st.session_state.active_tab == "Room Allocations":
    st.subheader("Room Occupancy Matrix")

    master_path = "masterSchedule.xlsx"
    if st.session_state.schedule_generated and os.path.exists(master_path):
        try:
            df_raw_rooms = pd.read_excel(master_path, sheet_name="All_Assignments")
            if "room" in df_raw_rooms.columns:
                df_raw_rooms["room"] = df_raw_rooms["room"].apply(format_room_name)

            room_cols = [c for c in df_raw_rooms.columns if any(k in c.lower() for k in ("room","location"))]
            prof_cols = [c for c in df_raw_rooms.columns if any(k in c.lower() for k in ("prof","instructor","faculty"))]
            course_color_map = get_course_color_map(df_raw_rooms)

            if room_cols:
                room_col_name = room_cols[0]
                room_list = ["All Rooms"] + sorted(df_raw_rooms[room_col_name].dropna().unique().tolist())
                selected_room = st.selectbox(f"🏫 Check Occupancy for Room:", room_list)
                df_room_filtered = (
                    df_raw_rooms[df_raw_rooms[room_col_name] == selected_room]
                    if selected_room != "All Rooms"
                    else df_raw_rooms
                )
            else:
                df_room_filtered = df_raw_rooms
                selected_room = "All Rooms"

            st.markdown("### 🗓️ Visual Room Occupancy")

            def room_cell(row):
                course = str(row.get("course_id",""))
                room   = str(row.get("room",""))
                prof   = str(row.get(prof_cols[0],"")) if prof_cols else ""
                return f"{course} | {prof}" if selected_room != "All Rooms" else f"{course} | {room}"

            grid_rooms = build_timetable_grid(df_room_filtered, room_cell)
            style_fn   = make_style_fn(course_color_map)

            try:
                styled_rooms = grid_rooms.style.map(style_fn)
            except AttributeError:
                styled_rooms = grid_rooms.style.applymap(style_fn)

            st.dataframe(styled_rooms, use_container_width=True, height=500)
            render_legend(course_color_map)

            st.markdown("### 📋 Room Assignment Details")
            df_room_table = df_room_filtered.copy()
            if "time_start" in df_room_table.columns:
                df_room_table["time_start"] = df_room_table["time_start"].apply(format_minutes)
            if "time_end" in df_room_table.columns:
                df_room_table["time_end"] = df_room_table["time_end"].apply(format_minutes)
            st.dataframe(df_room_table, use_container_width=True, height=250)

        except Exception as e:
            st.warning("Room data not available. Please generate the schedule first.")
    else:
        st.info("Generate a schedule to view room allocations.")


# ==========================================
# VIEW 3: MANUAL ADJUSTMENTS (full HCI redesign)
# ==========================================
elif st.session_state.active_tab == "Manual Adjustments":
    st.subheader("System Health & Manual Overrides")

    master_path = "masterSchedule.xlsx"
    if not (st.session_state.schedule_generated and os.path.exists(master_path)):
        st.info("Generate a schedule to access manual override tools.")
        st.stop()

    # ── Load data ──────────────────────────────────────────────────────────────
    try:
        df_edit = pd.read_excel(master_path, sheet_name="All_Assignments")
    except Exception as e:
        st.error(f"Cannot load schedule: {e}")
        st.stop()

    # Keep raw integer times internally; display only uses format_minutes()
    for tcol in ("time_start", "time_end"):
        if tcol in df_edit.columns:
            df_edit[tcol] = df_edit[tcol].apply(parse_time_to_minutes)

    # ── SECTION A: Algorithm Status ───────────────────────────────────────────
    try:
        df_summary = pd.read_excel(master_path, sheet_name="Summary")
        st.markdown("### 📊 Algorithm Status Report")
        if not df_summary.empty:
            metric_cols = st.columns(len(df_summary.columns))
            for i, col in enumerate(df_summary.columns):
                metric_cols[i].metric(
                    label=col.replace("_", " ").title(),
                    value=str(df_summary.iloc[0][col]),
                )
        st.divider()
    except Exception:
        pass

    # ── SECTION B: Professor Workload Dashboard ───────────────────────────────
    st.markdown("### 👨‍🏫 Professor Workload Dashboard")
    st.caption(f"CHED limit: ⚠️ {CHED_WARN_HOURS}h soft warning · 🔴 {CHED_MAX_HOURS}h hard cap")

    wl_df = compute_professor_workload(df_edit)
    if not wl_df.empty:
        wl_cols = st.columns(min(len(wl_df), 4))
        for i, (_, wrow) in enumerate(wl_df.iterrows()):
            col_idx = i % 4
            pct = min(wrow["hours"] / CHED_MAX_HOURS, 1.0)
            bar_color = (
                "#D32F2F" if wrow["hours"] > CHED_MAX_HOURS else
                "#F9A825" if wrow["hours"] >= CHED_WARN_HOURS else
                "#2E7D32"
            )
            wl_cols[col_idx].markdown(
                f"""
                <div style="background:#fff; border:1.5px solid #e0e0e0; border-radius:12px;
                            padding:12px 14px; margin-bottom:8px;">
                  <div style="font-weight:700; font-size:14px; color:#333;">{wrow['prof_id']}</div>
                  <div style="font-size:12px; color:#666; margin-bottom:4px;">
                      {wrow['hours']}h / {CHED_MAX_HOURS}h &nbsp; {wrow['status']}
                  </div>
                  <div class="workload-bar-wrap">
                    <div class="workload-bar"
                         style="width:{int(pct*100)}%; background:{bar_color};"></div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            # Rebuild columns every 4
            if col_idx == 3 and i < len(wl_df) - 1:
                wl_cols = st.columns(4)
    else:
        st.info("No professor data found in schedule.")

    st.divider()

    # ── SECTION C: Smart Assignment Editor ────────────────────────────────────
    st.markdown("### ✏️ Smart Assignment Editor")
    st.caption(
        "Select an assignment below to edit it. "
        "All fields are constrained — the system will alert you before saving any invalid change."
    )

    if df_edit.empty:
        st.info("No assignments to edit.")
        st.stop()

    # Build human-readable labels for each row
    def make_label(row):
        ts = format_minutes(row.get("time_start", ""))
        te = format_minutes(row.get("time_end",   ""))
        return (
            f"{row.get('course_id','?')} | Block {row.get('block','?')} | "
            f"{row.get('day','?')} {ts}–{te} | {row.get('prof_id','?')} | {row.get('room','?')}"
        )

    labels = ["— Select an assignment to edit —"] + [
        make_label(r) for _, r in df_edit.iterrows()
    ]
    indices = [None] + list(df_edit.index)

    chosen_label = st.selectbox(
        "📋 Assignment to edit:",
        labels,
        index=0,
        key="assignment_selector",
    )
    chosen_idx = indices[labels.index(chosen_label)]

    if chosen_idx is None:
        st.markdown(
            "<div style='background:#f0f4ff; border:1.5px solid #c5cae9; border-radius:12px; "
            "padding:18px 20px; color:#333; font-size:15px; margin-top:8px;'>"
            "👆 Select an assignment above to open the constrained editor."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        row = df_edit.loc[chosen_idx].to_dict()
        is_lab  = bool(row.get("is_lab", False))
        is_nstp = bool(row.get("is_nstp", False))
        cur_mode = str(row.get("mode", "f2f")).lower()

        st.markdown(
            f"<div style='background:#fff8e1; border:1.5px solid #ffe082; border-radius:12px; "
            f"padding:14px 18px; margin:8px 0 12px 0; font-size:14px; color:#555;'>"
            f"✏️ Editing: <strong>{row.get('course_id','?')}</strong> · "
            f"Block <strong>{row.get('block','?')}</strong> · "
            f"{'🔬 Lab' if is_lab else '📖 Lecture'}"
            f"{'&nbsp;&nbsp;🚫 Lab mode is locked to F2F' if is_lab else ''}"
            f"</div>",
            unsafe_allow_html=True,
        )

        col1, col2 = st.columns(2)

        with col1:
            # ── Day ──────────────────────────────────────────────────────
            valid_days = DAYS_OF_WEEK
            if is_nstp and row.get("year_level") == 1:
                valid_days = DAYS_OF_WEEK + ["Sunday"]
            cur_day = row.get("day", "Monday")
            new_day = st.selectbox(
                "📅 Day",
                valid_days,
                index=valid_days.index(cur_day) if cur_day in valid_days else 0,
            )

            # ── Mode ─────────────────────────────────────────────────────
            if is_lab:
                st.selectbox("🖥️ Mode", ["f2f"], disabled=True, help="Lab classes are always Face-to-Face.")
                new_mode = "f2f"
            else:
                mode_opts = ["f2f", "online"]
                cur_mode_idx = mode_opts.index(cur_mode) if cur_mode in mode_opts else 0
                new_mode = st.selectbox("🖥️ Mode", mode_opts, index=cur_mode_idx)

            # ── Professor ─────────────────────────────────────────────────
            all_profs = sorted(df_edit["prof_id"].dropna().unique().tolist())
            cur_prof  = str(row.get("prof_id", ""))

            def prof_label(p):
                h = prof_hours_from_df(df_edit, p, exclude_idx=chosen_idx)
                dur_this = (int(row.get("time_end",0)) - int(row.get("time_start",0))) / 60
                projected = h + dur_this
                if projected > CHED_MAX_HOURS:
                    return f"🔴 {p} ({h:.1f}h + {dur_this:.1f}h = {projected:.1f}h — OVER LIMIT)"
                elif projected >= CHED_WARN_HOURS:
                    return f"🟡 {p} ({h:.1f}h remaining: {CHED_MAX_HOURS - h:.1f}h)"
                return f"🟢 {p} ({h:.1f}h assigned)"

            prof_options  = all_profs
            prof_labels   = [prof_label(p) for p in prof_options]
            cur_prof_idx  = prof_options.index(cur_prof) if cur_prof in prof_options else 0

            new_prof_label = st.selectbox("👤 Professor", prof_labels, index=cur_prof_idx)
            new_prof = prof_options[prof_labels.index(new_prof_label)]

            # Workload guard — warn if new professor would exceed cap
            new_prof_existing_h = prof_hours_from_df(df_edit, new_prof, exclude_idx=chosen_idx)
            this_dur_h = (int(row.get("time_end",0)) - int(row.get("time_start",0))) / 60
            new_prof_total = new_prof_existing_h + this_dur_h
            if new_prof_total > CHED_MAX_HOURS:
                st.error(
                    f"🔴 **Load limit exceeded.** Assigning this slot to **{new_prof}** would bring "
                    f"their total to **{new_prof_total:.1f}h**, over the CHED maximum of {CHED_MAX_HOURS}h."
                )

        with col2:
            # ── Time Start ───────────────────────────────────────────────
            all_time_opts  = list(range(450, 1261, 30))   # 7:30 AM to 9:00 PM
            all_time_labels = [format_minutes(t) for t in all_time_opts]

            cur_start = int(row.get("time_start", 480))
            start_idx = all_time_opts.index(cur_start) if cur_start in all_time_opts else 0
            new_start_label = st.selectbox("🕐 Start Time", all_time_labels, index=start_idx)
            new_start = all_time_opts[all_time_labels.index(new_start_label)]

            # ── Duration ─────────────────────────────────────────────────
            cur_dur = int(row.get("time_end",0)) - int(row.get("time_start",0))
            dur_keys   = list(DURATION_OPTIONS.keys())
            dur_values = list(DURATION_OPTIONS.values())
            best_dur_idx = 0
            for di, dv in enumerate(dur_values):
                if dv == cur_dur:
                    best_dur_idx = di
                    break
            new_dur_label = st.selectbox("⏱️ Duration", dur_keys, index=best_dur_idx)
            new_dur   = DURATION_OPTIONS[new_dur_label]
            new_end   = new_start + new_dur
            st.caption(f"→ Class ends at **{format_minutes(new_end)}**")

            # ── Room ─────────────────────────────────────────────────────
            if new_mode == "online":
                st.selectbox("🏫 Room", ["— Online (no room needed) —"], disabled=True)
                new_room = row.get("room", "online")
            else:
                room_pool = LAB_ROOMS if is_lab else LEC_ROOMS
                room_display = [format_room_name(r) for r in room_pool]
                cur_room_raw = str(row.get("room", ""))
                # map raw code → display
                cur_room_display = format_room_name(cur_room_raw)
                cur_room_idx = (
                    room_display.index(cur_room_display)
                    if cur_room_display in room_display else 0
                )
                new_room_display = st.selectbox(
                    "🏫 Room",
                    room_display,
                    index=cur_room_idx,
                    help=(
                        "Lab courses → 5th Floor South Wing (S5xx) or lab room.\n"
                        "Lecture courses → 4th Floor East Wing (E4xx) or gymnasium."
                    ),
                )
                new_room = strip_wing_prefix(new_room_display)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Conflict Preview ──────────────────────────────────────────────────
        preview_row = {
            "course_id":  row.get("course_id",""),
            "prof_id":    new_prof,
            "room":       new_room,
            "day":        new_day,
            "time_start": new_start,
            "time_end":   new_end,
            "mode":       new_mode,
            "is_lab":     is_lab,
        }
        conflicts = check_conflicts(df_edit, chosen_idx, preview_row)
        over_limit = new_prof_total > CHED_MAX_HOURS

        if conflicts:
            st.markdown("**⚠️ Detected Conflicts — resolve before saving:**")
            for c in conflicts:
                st.markdown(
                    f"<div style='background:#fff3e0; border-left:4px solid #e65100; "
                    f"border-radius:6px; padding:8px 14px; margin:4px 0; font-size:14px;'>"
                    f"⚠️ {c}</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                "<div style='background:#e8f5e9; border-left:4px solid #2e7d32; "
                "border-radius:6px; padding:8px 14px; font-size:14px;'>"
                "✅ No conflicts detected — safe to save."
                "</div>",
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Save button (disabled if conflicts or over limit) ─────────────────
        save_disabled = bool(conflicts) or over_limit
        save_col, dl_col = st.columns([2, 1])

        with save_col:
            if save_disabled:
                st.button(
                    "💾 Save Changes  (resolve conflicts first)",
                    disabled=True,
                    use_container_width=True,
                )
            else:
                if st.button("💾 Save Changes to Master Schedule", use_container_width=True):
                    # Snapshot BEFORE the change so we can undo back to it
                    old_label = (
                        f"{row.get('course_id','')} · {row.get('day','')} "
                        f"{format_minutes(row.get('time_start',0))}–"
                        f"{format_minutes(row.get('time_end',0))} · "
                        f"{row.get('prof_id','')} · {row.get('room','')}"
                    )
                    push_history(df_edit, f"Before: {old_label}")

                    df_edit.at[chosen_idx, "day"]        = new_day
                    df_edit.at[chosen_idx, "time_start"] = new_start
                    df_edit.at[chosen_idx, "time_end"]   = new_end
                    df_edit.at[chosen_idx, "mode"]       = new_mode
                    df_edit.at[chosen_idx, "prof_id"]    = new_prof
                    df_edit.at[chosen_idx, "room"]       = new_room

                    # Snapshot AFTER the change for redo
                    new_label = (
                        f"{row.get('course_id','')} · {new_day} "
                        f"{format_minutes(new_start)}–{format_minutes(new_end)} · "
                        f"{new_prof} · {new_room}"
                    )
                    push_history(df_edit, f"After: {new_label}")

                    try:
                        write_df_to_excel(df_edit, master_path)
                        st.success(
                            f"✅ **{row.get('course_id','')}** updated — "
                            f"{new_day} {format_minutes(new_start)}–{format_minutes(new_end)} · "
                            f"Room {new_room} · Prof {new_prof}"
                        )
                        st.session_state.edit_idx = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to save: {e}")

        with dl_col:
            with open(master_path, "rb") as f_dl:
                st.download_button(
                    "⬇️ Download Master Schedule",
                    f_dl,
                    "masterSchedule.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

    st.divider()

    # ── SECTION D: Undo / Redo ─────────────────────────────────────────────────
    st.markdown("### ↩️ Edit History")

    history      = st.session_state.edit_history
    hist_idx     = st.session_state.history_idx
    can_undo     = hist_idx > 0
    can_redo     = hist_idx < len(history) - 1

    undo_col, redo_col, clear_col = st.columns([1, 1, 2])

    with undo_col:
        if st.button(
            "↩️ Undo",
            disabled=not can_undo,
            use_container_width=True,
            help="Revert to the previous saved state.",
        ):
            st.session_state.history_idx -= 1
            restored_df = history[st.session_state.history_idx]["df"].copy()
            try:
                write_df_to_excel(restored_df, master_path)
                st.success(
                    f"↩️ Undone to: **{history[st.session_state.history_idx]['label']}**"
                )
                st.rerun()
            except Exception as e:
                st.error(f"Undo failed: {e}")

    with redo_col:
        if st.button(
            "↪️ Redo",
            disabled=not can_redo,
            use_container_width=True,
            help="Re-apply the next saved state.",
        ):
            st.session_state.history_idx += 1
            restored_df = history[st.session_state.history_idx]["df"].copy()
            try:
                write_df_to_excel(restored_df, master_path)
                st.success(
                    f"↪️ Redone to: **{history[st.session_state.history_idx]['label']}**"
                )
                st.rerun()
            except Exception as e:
                st.error(f"Redo failed: {e}")

    with clear_col:
        if st.button(
            "🗑️ Clear History",
            disabled=len(history) == 0,
            use_container_width=True,
            help="Erase all undo/redo history (does not change the current schedule).",
        ):
            st.session_state.edit_history = []
            st.session_state.history_idx  = -1
            st.rerun()

    # History log
    if history:
        st.markdown("<br>", unsafe_allow_html=True)
        st.caption(
            f"Showing {len(history)} snapshot(s) — current position: "
            f"{'**' + str(hist_idx + 1) + '**'} of {len(history)}"
        )

        log_html = ""
        for i, snap in enumerate(reversed(history)):
            real_i  = len(history) - 1 - i      # index from oldest→newest
            is_cur  = real_i == hist_idx
            is_fut  = real_i > hist_idx

            bg      = "#e8f5e9" if is_cur else "#f5f5f5"
            border  = "#2e7d32" if is_cur else "#e0e0e0"
            opacity = "0.45" if is_fut else "1"
            marker  = "◀ current" if is_cur else ("↪ redo" if is_fut else "")
            label   = snap["label"]
            ts      = snap["ts"]

            log_html += (
                f"<div style='background:{bg}; border:1.5px solid {border}; border-radius:10px; "
                f"padding:9px 14px; margin:4px 0; opacity:{opacity}; "
                f"display:flex; justify-content:space-between; align-items:center;'>"
                f"  <span style='font-size:13px; color:#333; font-weight:600;'>{label}</span>"
                f"  <span style='font-size:12px; color:#888; margin-left:16px; white-space:nowrap;'>"
                f"    {ts}&nbsp;&nbsp;<em style='color:#1565C0;'>{marker}</em>"
                f"  </span>"
                f"</div>"
            )

        st.markdown(
            f"<div style='max-height:260px; overflow-y:auto; padding:2px;'>{log_html}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='background:#f5f5f5; border:1.5px solid #e0e0e0; border-radius:10px; "
            "padding:12px 16px; color:#888; font-size:14px;'>"
            "No changes yet — history will appear here after the first save."
            "</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── SECTION E: Full Assignment Table (read-only reference) ────────────────
    st.markdown("### 📋 Full Assignment Reference Table")
    st.caption("Read-only view of the current schedule. Use the editor above to make changes.")

    df_display = df_edit.copy()
    if "time_start" in df_display.columns:
        df_display["time_start"] = df_display["time_start"].apply(format_minutes)
    if "time_end" in df_display.columns:
        df_display["time_end"] = df_display["time_end"].apply(format_minutes)
    if "room" in df_display.columns:
        df_display["room"] = df_display["room"].apply(format_room_name)

    st.dataframe(df_display, use_container_width=True, height=300)
