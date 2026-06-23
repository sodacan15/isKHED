import os
import re
import sys
import html as _html
import time

import pandas as pd
import streamlit as st
import subprocess

# ==========================================
# PAGE CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="IskHED Admin",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ==========================================
# HELPER FUNCTIONS
# ==========================================
def format_minutes(minutes):
    """Converts raw minutes (e.g. 480) to 12-hour format (e.g. '8:00 AM')."""
    try:
        m_int = int(minutes)
        hours, mins = divmod(m_int, 60)
        period = "AM" if hours < 12 else "PM"
        hours_12 = hours % 12 or 12
        return f"{hours_12}:{mins:02d} {period}"
    except Exception:
        return minutes


def format_room_name(name):
    """Cleans up database room names (e.g. '4th_east_wing' → '4th East Wing')."""
    if not isinstance(name, str):
        return name
    formatted = name.replace("_", " ").title()
    fixes = {
        "1St": "1st", "2Nd": "2nd", "3Rd": "3rd",
        "4Th": "4th", "5Th": "5th", "6Th": "6th",
    }
    for wrong, right in fixes.items():
        formatted = formatted.replace(wrong, right)
    return formatted


# ==========================================
# STYLING (PUP Theme)
# ==========================================
st.markdown("""
<style>
#MainMenu, footer, .stAppDeployButton { visibility: hidden; display: none; }

:root {
    --pup-maroon: #880000;
    --pup-dark:   #660000;
    --pup-gold:   #FFD700;
    --text-dark:  #333333;
}

header,
[data-testid="stHeader"]   { background-color: var(--pup-maroon) !important; }
.stApp                     { background-color: #F5F5F5 !important; }
[data-testid="stSidebar"]  { background-color: var(--pup-dark) !important; }

[data-testid="stAppViewContainer"] h1,
[data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3,
[data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] label,
[data-testid="stMetricValue"] div   { color: var(--text-dark) !important; }
[data-testid="stMetricLabel"] p     { color: #555555 !important; font-weight: 600 !important; }

.custom-header h1,
.custom-header span { color: white !important; font-size: 64px !important; font-weight: 900 !important; }
.custom-header p    { color: var(--pup-gold) !important; font-size: 20px !important; font-weight: 600 !important; }

[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] span { color: white !important; }

div[data-testid="stFileUploaderDropzone"] {
    background-color: #111827 !important;
    border: 1px solid #444 !important;
    border-radius: 12px !important;
}

div.stButton > button:first-child {
    background-color: var(--pup-gold) !important;
    border: none !important;
    border-radius: 12px !important;
    height: 50px !important;
}
div.stButton > button:first-child * {
    color: var(--pup-dark) !important;
    font-weight: 700 !important;
    font-size: 16px !important;
}
div.stButton > button:first-child:hover {
    background-color: #FFF2A8 !important;
    transform: translateY(-1px);
}

button[data-baseweb="tab"] *                      { color: var(--text-dark) !important; font-weight: 700 !important; font-size: 16px !important; }
button[data-baseweb="tab"][aria-selected="true"] *{ color: var(--pup-maroon) !important; }
button[data-baseweb="tab"][aria-selected="true"]  { border-bottom: 4px solid var(--pup-maroon) !important; }

.custom-header {
    background: linear-gradient(135deg, #880000, #AA0000);
    border-radius: 15px;
    padding: 35px;
    margin-bottom: 25px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}
[data-testid="stAlert"]     { border-radius: 12px !important; }
[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)


# ==========================================
# HEADER
# ==========================================
st.markdown("""
<div class="custom-header">
    <h1>IskHED</h1>
    <p>
        An Automated Scheduling System for Polytechnic University of the Philippines<br>
        College of Computer and Information Sciences (PUP CCIS)
    </p>
</div>
""", unsafe_allow_html=True)


# ==========================================
# SESSION STATE DEFAULTS
# ==========================================
st.session_state.setdefault("schedule_generated", False)
st.session_state.setdefault("active_schedule_path", "masterSchedule.xlsx")
st.session_state.setdefault("imported_schedule", False)


# ==========================================
# SIDEBAR
# ==========================================
st.sidebar.title("⚙️ Parameters")
st.sidebar.write("Upload the latest constraints to generate the schedule.")

uploaded_file  = st.sidebar.file_uploader("Upload inputSheet.xlsx", type=["xlsx"])
run_algorithms = st.sidebar.button("Generate Schedule", use_container_width=True)

st.sidebar.divider()
st.sidebar.markdown("**📂 Or import an existing schedule**")
st.sidebar.caption("Load a previously generated masterSchedule.xlsx without re-running the algorithm.")
imported_file = st.sidebar.file_uploader(
    "Upload masterSchedule.xlsx", type=["xlsx"], key="import_master"
)
if imported_file is not None:
    with open("masterSchedule_imported.xlsx", "wb") as f:
        f.write(imported_file.getbuffer())
    st.session_state.active_schedule_path = "masterSchedule_imported.xlsx"
    st.session_state.imported_schedule    = True
    st.session_state.schedule_generated   = True
    st.sidebar.success("Schedule loaded successfully.")

st.sidebar.divider()
st.sidebar.markdown("**🔁 Re-run from Imported Schedule**")
st.sidebar.caption(
    "Re-runs the algorithm using the inputSheet.xlsx already on disk. "
    "Import a master schedule first, then click below."
)
rerun_from_master = st.sidebar.button("🔁 Re-run from Imported Schedule", use_container_width=True)


# ==========================================
# CONSTANTS
# ==========================================
DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
TIME_BINS    = list(range(420, 1290, 30))
TIME_LABELS  = [format_minutes(t) for t in TIME_BINS]

STAGE_KEYWORDS = [
    ("Loading data",        0.05, "Loading data..."),
    ("CSP domain",          0.20, "CSP — building valid domains..."),
    ("MCV",                 0.35, "MCV — drafting initial schedule..."),
    ("Genetic Algorithm",   0.55, "GA — evolving populations..."),
    ("Simulated Annealing", 0.80, "SA — fine-tuning soft constraints..."),
    ("2nd CSP",             0.90, "Scheduling irregular students..."),
    ("master lists",        0.95, "Saving master schedule..."),
]

COLOR_PALETTE = [
    '#1f77b4','#ff7f0e','#2ca02c','#d62728','#9467bd',
    '#8c564b','#e377c2','#17becf','#bcbd22','#7f7f7f',
    '#aec7e8','#ffbb78','#98df8a','#ff9896','#c5b0d5',
    '#393b79','#637939','#8c6d31','#843c39','#7b4173',
]


# ==========================================
# TERMINAL HELPERS
# ==========================================
TERMINAL_CSS = """
<style>
.term-box {
    background: #0d1117;
    color: #c9d1d9;
    font-family: 'Courier New', Courier, monospace;
    font-size: 13px;
    padding: 16px;
    border-radius: 10px;
    height: 340px;
    overflow-y: auto;
    border: 1px solid #30363d;
    white-space: pre-wrap;
    word-break: break-all;
    line-height: 1.6;
}
.term-box .ok   { color: #3fb950; }
.term-box .warn { color: #d29922; }
.term-box .err  { color: #f85149; }
.term-box .info { color: #58a6ff; }
.term-box .ga   { color: #bc8cff; }
.term-box .sa   { color: #79c0ff; }
</style>
"""

TERMINAL_RULES = [
    ("✅", "ok"), ("❌", "err"), ("⚠️", "warn"),
    ("📂", "info"), ("🔀", "info"), ("🔍", "info"), ("🔄", "info"), ("📋", "info"),
    ("[GA]", "ga"), ("[SA]", "sa"), ("Generation", "ga"),
    ("Temp:", "sa"), ("fitness", "sa"), ("hard=", "warn"), ("soft=", "info"),
    ("violation", "err"), ("passed", "ok"), ("PASSED", "ok"), ("FAILED", "err"),
]


def colorize(line):
    safe = _html.escape(line)
    for token, cls in TERMINAL_RULES:
        if token in safe:
            safe = safe.replace(token, f'<span class="{cls}">{token}</span>', 1)
            break
    return safe


def render_terminal(placeholder, lines):
    body = "<br>".join(colorize(l) for l in lines)
    placeholder.markdown(
        f'<div class="term-box">{body}<a id="term-end"></a></div>'
        '<script>document.getElementById("term-end")?.scrollIntoView();</script>',
        unsafe_allow_html=True,
    )


# ==========================================
# SCHEDULE GENERATION PIPELINE
# ==========================================
def run_generation_pipeline():
    """Streams main.py output with a progress bar and live terminal."""
    col_prog, col_del = st.columns([3, 1])
    with col_prog:
        progress_bar   = st.progress(0)
        progress_label = st.empty()
    with col_del:
        if st.button("🗑️ Delete Current Generation", use_container_width=True):
            st.error("Generation interrupted.")
            st.session_state.schedule_generated = False
            st.stop()

    st.markdown("**🖥️ Live Algorithm Output**")
    st.markdown(TERMINAL_CSS, unsafe_allow_html=True)
    terminal_placeholder = st.empty()

    log_lines = ["$ python main.py", "─" * 48]
    render_terminal(terminal_placeholder, log_lines)

    proc = subprocess.Popen(
        [sys.executable, "-u", "main.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    last_update = time.time()
    stage_ptr   = 0

    for raw_line in proc.stdout:
        line = raw_line.rstrip()
        if not line:
            continue
        log_lines.append(line)
        if len(log_lines) > 120:
            log_lines = log_lines[-120:]

        for kw, pct, label in STAGE_KEYWORDS[stage_ptr:]:
            if kw.lower() in line.lower():
                progress_bar.progress(pct)
                progress_label.markdown(f"⏳ {label}")
                stage_ptr = STAGE_KEYWORDS.index((kw, pct, label)) + 1
                break

        if time.time() - last_update > 0.25:
            render_terminal(terminal_placeholder, log_lines)
            last_update = time.time()

    proc.wait()
    render_terminal(terminal_placeholder, log_lines)
    progress_bar.progress(1.0)
    progress_label.empty()

    if proc.returncode != 0:
        log_lines += ["─" * 48, "❌ Process exited with errors (see above)."]
        render_terminal(terminal_placeholder, log_lines)
        st.error("Pipeline error — check the terminal output above.")
        st.session_state.schedule_generated = False
    else:
        log_lines += ["─" * 48, "✅ Schedule generation complete."]
        render_terminal(terminal_placeholder, log_lines)
        st.session_state.schedule_generated = True
        st.success("✨ Schedule finalized successfully!")


# ==========================================
# TIMETABLE HELPERS
# ==========================================
def build_timetable_grid(df, schedule_view, prof_col, block_col):
    grid = pd.DataFrame("", index=TIME_LABELS, columns=DAYS_OF_WEEK)
    selected_room = None  # only used in room view

    for _, row in df.iterrows():
        day = row.get("day")
        if day not in DAYS_OF_WEEK:
            continue
        try:
            start  = int(row["time_start"])
            end    = int(row["time_end"])
            course = str(row.get("course_id", ""))
            room   = str(row.get("room", ""))
            prof   = str(row.get(prof_col, "")) if prof_col else ""
            block  = str(row.get(block_col, "")) if block_col else ""

            cell = f"{course} | {prof} | {room}" if schedule_view == "Students (By Block)" \
                   else f"{course} | {block} | {room}"

            for t, t_label in zip(TIME_BINS, TIME_LABELS):
                if start <= t < end:
                    if grid.at[t_label, day] == "":
                        grid.at[t_label, day] = cell
                    else:
                        grid.at[t_label, day] += f" \n🛑 {cell}"
        except Exception:
            pass

    return grid


def style_timetable(course_colors):
    def _style(val):
        if val == "":
            return "background-color:#FFFFFF;color:#333333;border:1px solid #E0E0E0;"
        cid = val.split(" | ")[0].strip()
        bg  = course_colors.get(cid, "#880000")
        return (
            f"background-color:{bg};color:#FFFFFF;font-weight:700;"
            "border:1px solid rgba(255,255,255,0.3);text-align:center;"
        )
    return _style


def style_timetable_rooms(val):
    if val == "":
        return "background-color:#FFFFFF;color:#333333;border:1px solid #E0E0E0;"
    return "background-color:#880000;color:#FFFFFF;font-weight:700;border:1px solid rgba(255,255,255,0.3);text-align:center;"


def apply_style(df_style, fn):
    try:
        return df_style.map(fn)
    except AttributeError:
        return df_style.applymap(fn)


def display_timetable(df_filtered, schedule_view, prof_col, block_col):
    unique_cids    = sorted(df_filtered["course_id"].dropna().unique()) if "course_id" in df_filtered.columns else []
    course_colors  = {cid: COLOR_PALETTE[i % len(COLOR_PALETTE)] for i, cid in enumerate(unique_cids)}

    grid        = build_timetable_grid(df_filtered, schedule_view, prof_col, block_col)
    styled_grid = apply_style(grid.style, style_timetable(course_colors))
    st.dataframe(styled_grid, use_container_width=True, height=500)

    if course_colors:
        st.markdown("**🎨 Color Legend:**")
        legend_html = " ".join(
            f'<span style="background:{c};color:#fff;padding:4px 12px;border-radius:5px;'
            f'margin:3px;font-size:12px;font-weight:bold;display:inline-block">{cid}</span>'
            for cid, c in sorted(course_colors.items())
        )
        st.markdown(legend_html, unsafe_allow_html=True)


# ==========================================
# TABS
# ==========================================
tab1, tab2, tab3 = st.tabs(["📊 Master Schedule", "🏢 Room Allocations", "⚠️ Manual Adjustments"])


# ------------------------------------------
# TAB 1 — MASTER SCHEDULE
# ------------------------------------------
with tab1:
    st.subheader("Firm Master Schedules")

    # Re-run from imported schedule
    _do_generate = False
    if rerun_from_master:
        if st.session_state.imported_schedule and st.session_state.active_schedule_path:
            try:
                from migrate_master_to_input import migrate
                with st.spinner("Migrating imported schedule's constraints to inputSheet format..."):
                    counts = migrate(st.session_state.active_schedule_path, "inputSheet.xlsx")
                st.success(
                    f"✅ Migration complete — "
                    f"{counts.get('Professors', 0)} professors, "
                    f"{counts.get('Courses', 0)} courses, "
                    f"{counts.get('Rooms', 0)} rooms, "
                    f"{counts.get('Blocks', 0)} blocks loaded. "
                    "Running algorithm now…"
                )
                st.session_state.active_schedule_path = "masterSchedule.xlsx"
                st.session_state.imported_schedule    = False
                _do_generate = True
            except Exception as mig_err:
                st.error(f"Migration failed: {mig_err}")
        else:
            st.warning("Please import a masterSchedule.xlsx first using the sidebar uploader.")

    # Normal generate or re-run
    if run_algorithms or _do_generate:
        if uploaded_file is not None and not _do_generate:
            with open("inputSheet.xlsx", "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.session_state.active_schedule_path = "masterSchedule.xlsx"
            st.session_state.imported_schedule    = False

        if uploaded_file is not None or _do_generate:
            run_generation_pipeline()
        else:
            st.error("Please upload the input constraints file first.")
            st.session_state.schedule_generated = False

    # Imported-schedule banner
    if st.session_state.imported_schedule and st.session_state.schedule_generated:
        st.info("📂 Viewing an imported master schedule. Use '🔁 Re-run from Imported Schedule' to re-run the algorithm with these constraints.")

    # Display schedule
    schedule_ready = st.session_state.schedule_generated and (
        uploaded_file is not None or st.session_state.imported_schedule or _do_generate
    )

    if schedule_ready:
        try:
            df_raw = pd.read_excel(st.session_state.active_schedule_path, sheet_name="All_Assignments")
            if "room" in df_raw.columns:
                df_raw["room"] = df_raw["room"].apply(format_room_name)

            prof_cols  = [c for c in df_raw.columns if any(k in c.lower() for k in ("prof", "instructor", "faculty"))]
            block_cols = [c for c in df_raw.columns if any(k in c.lower() for k in ("block", "section"))]
            prof_col   = prof_cols[0]  if prof_cols  else None
            block_col  = block_cols[0] if block_cols else None

            schedule_view = st.radio("Generate Firm Schedule For:", ["Students (By Block)", "Professors"], horizontal=True)
            df_filtered   = df_raw

            if schedule_view == "Students (By Block)" and block_col:
                block_list    = ["All Blocks"] + sorted(df_raw[block_col].dropna().unique().tolist())
                selected      = st.selectbox("🔍 Select Block/Section:", block_list)
                if selected != "All Blocks":
                    df_filtered = df_raw[df_raw[block_col] == selected]
                    st.markdown(f"### 🎓 Official Schedule: {selected}")

            elif schedule_view == "Professors" and prof_col:
                prof_list = ["All Professors"] + sorted(df_raw[prof_col].dropna().unique().tolist())
                selected  = st.selectbox("🔍 Select Professor:", prof_list)
                if selected != "All Professors":
                    df_filtered = df_raw[df_raw[prof_col] == selected]
                    st.markdown(f"### 👨‍🏫 Official Schedule: {selected}")

            display_timetable(df_filtered, schedule_view, prof_col, block_col)

            st.markdown("### 📋 Detailed Records")
            df_table = df_filtered.copy()
            for col in ("time_start", "time_end"):
                if col in df_table.columns:
                    df_table[col] = df_table[col].apply(format_minutes)
            st.dataframe(df_table, use_container_width=True, height=420)

        except Exception as e:
            st.warning(f"Could not load master schedule. Error: {e}")

    elif not run_algorithms and not rerun_from_master and not st.session_state.schedule_generated:
        st.info("Upload the input file and click 'Generate Schedule' to view the timetable.")


# ------------------------------------------
# TAB 2 — ROOM ALLOCATIONS
# ------------------------------------------
with tab2:
    st.subheader("Room Occupancy Matrix")

    room_view_ready = st.session_state.schedule_generated and (
        uploaded_file is not None
        or st.session_state.imported_schedule
        or os.path.exists(st.session_state.active_schedule_path)
    )

    if room_view_ready:
        try:
            df_rooms = pd.read_excel(st.session_state.active_schedule_path, sheet_name="All_Assignments")
            if "room" in df_rooms.columns:
                df_rooms["room"] = df_rooms["room"].apply(format_room_name)

            room_cols = [c for c in df_rooms.columns if any(k in c.lower() for k in ("room", "location"))]
            prof_cols = [c for c in df_rooms.columns if any(k in c.lower() for k in ("prof", "instructor", "faculty"))]

            if room_cols:
                room_col      = room_cols[0]
                room_list     = ["All Rooms"] + sorted(df_rooms[room_col].dropna().unique().tolist())
                selected_room = st.selectbox(f"🏫 Check Occupancy for {room_col}:", room_list)
                df_room_view  = df_rooms if selected_room == "All Rooms" else df_rooms[df_rooms[room_col] == selected_room]
            else:
                selected_room = "All Rooms"
                df_room_view  = df_rooms

            st.markdown("### 🗓️ Visual Room Occupancy")
            grid_rooms = pd.DataFrame("", index=TIME_LABELS, columns=DAYS_OF_WEEK)

            for _, row in df_room_view.iterrows():
                day = row.get("day")
                if day not in DAYS_OF_WEEK:
                    continue
                try:
                    start  = int(row["time_start"])
                    end    = int(row["time_end"])
                    course = str(row.get("course_id", ""))
                    room   = str(row.get("room", ""))
                    prof   = str(row.get(prof_cols[0], "")) if prof_cols else ""

                    cell = f"{course} | {prof}" if selected_room != "All Rooms" else f"{course} | {room}"

                    for t, t_label in zip(TIME_BINS, TIME_LABELS):
                        if start <= t < end:
                            if grid_rooms.at[t_label, day] == "":
                                grid_rooms.at[t_label, day] = cell
                            else:
                                grid_rooms.at[t_label, day] += f" 🛑 {cell}"
                except Exception:
                    pass

            st.dataframe(
                apply_style(grid_rooms.style, style_timetable_rooms),
                use_container_width=True,
                height=500,
            )

            df_room_table = df_room_view.copy()
            for col in ("time_start", "time_end"):
                if col in df_room_table.columns:
                    df_room_table[col] = df_room_table[col].apply(format_minutes)
            st.dataframe(df_room_table, use_container_width=True, height=250)

        except Exception:
            st.warning("Room data not available. Please generate the schedule first.")
    else:
        st.info("Generate a schedule to view room allocations.")


# ------------------------------------------
# TAB 3 — MANUAL ADJUSTMENTS
# ------------------------------------------
with tab3:
    st.subheader("System Health & Manual Overrides")

    adjustments_ready = st.session_state.schedule_generated and (
        uploaded_file is not None
        or st.session_state.imported_schedule
        or os.path.exists(st.session_state.active_schedule_path)
    )

    if adjustments_ready:

        # ── Shared helpers ────────────────────────────────────────────
        def _cid(slot):        return str(slot.get("course_id", "?")).split("__")[0]
        def _sec(slot):        return str(slot.get("block", "?"))
        def _day(slot):        return str(slot.get("day", "?"))
        def _fmt_time(m):
            try:
                h, mn = divmod(int(m), 60)
                p = "AM" if h < 12 else "PM"
                return f"{h % 12 or 12}:{mn:02d} {p}"
            except Exception:
                return str(m)
        def _time_range(slot): return f"{_fmt_time(slot.get('time_start','?'))}–{_fmt_time(slot.get('time_end','?'))}"

        HARD_COLOR_MAP = {
            "👨‍🏫 Professor Double-Booking": "#3d1a1a",
            "🏫 Room Double-Booking":        "#1a2d3d",
            "🔄 Modality Mix":               "#2d2a1a",
            "🎓 Block Overlap":              "#1a2d1a",
            "🧪 Lab Not F2F":                "#2d1a2d",
            "⏰ Outside Allowed Hours":       "#1a1a2d",
            "📍 Invalid Room":               "#2d2d1a",
            "📅 Sunday Class":               "#2d1a1a",
        }

        def _style_hard(row, color_map=HARD_COLOR_MAP):
            bg = color_map.get(row["Type"], "#1a1a1a")
            return [f"background-color:{bg};color:#e6edf3"] * len(row)

        # ── Load All_Assignments for live re-check ────────────────────
        df_conflicts   = pd.read_excel(st.session_state.active_schedule_path, sheet_name="All_Assignments")
        schedule_dicts = df_conflicts.to_dict(orient="records")
        for s in schedule_dicts:
            for key in ("time_start", "time_end"):
                try:    s[key] = int(s[key])
                except: s[key] = 0
            for key in ("is_lab", "is_nstp"):
                s[key] = bool(s.get(key, False))
            if not s.get("block"):
                s["block"] = f"Year {s.get('year_level', '?')}"

        # ── Run live conflict check ───────────────────────────────────
        report = {}
        try:
            from csp_mcv import resolve_conflicts
            report = resolve_conflicts(schedule_dicts)
        except Exception as rc_err:
            st.caption(f"ℹ️ Live conflict re-check unavailable: {rc_err}")

        # ── Summary card (source of truth = Summary sheet) ────────────
        st.markdown("### 📊 Schedule Status")
        total_assign = len(schedule_dicts)
        hard_count   = sum(len(report.get(k, [])) for k in (
            "professor_conflicts","room_conflicts","modality_conflicts","block_overlaps",
            "lab_mode_violations","time_bound_violations","location_violations","sunday_violations",
        ))
        soft_count   = 0
        status_val   = "UNKNOWN"

        try:
            df_summary = pd.read_excel(st.session_state.active_schedule_path, sheet_name="Summary")
            if not df_summary.empty:
                _row         = df_summary.iloc[0]
                total_assign = int(_row.get("total_assignments", total_assign))
                # Use live hard_count from resolve_conflicts if available, else fall back to sheet
                if hard_count == 0 and report:
                    hard_count = int(_row.get("hard_violations", hard_count))
                soft_count   = int(_row.get("soft_suggestions", 0))
                status_val   = str(_row.get("status", "UNKNOWN"))
        except Exception:
            pass

        # Derive status from live count if sheet says UNKNOWN
        if status_val == "UNKNOWN":
            status_val = "PASSED" if hard_count == 0 else "REQUIRES REVIEW"
        status_color = "#3fb950" if status_val == "PASSED" else "#f85149"
        status_icon  = "✅"       if status_val == "PASSED" else "❌"

        st.markdown(f"""
<div style="background:#161b22;border:1px solid #30363d;border-radius:12px;
            padding:20px 28px;margin-bottom:18px;display:flex;gap:40px;
            align-items:center;flex-wrap:wrap;">
    <div style="flex:1;min-width:140px;text-align:center;">
        <div style="font-size:32px;font-weight:900;color:#58a6ff;">{total_assign}</div>
        <div style="font-size:13px;color:#8b949e;margin-top:4px;">Total Assignments</div>
    </div>
    <div style="flex:1;min-width:140px;text-align:center;">
        <div style="font-size:32px;font-weight:900;color:#f85149;">{hard_count}</div>
        <div style="font-size:13px;color:#8b949e;margin-top:4px;">Hard Violations</div>
    </div>
    <div style="flex:1;min-width:140px;text-align:center;">
        <div style="font-size:32px;font-weight:900;color:#d29922;">{soft_count}</div>
        <div style="font-size:13px;color:#8b949e;margin-top:4px;">Soft Suggestions</div>
    </div>
    <div style="flex:1;min-width:140px;text-align:center;">
        <div style="font-size:28px;font-weight:900;color:{status_color};">{status_icon} {status_val}</div>
        <div style="font-size:13px;color:#8b949e;margin-top:4px;">Overall Status</div>
    </div>
</div>
""", unsafe_allow_html=True)

        # ── Download button ───────────────────────────────────────────
        sched_path = st.session_state.active_schedule_path
        if os.path.exists(sched_path):
            with open(sched_path, "rb") as f:
                st.download_button(
                    label="⬇️ Download masterSchedule.xlsx",
                    data=f.read(),
                    file_name="masterSchedule.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

        st.divider()

        # ── Hard violations table ─────────────────────────────────────
        st.markdown("### ❌ Hard Constraint Violations")

        CATEGORIES = [
            ("professor_conflicts",   "👨‍🏫 Professor Double-Booking", 2),
            ("room_conflicts",        "🏫 Room Double-Booking",        2),
            ("modality_conflicts",    "🔄 Modality Mix",               2),
            ("block_overlaps",        "🎓 Block Overlap",              2),
            ("lab_mode_violations",   "🧪 Lab Not F2F",                1),
            ("time_bound_violations", "⏰ Outside Allowed Hours",       1),
            ("location_violations",   "📍 Invalid Room",               1),
            ("sunday_violations",     "📅 Sunday Class",               1),
        ]

        hard_rows = []
        for key, label, arity in CATEGORIES:
            for item in report.get(key, []):
                try:
                    if arity == 2:
                        s1, s2, _ = item
                        hard_rows.append({
                            "Type":    label,
                            "Course":  f"{_cid(s1)} & {_cid(s2)}",
                            "Section": _sec(s1),
                            "Day":     _day(s1),
                            "Time":    _time_range(s1),
                            "Reason":  f"{label}: {_cid(s1)} [Sec {_sec(s1)}] and "
                                       f"{_cid(s2)} [Sec {_sec(s2)}] overlap on "
                                       f"{_day(s1)} at {_time_range(s1)}",
                        })
                    else:
                        s1, _ = item
                        hard_rows.append({
                            "Type":    label,
                            "Course":  _cid(s1),
                            "Section": _sec(s1),
                            "Day":     _day(s1),
                            "Time":    _time_range(s1),
                            "Reason":  f"{label}: [{_cid(s1)}][Sec {_sec(s1)}] on "
                                       f"{_day(s1)} at {_time_range(s1)}",
                        })
                except Exception:
                    pass

        # If live check found 0 but summary sheet says there are violations,
        # show a warning so the user knows the table may be incomplete.
        if not hard_rows and hard_count > 0:
            st.warning(
                f"⚠️ The summary sheet reports **{hard_count}** hard violation(s), but the live "
                "re-check returned none. This usually means the violation keys returned by "
                "`resolve_conflicts` don't match the expected category names. "
                "Check `csp_mcv.resolve_conflicts` return keys."
            )
            # Expose actual report keys for debugging
            if report:
                st.caption(f"Keys returned by resolve_conflicts: `{list(report.keys())}`")
        elif not hard_rows:
            st.success("✅ No hard constraint violations — schedule is fully compliant.")
        else:
            st.error(f"⚠️ {len(hard_rows)} hard violation(s) found.")
            df_hard = pd.DataFrame(hard_rows)[["Type", "Course", "Section", "Day", "Time", "Reason"]]
            st.dataframe(
                df_hard.style.apply(_style_hard, axis=1),
                use_container_width=True,
                hide_index=True,
                height=min(38 * len(hard_rows) + 38, 400),
            )

        st.divider()

        # ── Soft suggestions ──────────────────────────────────────────
        st.markdown("### ⚠️ Soft Constraint Suggestions")
        try:
            from constraint_check import check_soft_constraints
            from database_access  import load_professors_excel, load_students_excel

            _profs    = load_professors_excel("inputSheet.xlsx")
            _students = load_students_excel("inputSheet.xlsx")
            _po_days  = []
            try:
                from database_access import load_power_outage_excel
                _po_days = load_power_outage_excel("inputSheet.xlsx")
            except Exception:
                pass

            soft_warnings = check_soft_constraints(schedule_dicts, _profs, _students, _po_days)

            if not soft_warnings:
                st.success("✅ No soft constraint suggestions.")
            else:
                st.warning(f"ℹ️ {len(soft_warnings)} suggestion(s) to review.")

                TAG_MAP = {
                    "BREAK":         ("⏸️ Insufficient Break",       "Professor has back-to-back classes without adequate rest."),
                    "MODALITY_GAP":  ("🔄 Modality Switch Gap",      "Less than 3-hour gap between F2F and online classes."),
                    "PREFERENCE":    ("💬 Prof Preference Mismatch", "Assigned mode doesn't match professor's preference."),
                    "POWER_OUTAGE":  ("⚡ Power Outage Day",         "Class scheduled on a power outage day — consider relocation."),
                    "IRREGULAR":     ("🎓 Irregular Adjacency",      "Retaken course may not be adjacent to year-level classes."),
                    "NO_CLASS_DAYS": ("📅 Too Many Class Days",      "Block has more than 4 scheduled weekdays."),
                }

                soft_rows = []
                for w in soft_warnings:
                    tag_match  = re.search(r"\[([A-Z_]+)\]", w)
                    tag        = tag_match.group(1) if tag_match else "OTHER"
                    type_label, reason_base = TAG_MAP.get(tag, (f"ℹ️ {tag}", w))

                    course_match  = re.search(r"course\s+([\w_]+)", w, re.I)
                    section_match = re.search(r"[Bb]lock\s+([\w\-]+)", w)
                    prof_match    = re.search(r"Prof\s+([\w_]+)", w)

                    readable = w
                    for old_tag in TAG_MAP:
                        readable = readable.replace(f"[{old_tag}]", "").strip()

                    soft_rows.append({
                        "Type":       type_label,
                        "Course":     course_match.group(1)  if course_match  else "—",
                        "Section":    section_match.group(1) if section_match else "—",
                        "Involves":   prof_match.group(1)    if prof_match    else "—",
                        "Suggestion": reason_base,
                        "Detail":     readable,
                    })

                st.dataframe(
                    pd.DataFrame(soft_rows)[["Type", "Course", "Section", "Involves", "Suggestion", "Detail"]],
                    use_container_width=True,
                    hide_index=True,
                    height=min(38 * len(soft_rows) + 38, 400),
                )

        except Exception as soft_err:
            st.info(f"Soft constraint check not available: {soft_err}")

        st.divider()

        # ── Manual editor ─────────────────────────────────────────────
        try:
            st.markdown("### ✏️ Interactive Override Editor")
            st.write("Double-click any cell below to manually fix soft constraints or override assignments.")

            df_edit = pd.read_excel(st.session_state.active_schedule_path, sheet_name="All_Assignments")
            if "room" in df_edit.columns:
                df_edit["room"] = df_edit["room"].apply(format_room_name)
            for col in ("time_start", "time_end"):
                if col in df_edit.columns:
                    df_edit[col] = df_edit[col].apply(format_minutes)

            edited_df = st.data_editor(df_edit, use_container_width=True, height=400, num_rows="dynamic")

            if st.button("💾 Save Manual Overrides", use_container_width=True):
                try:
                    out_path = "masterSchedule_Overridden.xlsx"
                    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
                        original_wb = pd.ExcelFile(st.session_state.active_schedule_path)
                        for sheet in original_wb.sheet_names:
                            if sheet != "All_Assignments":
                                pd.read_excel(
                                    st.session_state.active_schedule_path, sheet_name=sheet
                                ).to_excel(writer, sheet_name=sheet, index=False)
                        edited_df.to_excel(writer, sheet_name="All_Assignments", index=False)

                    st.session_state.active_schedule_path = out_path
                    st.success("✅ Overrides saved! Master Schedule and Room Allocations now reflect your changes.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to save overrides: {e}")

        except Exception:
            st.warning("Override data not available.")

    else:
        st.info("Generate a schedule to view system health and access manual overrides.")
