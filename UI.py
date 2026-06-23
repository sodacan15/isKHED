import streamlit as st
import pandas as pd
import subprocess
import sys
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
            result = subprocess.run(
                [sys.executable, "main.py"],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                st.error("⚠️ Schedule generation failed.")
                with st.expander("Show error details"):
                    st.code(result.stderr or result.stdout or "No output captured.")
            else:
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
    st.subheader("🏢 Room Allocation Center")

    master_path = "masterSchedule.xlsx"
    if not (st.session_state.schedule_generated and os.path.exists(master_path)):
        st.info("Generate a schedule to view room allocations.")
    else:
        try:
            df_raw_rooms = pd.read_excel(master_path, sheet_name="All_Assignments")
            if "room" in df_raw_rooms.columns:
                df_raw_rooms["room"] = df_raw_rooms["room"].apply(format_room_name)
            for tcol in ("time_start", "time_end"):
                if tcol in df_raw_rooms.columns:
                    df_raw_rooms[tcol] = df_raw_rooms[tcol].apply(parse_time_to_minutes)

            room_col_name = next(
                (c for c in df_raw_rooms.columns if any(k in c.lower() for k in ("room","location"))), None
            )
            prof_col_name = next(
                (c for c in df_raw_rooms.columns if any(k in c.lower() for k in ("prof","instructor","faculty"))), None
            )
            course_color_map = get_course_color_map(df_raw_rooms)

            if room_col_name is None:
                st.warning("No room column found in schedule.")
                st.stop()

            all_rooms = sorted(df_raw_rooms[room_col_name].dropna().unique().tolist())
            total_slots = len(DAYS_OF_WEEK) * len(TIME_BINS)

            # Build per-room stats
            room_stats = []
            for rm in all_rooms:
                r_df = df_raw_rooms[df_raw_rooms[room_col_name] == rm]
                occupied = 0
                for _, rrow in r_df.iterrows():
                    try:
                        occupied += (int(rrow["time_end"]) - int(rrow["time_start"])) // 30
                    except Exception:
                        pass
                util_pct = min(round(occupied / total_slots * 100, 1), 100)
                is_lab = rm.startswith("South Wing") or "lab" in rm.lower()
                room_stats.append({
                    "room": rm, "sessions": len(r_df),
                    "occupied_slots": occupied, "utilization": util_pct,
                    "type": "Lab" if is_lab else "Lecture",
                })
            stats_df = pd.DataFrame(room_stats)

            # Detect double-bookings
            conflicts_list = []
            for rm in all_rooms:
                r_df = df_raw_rooms[df_raw_rooms[room_col_name] == rm].reset_index(drop=True)
                for i in range(len(r_df)):
                    for j in range(i + 1, len(r_df)):
                        ri, rj = r_df.iloc[i], r_df.iloc[j]
                        if ri.get("day") == rj.get("day"):
                            si, ei = int(ri.get("time_start", 0)), int(ri.get("time_end", 0))
                            sj, ej = int(rj.get("time_start", 0)), int(rj.get("time_end", 0))
                            if si < ej and sj < ei:
                                conflicts_list.append({
                                    "Room": rm, "Day": ri.get("day", ""),
                                    "Course A": ri.get("course_id", ""),
                                    "Course B": rj.get("course_id", ""),
                                    "Time A": f"{format_minutes(si)}–{format_minutes(ei)}",
                                    "Time B": f"{format_minutes(sj)}–{format_minutes(ej)}",
                                })

            # ── Top Metrics ──────────────────────────────────────────────────────
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Rooms in Use", len(all_rooms))
            m2.metric("Total Sessions", len(df_raw_rooms))
            avg_util = round(stats_df["utilization"].mean(), 1) if not stats_df.empty else 0
            m3.metric("Avg Utilization", f"{avg_util}%")
            m4.metric(
                "Room Conflicts",
                len(conflicts_list),
                delta=f"{len(conflicts_list)} need attention" if conflicts_list else "None detected",
                delta_color="inverse" if conflicts_list else "normal",
            )

            st.markdown("<br>", unsafe_allow_html=True)

            # ── Tabs ─────────────────────────────────────────────────────────────
            tab_overview, tab_detail, tab_conflicts = st.tabs(
                ["📊 Room Overview", "🔍 Room Detail", "🚨 Conflict Report"]
            )

            with tab_overview:
                type_filter = st.radio(
                    "Filter by Type:", ["All", "Lab Rooms", "Lecture Rooms"],
                    horizontal=True, key="room_type_filter"
                )
                filtered_stats = stats_df.copy()
                if type_filter == "Lab Rooms":
                    filtered_stats = stats_df[stats_df["type"] == "Lab"]
                elif type_filter == "Lecture Rooms":
                    filtered_stats = stats_df[stats_df["type"] == "Lecture"]

                if filtered_stats.empty:
                    st.info("No rooms of this type found.")
                else:
                    st.caption(
                        "🟢 Under 50%  ·  🟡 50–80%  ·  🔴 Above 80% utilization"
                    )
                    cols_per_row = 4
                    rows_batched = [
                        filtered_stats.iloc[i:i + cols_per_row]
                        for i in range(0, len(filtered_stats), cols_per_row)
                    ]
                    for row_batch in rows_batched:
                        col_widgets = st.columns(cols_per_row)
                        for col_w, (_, rstat) in zip(col_widgets, row_batch.iterrows()):
                            util = rstat["utilization"]
                            bar_color = (
                                "#D32F2F" if util >= 80 else
                                "#F9A825" if util >= 50 else
                                "#2E7D32"
                            )
                            badge_color = "#1565C0" if rstat["type"] == "Lab" else "#6A1B9A"
                            col_w.markdown(
                                f"""<div style="background:#fff;border:1.5px solid #e0e0e0;
                                            border-radius:12px;padding:14px 16px;margin-bottom:10px;
                                            box-shadow:0 2px 6px rgba(0,0,0,0.06);">
                                  <div style="display:flex;justify-content:space-between;
                                              align-items:flex-start;margin-bottom:6px;">
                                    <div style="font-weight:700;font-size:13px;color:#222;">
                                        {rstat['room']}</div>
                                    <span style="background:{badge_color};color:#fff;font-size:10px;
                                               font-weight:700;padding:2px 8px;border-radius:20px;">
                                        {rstat['type']}</span>
                                  </div>
                                  <div style="font-size:12px;color:#666;margin-bottom:6px;">
                                    {rstat['sessions']} session{'s' if rstat['sessions'] != 1 else ''}
                                    &nbsp;·&nbsp;{util}%
                                  </div>
                                  <div style="background:#e0e0e0;border-radius:8px;height:8px;width:100%;">
                                    <div style="width:{util}%;background:{bar_color};
                                                height:8px;border-radius:8px;"></div>
                                  </div>
                                </div>""",
                                unsafe_allow_html=True,
                            )

            with tab_detail:
                room_select_list = ["— Select a room to inspect —"] + all_rooms
                selected_room = st.selectbox(
                    "🏫 Room:", room_select_list, key="room_detail_select"
                )

                if selected_room == "— Select a room to inspect —":
                    st.markdown(
                        "<div style='background:#f0f4ff;border:1.5px solid #c5cae9;"
                        "border-radius:12px;padding:18px 20px;color:#555;font-size:15px;'>"
                        "👆 Select a room above to view its full weekly timetable and session list."
                        "</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    df_room_filtered = df_raw_rooms[
                        df_raw_rooms[room_col_name] == selected_room
                    ]
                    sel_stat_rows = stats_df[stats_df["room"] == selected_room]
                    if not sel_stat_rows.empty:
                        rstat_sel = sel_stat_rows.iloc[0]
                        ri1, ri2, ri3 = st.columns(3)
                        ri1.metric("Sessions This Week", int(rstat_sel["sessions"]))
                        ri2.metric("Utilization", f"{rstat_sel['utilization']}%")
                        ri3.metric("Room Type", rstat_sel["type"])

                    st.markdown("#### 🗓️ Weekly Timetable")

                    def room_cell_detail(row):
                        course = str(row.get("course_id", ""))
                        prof   = str(row.get(prof_col_name, "")) if prof_col_name else ""
                        return f"{course} | {prof}"

                    grid_rooms = build_timetable_grid(df_room_filtered, room_cell_detail)
                    style_fn   = make_style_fn(course_color_map)
                    try:
                        styled_rooms = grid_rooms.style.map(style_fn)
                    except AttributeError:
                        styled_rooms = grid_rooms.style.applymap(style_fn)

                    st.dataframe(styled_rooms, use_container_width=True, height=500)
                    render_legend(course_color_map)

                    st.markdown("#### 📋 Session Details")
                    df_room_table = df_room_filtered.copy()
                    if "time_start" in df_room_table.columns:
                        df_room_table["time_start"] = df_room_table["time_start"].apply(format_minutes)
                    if "time_end" in df_room_table.columns:
                        df_room_table["time_end"] = df_room_table["time_end"].apply(format_minutes)
                    st.dataframe(df_room_table, use_container_width=True, height=260)

            with tab_conflicts:
                if not conflicts_list:
                    st.success(
                        "✅ No room conflicts detected — all rooms are properly allocated."
                    )
                else:
                    st.error(
                        f"🚨 {len(conflicts_list)} overlap(s) found. "
                        "These rooms have sessions assigned at the same time:"
                    )
                    st.dataframe(
                        pd.DataFrame(conflicts_list), use_container_width=True, height=300
                    )
                    st.markdown(
                        "<div style='background:#fff3e0;border-left:4px solid #e65100;"
                        "border-radius:6px;padding:12px 16px;margin-top:12px;font-size:14px;'>"
                        "⚠️ Go to <strong>Manual Adjustments</strong> to resolve these by "
                        "changing the time slot or room of the affected sessions.</div>",
                        unsafe_allow_html=True,
                    )

        except Exception as e:
            st.warning(f"Room data not available. Error: {e}")


# ==========================================
# VIEW 3: MANUAL ADJUSTMENTS
# ==========================================
elif st.session_state.active_tab == "Manual Adjustments":
    st.subheader("⚠️ Schedule Health & Manual Overrides")

    master_path = "masterSchedule.xlsx"
    if not (st.session_state.schedule_generated and os.path.exists(master_path)):
        st.info("Generate a schedule to access manual override tools.")
        st.stop()

    try:
        df_edit = pd.read_excel(master_path, sheet_name="All_Assignments")
    except Exception as e:
        st.error(f"Cannot load schedule: {e}")
        st.stop()

    for tcol in ("time_start", "time_end"):
        if tcol in df_edit.columns:
            df_edit[tcol] = df_edit[tcol].apply(parse_time_to_minutes)

    # ── SECTION A: Algorithm Status ───────────────────────────────────────────
    try:
        df_summary = pd.read_excel(master_path, sheet_name="Summary")
        if not df_summary.empty:
            with st.expander("📊 Algorithm Status Report", expanded=False):
                n_cols = min(len(df_summary.columns), 6)
                metric_cols = st.columns(n_cols)
                for i, col in enumerate(df_summary.columns[:n_cols]):
                    metric_cols[i].metric(
                        label=col.replace("_", " ").title(),
                        value=str(df_summary.iloc[0][col]),
                    )
    except Exception:
        pass

    st.markdown("<br>", unsafe_allow_html=True)

    # ── SECTION B: Professor Workload Dashboard ───────────────────────────────
    with st.expander("👨‍🏫 Professor Workload Dashboard", expanded=True):
        st.caption(
            f"CHED teaching load limit: "
            f"🟡 Warning at {CHED_WARN_HOURS}h/week · "
            f"🔴 Hard cap at {CHED_MAX_HOURS}h/week"
        )
        wl_df = compute_professor_workload(df_edit)
        if not wl_df.empty:
            over_cap   = wl_df[wl_df["hours"] > CHED_MAX_HOURS]
            near_cap   = wl_df[(wl_df["hours"] >= CHED_WARN_HOURS) & (wl_df["hours"] <= CHED_MAX_HOURS)]
            ok_profs   = wl_df[wl_df["hours"] < CHED_WARN_HOURS]

            wl_m1, wl_m2, wl_m3 = st.columns(3)
            wl_m1.metric("🟢 Within Limit", len(ok_profs))
            wl_m2.metric("🟡 Near Limit", len(near_cap))
            wl_m3.metric("🔴 Over Limit", len(over_cap))

            if not over_cap.empty:
                st.markdown(
                    "<div style='background:#ffebee;border-left:4px solid #c62828;"
                    "border-radius:6px;padding:10px 14px;margin:8px 0;font-size:14px;'>"
                    "🔴 <strong>Action required:</strong> The following professors exceed the "
                    f"CHED {CHED_MAX_HOURS}h cap. Use the editor below to reassign their sessions."
                    "</div>",
                    unsafe_allow_html=True,
                )

            st.markdown("<br>", unsafe_allow_html=True)
            wl_cols = st.columns(4)
            for i, (_, wrow) in enumerate(wl_df.iterrows()):
                col_idx = i % 4
                pct = min(wrow["hours"] / CHED_MAX_HOURS, 1.0)
                bar_color = (
                    "#D32F2F" if wrow["hours"] > CHED_MAX_HOURS else
                    "#F9A825" if wrow["hours"] >= CHED_WARN_HOURS else
                    "#2E7D32"
                )
                border_color = (
                    "#ffcdd2" if wrow["hours"] > CHED_MAX_HOURS else
                    "#fff9c4" if wrow["hours"] >= CHED_WARN_HOURS else
                    "#e0e0e0"
                )
                remaining = max(CHED_MAX_HOURS - wrow["hours"], 0)
                wl_cols[col_idx].markdown(
                    f"""<div style="background:#fff;border:1.5px solid {border_color};
                                border-radius:12px;padding:12px 14px;margin-bottom:8px;">
                      <div style="font-weight:700;font-size:13px;color:#222;
                                  margin-bottom:2px;">{wrow['prof_id']}</div>
                      <div style="font-size:11px;color:#666;margin-bottom:5px;">
                        {wrow['hours']}h assigned &nbsp;·&nbsp;
                        {remaining:.1f}h remaining &nbsp;{wrow['status']}
                      </div>
                      <div style="background:#e0e0e0;border-radius:8px;height:8px;width:100%;">
                        <div style="width:{int(pct*100)}%;background:{bar_color};
                                    height:8px;border-radius:8px;"></div>
                      </div>
                    </div>""",
                    unsafe_allow_html=True,
                )
                if col_idx == 3 and i < len(wl_df) - 1:
                    wl_cols = st.columns(4)
        else:
            st.info("No professor data found in schedule.")

    st.divider()

    # ── SECTION C: Smart Assignment Editor ────────────────────────────────────
    st.markdown("### ✏️ Smart Assignment Editor")
    st.caption(
        "Use the filters to narrow down the assignment you want to change, "
        "then edit its fields. The system validates every change in real time "
        "before allowing you to save."
    )

    if df_edit.empty:
        st.info("No assignments to edit.")
        st.stop()

    # ── Step 1: Filter panel ──────────────────────────────────────────────────
    with st.container():
        st.markdown(
            "<div style='background:#f8f9fa;border:1px solid #e0e0e0;border-radius:12px;"
            "padding:16px 20px;margin-bottom:16px;'>",
            unsafe_allow_html=True,
        )
        st.markdown("**🔍 Step 1 — Filter assignments**")
        fc1, fc2, fc3 = st.columns(3)

        all_courses = ["All"] + sorted(df_edit["course_id"].dropna().unique().tolist())
        all_days_f  = ["All"] + DAYS_OF_WEEK
        all_profs_f = ["All"] + sorted(df_edit["prof_id"].dropna().unique().tolist())

        f_course = fc1.selectbox("Course", all_courses, key="f_course")
        f_day    = fc2.selectbox("Day", all_days_f, key="f_day")
        f_prof   = fc3.selectbox("Professor", all_profs_f, key="f_prof")
        st.markdown("</div>", unsafe_allow_html=True)

    df_filtered_edit = df_edit.copy()
    if f_course != "All":
        df_filtered_edit = df_filtered_edit[df_filtered_edit["course_id"] == f_course]
    if f_day != "All":
        df_filtered_edit = df_filtered_edit[df_filtered_edit["day"] == f_day]
    if f_prof != "All":
        df_filtered_edit = df_filtered_edit[df_filtered_edit["prof_id"] == f_prof]

    # ── Step 2: Pick assignment ───────────────────────────────────────────────
    def make_label(row):
        ts = format_minutes(row.get("time_start", ""))
        te = format_minutes(row.get("time_end",   ""))
        type_tag = "🔬 Lab" if row.get("is_lab") else "📖 Lec"
        return (
            f"{row.get('course_id','?')} · Block {row.get('block','?')} · "
            f"{row.get('day','?')} {ts}–{te} · {row.get('prof_id','?')} · "
            f"{format_room_name(str(row.get('room','?')))} · {type_tag}"
        )

    filtered_labels  = ["— Select an assignment —"] + [
        make_label(r) for _, r in df_filtered_edit.iterrows()
    ]
    filtered_indices = [None] + list(df_filtered_edit.index)

    st.markdown("**📋 Step 2 — Select the assignment to edit**")
    chosen_label = st.selectbox(
        f"Showing {len(df_filtered_edit)} of {len(df_edit)} assignments",
        filtered_labels,
        index=0,
        key="assignment_selector",
        label_visibility="visible",
    )
    chosen_idx = filtered_indices[filtered_labels.index(chosen_label)]

    st.markdown("<br>", unsafe_allow_html=True)

    if chosen_idx is None:
        st.markdown(
            "<div style='background:#f0f4ff;border:1.5px solid #c5cae9;border-radius:12px;"
            "padding:18px 20px;color:#555;font-size:15px;'>"
            "👆 Select an assignment above to open the constrained editor."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        row = df_edit.loc[chosen_idx].to_dict()
        is_lab   = bool(row.get("is_lab", False))
        is_nstp  = bool(row.get("is_nstp", False))
        cur_mode = str(row.get("mode", "f2f")).lower()

        # ── Context banner ────────────────────────────────────────────────────
        type_label = "🔬 Lab (locked to F2F)" if is_lab else "📖 Lecture"
        st.markdown(
            f"<div style='background:#fff8e1;border:1.5px solid #ffe082;border-radius:12px;"
            f"padding:14px 20px;margin-bottom:16px;display:flex;align-items:center;"
            f"justify-content:space-between;'>"
            f"  <div>"
            f"    <div style='font-weight:800;font-size:16px;color:#333;'>"
            f"      ✏️ {row.get('course_id','?')} &nbsp;·&nbsp; Block {row.get('block','?')}"
            f"    </div>"
            f"    <div style='font-size:13px;color:#666;margin-top:4px;'>{type_label}</div>"
            f"  </div>"
            f"  <div style='font-size:12px;color:#888;text-align:right;'>"
            f"    Currently: {row.get('day','?')} "
            f"    {format_minutes(row.get('time_start',0))}–"
            f"    {format_minutes(row.get('time_end',0))}"
            f"    <br>{format_room_name(str(row.get('room','?')))} · {row.get('prof_id','?')}"
            f"  </div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # ── Step 3: Edit fields ───────────────────────────────────────────────
        st.markdown("**🛠️ Step 3 — Modify the fields below**")
        col1, col2, col3 = st.columns(3)

        with col1:
            valid_days = DAYS_OF_WEEK
            if is_nstp and row.get("year_level") == 1:
                valid_days = DAYS_OF_WEEK + ["Sunday"]
            cur_day = row.get("day", "Monday")
            new_day = st.selectbox(
                "📅 Day",
                valid_days,
                index=valid_days.index(cur_day) if cur_day in valid_days else 0,
                key="edit_day",
            )

            if is_lab:
                st.selectbox(
                    "🖥️ Mode", ["Face-to-Face"], disabled=True,
                    help="Lab sessions are always Face-to-Face.", key="edit_mode_lab"
                )
                new_mode = "f2f"
            else:
                mode_display = {"f2f": "Face-to-Face", "online": "Online"}
                mode_opts    = ["f2f", "online"]
                mode_labels  = [mode_display[m] for m in mode_opts]
                cur_mode_idx = mode_opts.index(cur_mode) if cur_mode in mode_opts else 0
                new_mode_label = st.selectbox(
                    "🖥️ Mode", mode_labels, index=cur_mode_idx, key="edit_mode"
                )
                new_mode = mode_opts[mode_labels.index(new_mode_label)]

        with col2:
            all_time_opts   = list(range(450, 1261, 30))
            all_time_labels = [format_minutes(t) for t in all_time_opts]
            cur_start  = int(row.get("time_start", 480))
            start_idx  = all_time_opts.index(cur_start) if cur_start in all_time_opts else 0
            new_start_label = st.selectbox(
                "🕐 Start Time", all_time_labels, index=start_idx, key="edit_start"
            )
            new_start = all_time_opts[all_time_labels.index(new_start_label)]

            cur_dur      = int(row.get("time_end", 0)) - int(row.get("time_start", 0))
            dur_keys     = list(DURATION_OPTIONS.keys())
            dur_values   = list(DURATION_OPTIONS.values())
            best_dur_idx = next((di for di, dv in enumerate(dur_values) if dv == cur_dur), 0)
            new_dur_label = st.selectbox(
                "⏱️ Duration", dur_keys, index=best_dur_idx, key="edit_dur"
            )
            new_dur = DURATION_OPTIONS[new_dur_label]
            new_end = new_start + new_dur
            st.caption(f"⏰ Ends at **{format_minutes(new_end)}**")

        with col3:
            all_profs_e  = sorted(df_edit["prof_id"].dropna().unique().tolist())
            cur_prof     = str(row.get("prof_id", ""))
            this_dur_h   = (int(row.get("time_end", 0)) - int(row.get("time_start", 0))) / 60

            def prof_label_e(p):
                h = prof_hours_from_df(df_edit, p, exclude_idx=chosen_idx)
                proj = h + this_dur_h
                if proj > CHED_MAX_HOURS:
                    return f"🔴 {p}  ({h:.1f}h → {proj:.1f}h OVER)"
                elif proj >= CHED_WARN_HOURS:
                    return f"🟡 {p}  ({h:.1f}h → {proj:.1f}h)"
                return f"🟢 {p}  ({h:.1f}h assigned)"

            prof_labels_e  = [prof_label_e(p) for p in all_profs_e]
            cur_prof_idx_e = all_profs_e.index(cur_prof) if cur_prof in all_profs_e else 0
            new_prof_label = st.selectbox(
                "👤 Professor", prof_labels_e, index=cur_prof_idx_e, key="edit_prof"
            )
            new_prof = all_profs_e[prof_labels_e.index(new_prof_label)]

            new_prof_existing_h = prof_hours_from_df(df_edit, new_prof, exclude_idx=chosen_idx)
            new_prof_total      = new_prof_existing_h + this_dur_h

            if new_mode == "online":
                st.selectbox(
                    "🏫 Room", ["— Online (no room) —"],
                    disabled=True, key="edit_room_online"
                )
                new_room = row.get("room", "online")
            else:
                room_pool    = LAB_ROOMS if is_lab else LEC_ROOMS
                room_display = [format_room_name(r) for r in room_pool]
                cur_room_raw     = str(row.get("room", ""))
                cur_room_display = format_room_name(cur_room_raw)
                cur_room_idx     = (
                    room_display.index(cur_room_display)
                    if cur_room_display in room_display else 0
                )
                new_room_display = st.selectbox(
                    "🏫 Room", room_display, index=cur_room_idx, key="edit_room",
                    help=(
                        "Lab → South Wing 5th Floor (S5xx)\n"
                        "Lecture → East Wing 4th Floor (E4xx)"
                    ),
                )
                new_room = strip_wing_prefix(new_room_display)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Step 4: Live validation ───────────────────────────────────────────
        preview_row = {
            "course_id":  row.get("course_id", ""),
            "prof_id":    new_prof,
            "room":       new_room,
            "day":        new_day,
            "time_start": new_start,
            "time_end":   new_end,
            "mode":       new_mode,
            "is_lab":     is_lab,
        }
        conflicts    = check_conflicts(df_edit, chosen_idx, preview_row)
        over_limit   = new_prof_total > CHED_MAX_HOURS
        save_disabled = bool(conflicts) or over_limit

        # Before / After summary
        bc, ac = st.columns(2)
        with bc:
            st.markdown(
                f"<div style='background:#f5f5f5;border:1.5px solid #e0e0e0;border-radius:10px;"
                f"padding:12px 16px;font-size:13px;color:#555;'>"
                f"<div style='font-weight:700;color:#880000;margin-bottom:6px;'>BEFORE</div>"
                f"📅 {row.get('day','?')}<br>"
                f"🕐 {format_minutes(row.get('time_start',0))}–{format_minutes(row.get('time_end',0))}<br>"
                f"👤 {row.get('prof_id','?')}<br>"
                f"🏫 {format_room_name(str(row.get('room','?')))}"
                f"</div>",
                unsafe_allow_html=True,
            )
        with ac:
            changed = (
                new_day != row.get("day") or
                new_start != row.get("time_start") or
                new_prof != row.get("prof_id") or
                new_room != row.get("room") or
                new_mode != cur_mode
            )
            after_bg     = "#e8f5e9" if (changed and not save_disabled) else "#f5f5f5"
            after_border = "#2e7d32" if (changed and not save_disabled) else "#e0e0e0"
            after_title_color = "#2e7d32" if (changed and not save_disabled) else "#555"
            st.markdown(
                f"<div style='background:{after_bg};border:1.5px solid {after_border};"
                f"border-radius:10px;padding:12px 16px;font-size:13px;color:#555;'>"
                f"<div style='font-weight:700;color:{after_title_color};margin-bottom:6px;'>AFTER</div>"
                f"📅 {new_day}<br>"
                f"🕐 {format_minutes(new_start)}–{format_minutes(new_end)}<br>"
                f"👤 {new_prof}<br>"
                f"🏫 {format_room_name(new_room) if new_mode != 'online' else '— Online —'}"
                f"</div>",
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)

        # Validation feedback
        if conflicts or over_limit:
            st.markdown(
                "<div style='background:#fff3e0;border:1.5px solid #e65100;border-radius:10px;"
                "padding:14px 18px;margin-bottom:12px;'>"
                "<div style='font-weight:700;font-size:14px;color:#bf360c;margin-bottom:8px;'>"
                "⚠️ Conflicts detected — resolve before saving</div>",
                unsafe_allow_html=True,
            )
            for c in conflicts:
                st.markdown(
                    f"<div style='font-size:13px;color:#555;padding:4px 0 4px 8px;"
                    f"border-left:3px solid #e65100;margin:4px 0;'>{c}</div>",
                    unsafe_allow_html=True,
                )
            if over_limit:
                st.markdown(
                    f"<div style='font-size:13px;color:#555;padding:4px 0 4px 8px;"
                    f"border-left:3px solid #c62828;margin:4px 0;'>"
                    f"🔴 Assigning to <strong>{new_prof}</strong> would bring their total to "
                    f"<strong>{new_prof_total:.1f}h</strong> — over the CHED {CHED_MAX_HOURS}h cap.</div>",
                    unsafe_allow_html=True,
                )
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.markdown(
                "<div style='background:#e8f5e9;border:1.5px solid #2e7d32;border-radius:10px;"
                "padding:12px 16px;font-size:14px;margin-bottom:12px;'>"
                "✅ <strong>All clear</strong> — no conflicts detected. Safe to save."
                "</div>",
                unsafe_allow_html=True,
            )

        # Save / Download
        save_col, dl_col = st.columns([2, 1])
        with save_col:
            if save_disabled:
                st.button(
                    "🔒 Save Blocked — Resolve Conflicts First",
                    disabled=True, use_container_width=True,
                )
            else:
                if st.button(
                    "💾 Save Changes to Master Schedule",
                    use_container_width=True, type="primary",
                ):
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

                    new_label = (
                        f"{row.get('course_id','')} · {new_day} "
                        f"{format_minutes(new_start)}–{format_minutes(new_end)} · "
                        f"{new_prof} · {new_room}"
                    )
                    push_history(df_edit, f"After: {new_label}")

                    try:
                        write_df_to_excel(df_edit, master_path)
                        st.success(
                            f"✅ Saved — **{row.get('course_id','')}** moved to "
                            f"{new_day} {format_minutes(new_start)}–{format_minutes(new_end)}, "
                            f"Room {format_room_name(new_room)}, Prof {new_prof}"
                        )
                        st.session_state.edit_idx = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to save: {e}")

        with dl_col:
            with open(master_path, "rb") as f_dl:
                st.download_button(
                    "⬇️ Download Schedule",
                    f_dl,
                    "masterSchedule.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

    st.divider()

    # ── SECTION D: Undo / Redo ─────────────────────────────────────────────────
    st.markdown("### ↩️ Edit History")

    history  = st.session_state.edit_history
    hist_idx = st.session_state.history_idx
    can_undo = hist_idx > 0
    can_redo = hist_idx < len(history) - 1

    undo_col, redo_col, clear_col, status_col = st.columns([1, 1, 1, 3])

    with undo_col:
        if st.button(
            "↩️ Undo", disabled=not can_undo,
            use_container_width=True, help="Revert to the previous state.",
        ):
            st.session_state.history_idx -= 1
            restored_df = history[st.session_state.history_idx]["df"].copy()
            try:
                write_df_to_excel(restored_df, master_path)
                st.success(f"↩️ Undone: **{history[st.session_state.history_idx]['label']}**")
                st.rerun()
            except Exception as e:
                st.error(f"Undo failed: {e}")

    with redo_col:
        if st.button(
            "↪️ Redo", disabled=not can_redo,
            use_container_width=True, help="Re-apply the next state.",
        ):
            st.session_state.history_idx += 1
            restored_df = history[st.session_state.history_idx]["df"].copy()
            try:
                write_df_to_excel(restored_df, master_path)
                st.success(f"↪️ Redone: **{history[st.session_state.history_idx]['label']}**")
                st.rerun()
            except Exception as e:
                st.error(f"Redo failed: {e}")

    with clear_col:
        if st.button(
            "🗑️ Clear", disabled=len(history) == 0,
            use_container_width=True, help="Erase all history (does not change the schedule).",
        ):
            st.session_state.edit_history = []
            st.session_state.history_idx  = -1
            st.rerun()

    with status_col:
        if history:
            st.markdown(
                f"<div style='padding:8px 0;font-size:13px;color:#666;'>"
                f"Step <strong>{hist_idx + 1}</strong> of <strong>{len(history)}</strong> "
                f"&nbsp;·&nbsp; {len(history)} change{'s' if len(history) != 1 else ''} recorded"
                f"</div>",
                unsafe_allow_html=True,
            )

    if history:
        st.markdown("<br>", unsafe_allow_html=True)
        log_html = ""
        for i, snap in enumerate(reversed(history)):
            real_i  = len(history) - 1 - i
            is_cur  = real_i == hist_idx
            is_fut  = real_i > hist_idx
            bg      = "#e8f5e9" if is_cur else "#f5f5f5"
            border  = "#2e7d32" if is_cur else "#e0e0e0"
            opacity = "0.4" if is_fut else "1"
            marker  = "◀ current" if is_cur else ("↪ redo" if is_fut else "")
            log_html += (
                f"<div style='background:{bg};border:1.5px solid {border};border-radius:10px;"
                f"padding:9px 14px;margin:4px 0;opacity:{opacity};"
                f"display:flex;justify-content:space-between;align-items:center;'>"
                f"  <span style='font-size:13px;color:#333;font-weight:600;'>"
                f"    {snap['label']}</span>"
                f"  <span style='font-size:12px;color:#888;margin-left:16px;white-space:nowrap;'>"
                f"    {snap['ts']}"
                f"    &nbsp;<em style='color:#1565C0;'>{marker}</em>"
                f"  </span>"
                f"</div>"
            )
        st.markdown(
            f"<div style='max-height:240px;overflow-y:auto;padding:2px;'>{log_html}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div style='background:#f5f5f5;border:1.5px solid #e0e0e0;border-radius:10px;"
            "padding:12px 16px;color:#999;font-size:14px;'>"
            "No changes yet — history appears here after each save."
            "</div>",
            unsafe_allow_html=True,
        )

    st.divider()

    # ── SECTION E: Full Reference Table ───────────────────────────────────────
    st.markdown("### 📋 Full Assignment Reference")
    st.caption("Read-only view — use the editor above to make changes.")

    ref_fcols = st.columns(3)
    ref_f_course = ref_fcols[0].selectbox(
        "Filter by Course", ["All"] + sorted(df_edit["course_id"].dropna().unique().tolist()),
        key="ref_f_course"
    )
    ref_f_day = ref_fcols[1].selectbox(
        "Filter by Day", ["All"] + DAYS_OF_WEEK, key="ref_f_day"
    )
    ref_f_prof = ref_fcols[2].selectbox(
        "Filter by Professor",
        ["All"] + sorted(df_edit["prof_id"].dropna().unique().tolist()),
        key="ref_f_prof"
    )

    df_display = df_edit.copy()
    if ref_f_course != "All":
        df_display = df_display[df_display["course_id"] == ref_f_course]
    if ref_f_day != "All":
        df_display = df_display[df_display["day"] == ref_f_day]
    if ref_f_prof != "All":
        df_display = df_display[df_display["prof_id"] == ref_f_prof]

    if "time_start" in df_display.columns:
        df_display = df_display.copy()
        df_display["time_start"] = df_display["time_start"].apply(format_minutes)
    if "time_end" in df_display.columns:
        df_display["time_end"] = df_display["time_end"].apply(format_minutes)
    if "room" in df_display.columns:
        df_display["room"] = df_display["room"].apply(format_room_name)

    st.caption(f"Showing {len(df_display)} of {len(df_edit)} assignments")
    st.dataframe(df_display, use_container_width=True, height=320)
