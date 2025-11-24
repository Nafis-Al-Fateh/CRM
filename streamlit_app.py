pip install streamlit supabase-py python-dotenv pandas

# app.py
import streamlit as st
import streamlit.components.v1 as components
from supabase import create_client
import os
from datetime import datetime, timezone
import pandas as pd
import uuid

# --- CONFIG ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Set SUPABASE_URL and SUPABASE_KEY environment variables.")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Helpers ---
def get_current_user():
    user = supabase.auth.get_user()
    return user.data.user if user and user.data else None

def ensure_crm_user(auth_user):
    # try find crm_users row, else create
    if not auth_user:
        return None
    res = supabase.table("crm_users").select("*").eq("auth_id", auth_user.id).execute()
    if res.data and len(res.data) > 0:
        return res.data[0]
    # create default agent
    new = {
        "auth_id": auth_user.id,
        "full_name": auth_user.email.split("@")[0],
        "role": "agent"
    }
    r = supabase.table("crm_users").insert(new).execute()
    return r.data[0]

def insert_attendance_clock_in(user_id):
    now = datetime.now(timezone.utc).isoformat()
    r = supabase.table("attendance").insert({
        "user_id": user_id,
        "clock_in": now
    }).execute()
    return r

def update_attendance_clock_out(att_id):
    now = datetime.now(timezone.utc).isoformat()
    # fetch clock_in
    a = supabase.table("attendance").select("clock_in").eq("id", att_id).single().execute()
    if not a.data:
        return None
    clock_in = datetime.fromisoformat(a.data["clock_in"])
    clock_out = datetime.now(timezone.utc)
    diff = int((clock_out - clock_in).total_seconds() / 60)  # minutes
    r = supabase.table("attendance").update({
        "clock_out": clock_out.isoformat(),
        "work_minutes": diff
    }).eq("id", att_id).execute()
    return r

def insert_break_start(user_id, attendance_id=None):
    now = datetime.now(timezone.utc).isoformat()
    r = supabase.table("breaks").insert({
        "user_id": user_id,
        "break_start": now,
        "attendance_id": attendance_id
    }).execute()
    return r

def update_break_end(break_id):
    now = datetime.now(timezone.utc)
    b = supabase.table("breaks").select("break_start").eq("id", break_id).single().execute()
    if not b.data:
        return None
    start = datetime.fromisoformat(b.data["break_start"])
    minutes = int((now - start).total_seconds() / 60)
    r = supabase.table("breaks").update({
        "break_end": now.isoformat(),
        "break_minutes": minutes
    }).eq("id", break_id).execute()
    return r

def start_call_record(user_id, task_type, notes, jitsi_room):
    now = datetime.now(timezone.utc).isoformat()
    r = supabase.table("calls").insert({
        "user_id": user_id,
        "call_start": now,
        "task_type": task_type,
        "notes": notes,
        "jitsi_room": jitsi_room
    }).execute()
    return r

def end_call_record(call_id):
    now = datetime.now(timezone.utc)
    c = supabase.table("calls").select("call_start").eq("id", call_id).single().execute()
    if not c.data:
        return None
    start = datetime.fromisoformat(c.data["call_start"])
    duration = int((now - start).total_seconds())
    r = supabase.table("calls").update({
        "call_end": now.isoformat(),
        "duration_seconds": duration
    }).eq("id", call_id).execute()
    return r

# --- UI ---
st.set_page_config(page_title="Streamlit CRM with Time Tracking", layout="wide")
st.title("CRM — Time Tracking & Calls")

# Authentication UI (basic)
if "auth_user" not in st.session_state:
    st.session_state.auth_user = None

auth_section = st.sidebar.expander("Login / Signup")
with auth_section:
    mode = st.radio("Mode", ["Login", "Signup"])
    email = st.text_input("Email", value="", key="email")
    password = st.text_input("Password", type="password", key="pw")
    if st.button("Submit"):
        if mode == "Signup":
            resp = supabase.auth.sign_up({"email": email, "password": password})
            st.success("Signed up. Please check your email for confirmation (if enabled). Then log in.")
        else:
            resp = supabase.auth.sign_in_with_password({"email": email, "password": password})
            if resp and resp.data:
                st.success("Logged in")
                st.session_state.auth_user = resp.data.user
            else:
                st.error("Login failed")

# require login
if not st.session_state.get("auth_user"):
    st.info("Please login on the left to proceed.")
    st.stop()

auth_user = st.session_state.auth_user
crm_user = ensure_crm_user(auth_user)
st.sidebar.markdown(f"**User:** {crm_user['full_name']} ({crm_user['role']})")

# Employee actions
col1, col2 = st.columns(2)
with col1:
    st.header("Attendance")
    # Check if there's an open attendance (clock_in without clock_out)
    open_att = supabase.table("attendance").select("*").eq("user_id", crm_user["id"]).is_("clock_out", None).order("clock_in", desc=True).limit(1).execute()
    open_att = open_att.data[0] if open_att.data else None

    if open_att is None:
        if st.button("Clock In"):
            res = insert_attendance_clock_in(crm_user["id"])
            st.success("Clocked in.")
    else:
        st.write("Clocked in at:", open_att["clock_in"])
        if st.button("Clock Out"):
            update_attendance_clock_out(open_att["id"])
            st.success("Clocked out.")

with col2:
    st.header("Breaks")
    # check open break
    open_break = supabase.table("breaks").select("*").eq("user_id", crm_user["id"]).is_("break_end", None).order("break_start", desc=True).limit(1).execute()
    open_break = open_break.data[0] if open_break.data else None

    if open_break is None:
        if st.button("Start Break"):
            # associate with current attendance if exists
            attendance_for_break = open_att["id"] if open_att else None
            insert_break_start(crm_user["id"], attendance_for_break)
            st.success("Break started.")
    else:
        st.write("Break started at:", open_break["break_start"])
        if st.button("End Break"):
            update_break_end(open_break["id"])
            st.success("Break ended.")

st.markdown("---")
# CALLS SECTION using Jitsi (free browser-to-browser)
st.header("Calling (Free via Jitsi Meet)")
call_col1, call_col2 = st.columns([2,1])
with call_col1:
    task_type = st.selectbox("Task Type", ["Follow-up", "Lead Call", "Survey", "Support", "Other"])
    notes = st.text_area("Notes for call (optional)", "")
    start_call_btn = st.button("Start Call (Open Jitsi Room)")
    end_call_btn = st.button("End Call (Stop & Log)")
with call_col2:
    st.write("Call Controls")
    # manage current call id in session
    if "current_call_id" not in st.session_state:
        st.session_state.current_call_id = None
    if "current_jitsi_room" not in st.session_state:
        st.session_state.current_jitsi_room = None

    if start_call_btn and st.session_state.current_call_id is None:
        # generate unique jitsi room
        room = f"crm-{crm_user['id']}-{uuid.uuid4().hex[:8]}"
        inserted = start_call_record(crm_user["id"], task_type, notes, room)
        if inserted.data:
            call_id = inserted.data[0]["id"]
            st.session_state.current_call_id = call_id
            st.session_state.current_jitsi_room = room
            st.success("Call started and logged. Use the embedded room below.")
    if end_call_btn and st.session_state.current_call_id:
        end_call_record(st.session_state.current_call_id)
        st.success("Call ended and recorded.")
        st.session_state.current_call_id = None
        st.session_state.current_jitsi_room = None

# Embed Jitsi iframe when call started
if st.session_state.get("current_jitsi_room"):
    room = st.session_state.current_jitsi_room
    # minimal Jitsi embed HTML using External API
    jitsi_html = f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
      </head>
      <body>
        <div id="jitsi-container" style="height: 600px; width: 100%;"></div>
        <script src="https://meet.jit.si/external_api.js"></script>
        <script>
          const domain = "meet.jit.si";
          const options = {{
            roomName: "{room}",
            parentNode: document.querySelector('#jitsi-container'),
            interfaceConfigOverwrite: {{ TOOLBAR_BUTTONS: ['microphone','hangup','chat'] }},
            configOverwrite: {{ startWithVideoMuted: true }}
          }};
          const api = new JitsiMeetExternalAPI(domain, options);
        </script>
      </body>
    </html>
    """
    components.html(jitsi_html, height=640, scrolling=True)

st.markdown("---")
# ADMIN DASHBOARD
if crm_user["role"] == "admin":
    st.header("Admin Dashboard — End of Day Summary")
    d1, d2 = st.columns(2)
    with d1:
        date = st.date_input("Date", value=pd.Timestamp.now().date())
        user_filter = st.selectbox("Filter user (optional)", ["All"] + [u["full_name"] for u in supabase.table("crm_users").select("full_name,id").execute().data])
        if st.button("Load Summary"):
            # fetch attendance and breaks and calls for date
            date_str = pd.to_datetime(date).strftime("%Y-%m-%d")
            attendance = supabase.table("attendance").select("*").eq("clock_date", date_str).execute().data
            breaks = supabase.table("breaks").select("*").execute().data
            calls = supabase.table("calls").select("*").execute().data
            # build summary
            df_att = pd.DataFrame(attendance)
            df_break = pd.DataFrame(breaks)
            df_calls = pd.DataFrame(calls)
            if user_filter != "All":
                # map name->id
                users = supabase.table("crm_users").select("id,full_name").execute().data
                uid = [u["id"] for u in users if u["full_name"] == user_filter][0]
                df_att = df_att[df_att["user_id"]==uid]
                df_break = df_break[df_break["user_id"]==uid]
                df_calls = df_calls[df_calls["user_id"]==uid]
            st.subheader("Attendance")
            st.dataframe(df_att)
            st.subheader("Breaks")
            st.dataframe(df_break)
            st.subheader("Calls")
            st.dataframe(df_calls)
            # aggregate
            summary = df_att.groupby("user_id")["work_minutes"].sum().reset_index().rename(columns={"work_minutes":"total_work_minutes"})
            brsum = df_break.groupby("user_id")["break_minutes"].sum().reset_index().rename(columns={"break_minutes":"total_break_minutes"})
            callsum = df_calls.groupby("user_id")["duration_seconds"].sum().reset_index().rename(columns={"duration_seconds":"call_seconds"})
            agg = summary.merge(brsum, on="user_id", how="left").merge(callsum, on="user_id", how="left").fillna(0)
            # join names
            users = supabase.table("crm_users").select("id,full_name").execute().data
            users_df = pd.DataFrame(users)
            agg = agg.merge(users_df, left_on="user_id", right_on="id", how="left")
            st.subheader("Aggregated Summary")
            st.dataframe(agg[["full_name","total_work_minutes","total_break_minutes","call_seconds"]])
