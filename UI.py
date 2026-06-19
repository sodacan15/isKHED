import streamlit as st
import pandas as pd
import subprocess
import os

# ==========================================
# PAGE CONFIGURATION
# ==========================================
# We set the sidebar to expanded so the navigation menu is visible immediately
st.set_page_config(page_title="IskHED Admin", layout="wide", initial_sidebar_state="expanded")

# ==========================================
# HELPER FUNCTIONS (Formatting & UI Logic)
# ==========================================
def format_minutes(minutes):
    """Converts raw minutes (e.g., 480) into readable 12-hour format (e.g., 8:00 AM)"""
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

def format_room_name(name):
    """Cleans up database room names (e.g., '4th_east_wing' -> '4th East Wing')"""
    if not isinstance(name, str): return name
    formatted = name.replace("_", " ").title()
    fixes = {"1St": "1st", "2Nd": "2nd", "3Rd": "3rd", "4Th": "4th", "5Th": "5th", "6Th": "6th"}
    for wrong, right in fixes.items():
        formatted = formatted.replace(wrong, right)
    return formatted

# ==========================================
# SAFE CSS STYLING (PUP Theme & Layout Fixes)
# ==========================================
st.markdown("""
<style>
/* Hide Streamlit defaults for a cleaner app look */
#MainMenu {visibility:hidden;}
footer {visibility:hidden;}
.stAppDeployButton {display:none;}

/* Core PUP Color Variables */
:root{
    --pup-maroon:#880000;
    --pup-dark:#660000;
    --pup-gold:#FFD700;
    --text-dark:#333333;
}

/* Force Header and Backgrounds */
header { background-color: var(--pup-maroon) !important; }
[data-testid="stHeader"]{ background-color: var(--pup-maroon) !important; }
.stApp{ background-color:#F5F5F5 !important; }
[data-testid="stSidebar"]{ background-color:var(--pup-dark) !important; }

/* Force standard text to be readable dark grey */
[data-testid="stAppViewContainer"] h1, 
[data-testid="stAppViewContainer"] h2, 
[data-testid="stAppViewContainer"] h3, 
[data-testid="stAppViewContainer"] p, 
[data-testid="stAppViewContainer"] label,
[data-testid="stMetricValue"] div { color: var(--text-dark) !important; }
[data-testid="stMetricLabel"] p { color: #555555 !important; font-weight: 600 !important; }

/* Protect Custom Header text colors */
.custom-header h1, .custom-header span { color: white !important; font-size:64px !important; font-weight:900 !important; }
.custom-header p { color: var(--pup-gold) !important; font-size:20px !important; font-weight:600 !important; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3, [data-testid="stSidebar"] p, [data-testid="stSidebar"] label, [data-testid="stSidebar"] span { color: white !important; }

/* Form UI styling (Buttons & Uploaders) */
div[data-testid="stFileUploaderDropzone"]{ background-color:#111827 !important; border:1px solid #444 !important; border-radius:12px !important; }
div[data-testid="stFileUploaderDropzone"] * { color: white !important; }
div.stButton > button:first-child{ background-color:var(--pup-gold) !important; border:none !important; border-radius:12px !important; height:50px !important; }
div.stButton > button:first-child * { color:var(--pup-dark) !important; font-weight:700 !important; font-size:16px !important; }
div.stButton > button:first-child:hover{ background-color:#FFF2A8 !important; transform:translateY(-1px); }

/* --- FIX FOR INVISIBLE FILE UPLOAD NAME AND ICON --- */
[data-testid="stUploadedFile"] * { color: var(--text-dark) !important; font-weight: 600 !important; }
[data-testid="stUploadedFile"] svg { color: var(--pup-maroon) !important; stroke: var(--pup-maroon) !important; }
[data-testid="stFileUploaderFile"] * { color: var(--text-dark) !important; font-weight: 600 !important; }
[data-testid="stFileUploaderFile"] svg { color: var(--pup-maroon) !important; fill: var(--pup-maroon) !important; }

/* Layout Containers */
.custom-header{ background:linear-gradient(135deg, #880000, #AA0000); border-radius:15px; padding:35px; margin-bottom:25px; box-shadow: 0px 4px 12px rgba(0,0,0,0.15); }
[data-testid="stAlert"]{ border-radius:12px !important; }
[data-testid="stDataFrame"]{ border-radius:10px; overflow:hidden; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# MAIN APP HEADER
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
# SESSION STATE INITIALIZATION
# ==========================================
if 'schedule_generated' not in st.session_state:
    st.session_state.schedule_generated = False

if 'active_tab' not in st.session_state:
    st.session_state.active_tab = "Master Schedule"

# ==========================================
# SIDEBAR NAVIGATION MENU
# ==========================================
st.sidebar.markdown("### 📌 Navigation Menu")
st.sidebar.divider()

if st.sidebar.button("📊 Master Schedule", use_container_width=True):
    st.session_state.active_tab = "Master Schedule"

if st.sidebar.button("🏢 Room Allocations", use_container_width=True):
    st.session_state.active_tab = "Room Allocations"
    
if st.sidebar.button("⚠️ Manual Adjustments", use_container_width=True):
    st.session_state.active_tab = "Manual Adjustments"

# Delete button only shows up if a schedule exists
if st.session_state.schedule_generated:
    st.sidebar.markdown("<br><br>", unsafe_allow_html=True) # Spacer
    if st.sidebar.button("🗑️ Delete Generation", use_container_width=True):
        st.session_state.schedule_generated = False
        st.rerun()

# ==========================================
# TOP SECTION: UPLOAD & GENERATE
# ==========================================
st.markdown("### ⚙️ System Parameters")
st.write("Upload the latest constraints to generate the schedule.")

upload_col, btn_col = st.columns([3, 1])

with upload_col:
    uploaded_file = st.file_uploader("Upload inputSheet.xlsx", type=["xlsx"], label_visibility="collapsed")

with btn_col:
    # Add a little spacing so the button aligns nicely with the uploader
    st.markdown("<div style='margin-top: 2px;'></div>", unsafe_allow_html=True)
    run_algorithms = st.button("Generate Schedule", use_container_width=True)

# Handle the generation logic immediately after the button
if run_algorithms:
    if uploaded_file is not None:
        with st.spinner('Running the Algorithm... Please wait.'):
            # Save upload to local directory for backend script
            with open("inputSheet.xlsx", "wb") as f:
                f.write(uploaded_file.getbuffer())
            # Execute backend algorithm
            subprocess.run(["python", "main.py"]) 
            st.session_state.schedule_generated = True
        st.success("✨ Schedule finalized successfully!")
    else:
        st.error("Please upload the input constraints file first.")
        st.session_state.schedule_generated = False

st.divider()

# ==========================================
# MAIN CONTENT VIEWS
# ==========================================

# ------------------------------------------
# VIEW 1: MASTER SCHEDULE
# ------------------------------------------
if st.session_state.active_tab == "Master Schedule":
    st.subheader("Firm Master Schedules")
    
    if st.session_state.schedule_generated and uploaded_file is not None:
        try:
            # Read output from backend
            df_raw = pd.read_excel("masterSchedule.xlsx", sheet_name="All_Assignments") 
            
            if 'room' in df_raw.columns: df_raw['room'] = df_raw['room'].apply(format_room_name)
            
            # Dynamically identify relevant columns
            prof_cols = [col for col in df_raw.columns if 'prof' in col.lower() or 'instructor' in col.lower() or 'faculty' in col.lower()]
            block_cols = [col for col in df_raw.columns if 'block' in col.lower() or 'section' in col.lower()]
            
            prof_col_name = prof_cols[0] if prof_cols else None
            block_col_name = block_cols[0] if block_cols else None

            # Toggle switch for audience view
            schedule_view = st.radio("Generate Firm Schedule For:", ["Students (By Block)", "Professors"], horizontal=True)
            
            df_filtered = df_raw
            selected_entity = "All"
            
            # Apply appropriate filters based on toggle selection
            if schedule_view == "Students (By Block)" and block_col_name:
                block_list = ["All Blocks"] + sorted(df_raw[block_col_name].dropna().unique().tolist())
                selected_entity = st.selectbox(f"🔍 Select Block/Section:", block_list)
                if selected_entity != "All Blocks":
                    df_filtered = df_raw[df_raw[block_col_name] == selected_entity]
                    st.markdown(f"### 🎓 Official Schedule: {selected_entity}")
                    
            elif schedule_view == "Professors" and prof_col_name:
                prof_list = ["All Professors"] + sorted(df_raw[prof_col_name].dropna().unique().tolist())
                selected_entity = st.selectbox(f"🔍 Select Professor:", prof_list)
                if selected_entity != "All Professors":
                    df_filtered = df_raw[df_raw[prof_col_name] == selected_entity]
                    st.markdown(f"### 👨‍🏫 Official Schedule: {selected_entity}")

            # --- VISUAL TIMETABLE MATRIX ---
            days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            time_bins = list(range(420, 1290, 30)) # Generates slots from 7:00 AM to 9:30 PM
            time_labels = [format_minutes(t) for t in time_bins]
            
            grid_df = pd.DataFrame("", index=time_labels, columns=days_of_week)
            
            # Populate visual grid
            for _, row in df_filtered.iterrows():
                day = row.get('day')
                if day not in days_of_week: continue
                
                try:
                    start = int(row['time_start'])
                    end = int(row['time_end'])
                    course = str(row.get('course_id', ''))
                    room = str(row.get('room', ''))
                    prof = str(row.get(prof_col_name, '')) if prof_col_name else ''
                    block = str(row.get(block_col_name, '')) if block_col_name else ''
                    
                    if schedule_view == "Students (By Block)":
                        cell_text = f"{course} | {prof} | {room}"
                    else:
                        cell_text = f"{course} | {block} | {room}"
                        
                    for t, t_label in zip(time_bins, time_labels):
                        if start <= t < end:
                            if grid_df.at[t_label, day] == "":
                                grid_df.at[t_label, day] = cell_text
                            else:
                                grid_df.at[t_label, day] += f" \n🛑 {cell_text}" 
                except:
                    pass 
                    
            def style_timetable(val):
                """Colors cells maroon if occupied, white if empty"""
                if val != "":
                    return 'background-color: #880000; color: #FFFFFF; font-weight: 700; border: 1px solid #FFD700; text-align: center;'
                return 'background-color: #FFFFFF; color: #333333; border: 1px solid #E0E0E0;'

            try:
                styled_grid = grid_df.style.map(style_timetable)
            except AttributeError:
                styled_grid = grid_df.style.applymap(style_timetable)
                
            st.dataframe(styled_grid, use_container_width=True, height=500)
            
            # --- DETAILED RAW DATA LOG ---
            st.markdown("### 📋 Detailed Records")
            df_table = df_filtered.copy()
            if 'time_start' in df_table.columns: df_table['time_start'] = df_table['time_start'].apply(format_minutes)
            if 'time_end' in df_table.columns: df_table['time_end'] = df_table['time_end'].apply(format_minutes)
            st.dataframe(df_table, use_container_width=True, height=250) 
            
        except Exception as e:
            st.warning(f"Could not load master schedule. Error: {e}")
            
    else:
        st.info("Upload the input file and click 'Generate Schedule' to view the timetable.")

# ------------------------------------------
# VIEW 2: ROOM ALLOCATIONS
# ------------------------------------------
elif st.session_state.active_tab == "Room Allocations":
    st.subheader("Room Occupancy Matrix")
    
    if st.session_state.schedule_generated and uploaded_file is not None:
        try:
            df_raw_rooms = pd.read_excel("masterSchedule.xlsx", sheet_name="All_Assignments") 
            
            if 'room' in df_raw_rooms.columns: df_raw_rooms['room'] = df_raw_rooms['room'].apply(format_room_name)
            
            room_cols = [col for col in df_raw_rooms.columns if 'room' in col.lower() or 'location' in col.lower()]
            prof_cols = [col for col in df_raw_rooms.columns if 'prof' in col.lower() or 'instructor' in col.lower() or 'faculty' in col.lower()]
            
            if room_cols:
                room_col_name = room_cols[0] 
                room_list = ["All Rooms"] + sorted(df_raw_rooms[room_col_name].dropna().unique().tolist())
                selected_room = st.selectbox(f"🏫 Check Occupancy for {room_col_name}:", room_list)
                
                if selected_room != "All Rooms":
                    df_room_filtered = df_raw_rooms[df_raw_rooms[room_col_name] == selected_room]
                else:
                    df_room_filtered = df_raw_rooms
            else:
                df_room_filtered = df_raw_rooms
                
            # --- ROOM VISUAL TIMETABLE ---
            st.markdown("### 🗓️ Visual Room Occupancy")
            
            days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
            time_bins = list(range(420, 1290, 30))
            time_labels = [format_minutes(t) for t in time_bins]
            grid_df_rooms = pd.DataFrame("", index=time_labels, columns=days_of_week)
            
            for _, row in df_room_filtered.iterrows():
                day = row.get('day')
                if day not in days_of_week: continue
                
                try:
                    start = int(row['time_start'])
                    end = int(row['time_end'])
                    course = str(row.get('course_id', ''))
                    room = str(row.get('room', ''))
                    prof = str(row.get(prof_cols[0], '')) if prof_cols else ''
                    
                    cell_text = f"{course} | {prof}" if selected_room != "All Rooms" else f"{course} | {room}"
                    
                    for t, t_label in zip(time_bins, time_labels):
                        if start <= t < end:
                            if grid_df_rooms.at[t_label, day] == "":
                                grid_df_rooms.at[t_label, day] = cell_text
                            else:
                                grid_df_rooms.at[t_label, day] += f" 🛑 {cell_text}" 
                except:
                    pass
                    
            def style_timetable(val):
                if val != "":
                    return 'background-color: #880000; color: #FFFFFF; font-weight: 700; border: 1px solid #FFD700; text-align: center;'
                return 'background-color: #FFFFFF; color: #333333; border: 1px solid #E0E0E0;'

            try:
                styled_room_grid = grid_df_rooms.style.map(style_timetable)
            except AttributeError:
                styled_room_grid = grid_df_rooms.style.applymap(style_timetable)
                
            st.dataframe(styled_room_grid, use_container_width=True, height=500)
            
            # --- ROOM RAW DATA LOG ---
            st.markdown("### 📋 Room Assignment Details")
            df_room_table = df_room_filtered.copy()
            if 'time_start' in df_room_table.columns: df_room_table['time_start'] = df_room_table['time_start'].apply(format_minutes)
            if 'time_end' in df_room_table.columns: df_room_table['time_end'] = df_room_table['time_end'].apply(format_minutes)
            st.dataframe(df_room_table, use_container_width=True, height=250) 
            
        except Exception as e:
            st.warning("Room data not available. Please generate the schedule first.")
    else:
        st.info("Generate a schedule to view room allocations.")

# ------------------------------------------
# VIEW 3: MANUAL ADJUSTMENTS
# ------------------------------------------
elif st.session_state.active_tab == "Manual Adjustments":
    st.subheader("System Health & Manual Overrides")
    
    if st.session_state.schedule_generated and uploaded_file is not None:
        
        # --- ALGORITHM STATUS SUMMARY METRICS ---
        try:
            df_summary = pd.read_excel("masterSchedule.xlsx", sheet_name="Summary")
            st.markdown("### 📊 Algorithm Status Report")
            
            if not df_summary.empty:
                metric_cols = st.columns(len(df_summary.columns))
                for i, col in enumerate(df_summary.columns):
                    metric_cols[i].metric(label=col.replace("_", " ").title(), value=str(df_summary.iloc[0][col]))
            st.divider()
        except:
            st.info("No Summary sheet found in the generated output.")

        # --- INTERACTIVE MANUAL EDITOR ---
        try:
            st.markdown("### ✏️ Interactive Override Editor")
            st.write("Double-click any cell below to manually fix soft constraints or override assignments.")
            
            df_edit = pd.read_excel("masterSchedule.xlsx", sheet_name="All_Assignments") 
            
            if 'room' in df_edit.columns: df_edit['room'] = df_edit['room'].apply(format_room_name)
            if 'time_start' in df_edit.columns: df_edit['time_start'] = df_edit['time_start'].apply(format_minutes)
            if 'time_end' in df_edit.columns: df_edit['time_end'] = df_edit['time_end'].apply(format_minutes)
            
            # Render interactive dataframe where cells can be modified by the admin
            edited_df = st.data_editor(df_edit, use_container_width=True, height=400, num_rows="dynamic")
            
            # Save logic for exporting overrides
            if st.button("💾 Save Manual Overrides", use_container_width=True):
                try:
                    with pd.ExcelWriter("masterSchedule_Overridden.xlsx") as writer:
                        edited_df.to_excel(writer, sheet_name="All_Assignments", index=False)
                    st.success("✅ Overrides successfully saved to `masterSchedule_Overridden.xlsx`!")
                except Exception as e:
                    st.error(f"Failed to save overrides: {e}")
                    
        except Exception as e:
            st.warning("Override data not available.")
            
    else:
        st.info("Generate a schedule to view system health and access manual overrides.")
