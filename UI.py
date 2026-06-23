import streamlit as st
import pandas as pd
import subprocess
import os
import re

st.set_page_config(page_title="IskHED Admin", layout="wide", initial_sidebar_state="expanded")

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def format_minutes(minutes):
    try:
        m_int = int(minutes)
        hours, mins = divmod(m_int, 60)
        period = "AM" if hours < 12 else "PM"
        hours_12 = hours % 12
        if hours_12 == 0:
            hours_12 = 12
        return f"{hours_12}:{mins:02d} {period}"
    except:
        return minutes


def parse_time_to_minutes(val):
    """Convert '8:00 AM' string or int back to minutes from midnight."""
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
    # Handle specific room codes: E401, S501, etc.
    if len(name) >= 4 and name[0] in ("E", "S") and name[1].isdigit():
        wing = "East Wing" if name[0] == "E" else "South Wing"
        return f"{wing} {name}"
    # Fallback for legacy wing-level codes
    formatted = name.replace("_", " ").title()
    fixes = {"1St": "1st", "2Nd": "2nd", "3Rd": "3rd", "4Th": "4th", "5Th": "5th", "6Th": "6th"}
    for wrong, right in fixes.items():
        formatted = formatted.replace(wrong, right)
    return formatted


# ==========================================
# COLOR PALETTE — per course
# ==========================================

COURSE_COLORS = [
    "#C62828", "#1565C0", "#2E7D32", "#6A1B9A", "#E65100",
    "#00695C", "#4527A0", "#AD1457", "#0277BD", "#558B2F",
    "#6D4C41", "#37474F", "#BF360C", "#01579B", "#33691E",
    "#880E4F", "#4E342E", "#1A237E", "#004D40", "#F57F17",
    "#263238", "#FF6F00", "#0D47A1", "#1B5E20", "#4A148C",
]


def get_course_color_map(df: pd.DataFrame) -> dict:
    """Assign a distinct color to each unique course_id."""
    courses = sorted(df["course_id"].dropna().unique().tolist())
    return {c: COURSE_COLORS[i % len(COURSE_COLORS)] for i, c in enumerate(courses)}


def make_style_fn(course_color_map: dict):
    """Returns a pandas styler function that colors cells by course."""
    def style_timetable(val):
        if val != "":
            course_id = str(val).split("|")[0].strip()
            color = course_color_map.get(course_id, "#880000")
            return (
                f"background-color: {color}; color: #FFFFFF; font-weight: 700; "
                f"border: 1px solid rgba(255,255,255,0.25); text-align: center;"
            )
        return "background-color: #FFFFFF; color: #333333; border: 1px solid #E0E0E0;"
    return style_timetable


def render_legend(course_color_map: dict):
    """Render a color legend below the timetable."""
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
[data-testid="stUploadedFile"] svg { color: var(--pup-maroon) !important; stroke: var(--pup-maroon) !important; }
[data-testid="stFileUploaderFile"] * { color: var(--text-dark) !important; font-weight: 600 !important; }
[data-testid="stFileUploaderFile"] svg { color: var(--pup-maroon) !important; fill: var(--pup-maroon) !important; }

.custom-header{ background:linear-gradient(135deg, #880000, #AA0000); border-radius:15px; padding:35px; margin-bottom:25px; box-shadow: 0px 4px 12px rgba(0,0,0,0.15); }
[data-testid="stAlert"]{ border-radius:12px !important; }
[data-testid="stDataFrame"]{ border-radius:10px; overflow:hidden; }
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
    master_path = "masterSchedule.xlsx"
    if os.path.exists(master_path):
        with open(master_path, "rb") as _f_sidebar:
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
        st.success("✨ Schedule finalized successfully!")
    else:
        st.error("Please upload the input constraints file first.")
        st.session_state.schedule_generated = False

st.divider()

# ==========================================
# TIMETABLE BUILDER (shared logic)
# ==========================================

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
TIME_BINS    = list(range(420, 1290, 30))   # 7:00 AM – 9:30 PM in 30-min steps
TIME_LABELS  = [format_minutes(t) for t in TIME_BINS]


def build_timetable_grid(df_filtered: pd.DataFrame, cell_fn) -> pd.DataFrame:
    """
    Build a (time_label × day) grid DataFrame.
    cell_fn(row) → cell text string for a given assignment row.
    """
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

            prof_cols  = [c for c in df_raw.columns if any(k in c.lower() for k in ("prof", "instructor", "faculty"))]
            block_cols = [c for c in df_raw.columns if any(k in c.lower() for k in ("block", "section"))]

            prof_col_name  = prof_cols[0]  if prof_cols  else None
            block_col_name = block_cols[0] if block_cols else None

            course_color_map = get_course_color_map(df_raw)

            schedule_view = st.radio(
                "Generate Firm Schedule For:",
                ["Students (By Block)", "Professors"],
                horizontal=True,
            )

            df_filtered  = df_raw
            selected_entity = "All"

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

            # --- TIMETABLE ---
            def student_cell(row):
                course = str(row.get("course_id", ""))
                prof   = str(row.get(prof_col_name, "")) if prof_col_name else ""
                room   = str(row.get("room", ""))
                return f"{course} | {prof} | {room}"

            def prof_cell(row):
                course = str(row.get("course_id", ""))
                block  = str(row.get(block_col_name, "")) if block_col_name else ""
                room   = str(row.get("room", ""))
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

            # --- DETAILED RECORDS (all rows, no limit) ---
            st.markdown("### 📋 Detailed Records")
            df_table = df_filtered.copy()
            if "time_start" in df_table.columns:
                df_table["time_start"] = df_table["time_start"].apply(format_minutes)
            if "time_end" in df_table.columns:
                df_table["time_end"] = df_table["time_end"].apply(format_minutes)
            st.dataframe(df_table, use_container_width=True, height=350)

            # Download button
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

            room_cols = [c for c in df_raw_rooms.columns if any(k in c.lower() for k in ("room", "location"))]
            prof_cols = [c for c in df_raw_rooms.columns if any(k in c.lower() for k in ("prof", "instructor", "faculty"))]

            course_color_map = get_course_color_map(df_raw_rooms)

            if room_cols:
                room_col_name = room_cols[0]
                room_list = ["All Rooms"] + sorted(df_raw_rooms[room_col_name].dropna().unique().tolist())
                selected_room = st.selectbox(f"🏫 Check Occupancy for {room_col_name}:", room_list)
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
                course = str(row.get("course_id", ""))
                room   = str(row.get("room", ""))
                prof   = str(row.get(prof_cols[0], "")) if prof_cols else ""
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
# VIEW 3: MANUAL ADJUSTMENTS
# ==========================================
elif st.session_state.active_tab == "Manual Adjustments":
    st.subheader("System Health & Manual Overrides")

    master_path = "masterSchedule.xlsx"
    if st.session_state.schedule_generated and os.path.exists(master_path):

        # --- ALGORITHM STATUS METRICS ---
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
            st.info("No Summary sheet found in the generated output.")

        # --- INTERACTIVE EDITOR ---
        try:
            st.markdown("### ✏️ Interactive Override Editor")
            st.write(
                "Double-click any cell to manually adjust assignments. "
                "Times are in minutes from midnight (e.g. 480 = 8:00 AM, 540 = 9:00 AM). "
                "Click **Save Changes** when done — changes update the Master Schedule immediately."
            )

            df_edit = pd.read_excel(master_path, sheet_name="All_Assignments")
            if "room" in df_edit.columns:
                df_edit["room"] = df_edit["room"].apply(format_room_name)

            edited_df = st.data_editor(
                df_edit,
                use_container_width=True,
                height=400,
                num_rows="dynamic",
            )

            save_col, dl_col = st.columns([2, 1])

            with save_col:
                if st.button("💾 Save Changes to Master Schedule", use_container_width=True):
                    try:
                        save_df = edited_df.copy()
                        # Convert time columns back to integer minutes if they were formatted
                        for tcol in ("time_start", "time_end"):
                            if tcol in save_df.columns:
                                save_df[tcol] = save_df[tcol].apply(parse_time_to_minutes)

                        # Preserve Summary sheet; replace All_Assignments
                        try:
                            existing_summary = pd.read_excel(master_path, sheet_name="Summary")
                        except Exception:
                            existing_summary = None

                        with pd.ExcelWriter(master_path, engine="openpyxl") as writer:
                            if existing_summary is not None:
                                existing_summary.to_excel(writer, sheet_name="Summary", index=False)
                            save_df.to_excel(writer, sheet_name="All_Assignments", index=False)

                        st.success("✅ Changes saved! Switch to Master Schedule to see updates.")
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

        except Exception as e:
            st.warning(f"Override editor not available: {e}")
    else:
        st.info("Generate a schedule to view system health and access manual overrides.")
