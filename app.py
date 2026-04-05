import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, date, time, timedelta
import json
import os
from dateutil import parser as dateparser
from openai import OpenAI
import base64

DB_PATH = "sessions.db"

# ---------- DB helpers ----------

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_iso TEXT,
            start_time_24h TEXT,
            session_datetime TEXT,
            duration_min INTEGER,
            topic TEXT,
            institution TEXT,
            organizer_name TEXT,
            contact_whatsapp TEXT,
            mode TEXT,
            platform_or_venue TEXT,
            meeting_link TEXT,
            notes TEXT,
            ppt_status TEXT,
            reminder1_at TEXT,
            reminder2_at TEXT,
            reminder1_sent INTEGER,
            reminder2_sent INTEGER
        )
        """
    )
    conn.commit()
    conn.close()

def insert_session(data):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO sessions (
            date_iso, start_time_24h, session_datetime,
            duration_min, topic, institution, organizer_name,
            contact_whatsapp, mode, platform_or_venue,
            meeting_link, notes, ppt_status,
            reminder1_at, reminder2_at,
            reminder1_sent, reminder2_sent
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["date_iso"],
            data["start_time_24h"],
            data["session_datetime"],
            data["duration_min"],
            data["topic"],
            data["institution"],
            data["organizer_name"],
            data["contact_whatsapp"],
            data["mode"],
            data["platform_or_venue"],
            data["meeting_link"],
            data["notes"],
            data["ppt_status"],
            data["reminder1_at"],
            data["reminder2_at"],
            0,
            0,
        ),
    )
    conn.commit()
    conn.close()

def load_sessions():
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM sessions", conn)
    conn.close()
    return df

# ---------- AI helpers ----------

def get_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        st.error("OPENAI_API_KEY not set. Please configure it in Streamlit secrets.")
        return None
    return OpenAI(api_key=api_key)

BASE_SYSTEM_PROMPT = """
You are an assistant that extracts session (talk/lecture/workshop) details from invites.

Return ONLY valid JSON with this exact structure:

{
  "date_iso": "YYYY-MM-DD",
  "start_time_24h": "HH:MM",
  "duration_min": 60,
  "topic": "",
  "institution": "",
  "organizer_name": "",
  "contact_whatsapp": "",
  "mode": "Online" or "Offline",
  "platform_or_venue": "",
  "meeting_link": "",
  "notes": ""
}

Rules:
- If unsure about any field, DO NOT GUESS. Use empty string "" or null.
- Use today's date (given) to resolve relative dates like "tomorrow", "next Friday", "this Saturday".
- Use 24-hour time for start_time_24h.
- "mode" MUST be exactly "Online" or "Offline".
- meeting_link should include Zoom/Meet/Teams/Webex link if present, else empty string.
"""

def call_ai_parser_from_text(raw_text: str):
    client = get_client()
    if not client:
        return None

    today_str = date.today().isoformat()

    user_prompt = f"""
Today's date is: {today_str}

Extract one session from this text:

\"\"\"{raw_text}\"\"\"
"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": BASE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        if not data.get("date_iso") or not data.get("start_time_24h"):
            st.warning("AI could not detect date or time properly. Please fill those fields manually below.")
        return data
    except Exception as e:
        st.error(f"Error calling AI parser (text): {e}")
        return None

def image_bytes_to_b64(img_bytes: bytes) -> str:
    return base64.b64encode(img_bytes).decode("utf-8")

def call_ai_parser_from_image(file):
    client = get_client()
    if not client:
        return None

    try:
        img_bytes = file.read()
        b64 = image_bytes_to_b64(img_bytes)
        today_str = date.today().isoformat()

        user_prompt = f"""
Today's date is: {today_str}

You are given an invite poster or schedule as an image.
Read all the visible text and extract ONE session using the JSON schema.
If there are multiple sessions, pick the one that is most clearly a talk I am giving.
"""

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": BASE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                    ],
                },
            ],
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        if not data.get("date_iso") or not data.get("start_time_24h"):
            st.warning("AI (image) could not detect date or time properly. Please fill those fields manually below.")
        return data
    except Exception as e:
        st.error(f"Error calling AI parser (image): {e}")
        return None

# ---------- Streamlit UI ----------

st.set_page_config(page_title="Session Diary", layout="wide")
st.title("Session Diary – AI Assisted")

st.markdown(
    """
    *Designed and used by* **Prof. Mohit Tiwari**  
    Assistant Professor | Cybersecurity & AI Research | BVCOE Delhi  

    [Google Scholar](https://scholar.google.com/citations?user=ZFRPBBcAAAAJ&hl=en&authuser=2) · 
    [ORCID](https://orcid.org/0000-0003-1836-3451) · 
    [LinkedIn](https://linkedin.com/in/mtiw)
    """
)
st.markdown("---")

init_db()
df_sessions = load_sessions()

st.markdown("Paste WhatsApp invite **or** upload poster → AI parses → you confirm → saved.")

# ---------- Today / Tomorrow strip ----------

st.subheader("🔥 Today / Tomorrow")

if not df_sessions.empty:
    df_tmp = df_sessions.copy()
    df_tmp["session_datetime"] = pd.to_datetime(df_tmp["session_datetime"])
    now = datetime.now()
    tomorrow = now + timedelta(days=1)

    df_tmp = df_tmp[
        (df_tmp["session_datetime"] >= now) &
        (df_tmp["session_datetime"] <= tomorrow)
    ].sort_values("session_datetime")

    if not df_tmp.empty:
        st.dataframe(
            df_tmp[["session_datetime", "topic", "institution", "ppt_status"]],
            use_container_width=True,
        )
    else:
        st.info("No sessions today or tomorrow.")
else:
    st.info("No sessions logged yet.")

st.markdown("---")

# ---------- Upcoming in next 3 days ----------

st.subheader("⚠️ Upcoming Sessions (Next 3 Days)")

if not df_sessions.empty:
    df_up = df_sessions.copy()
    df_up["session_datetime"] = pd.to_datetime(df_up["session_datetime"])
    now = datetime.now()
    three_days = now + timedelta(days=3)
    mask = (df_up["session_datetime"] >= now) & (df_up["session_datetime"] <= three_days)
    df_up = df_up[mask].sort_values("session_datetime")

    if df_up.empty:
        st.info("No sessions in the next 3 days.")
    else:
        df_show = df_up[
            [
                "session_datetime",
                "topic",
                "institution",
                "ppt_status",
                "meeting_link",
                "notes",
            ]
        ].copy()

        df_show["⚠️ PPT Pending"] = df_show["ppt_status"].apply(
            lambda x: "YES" if x != "Ready" else ""
        )

        df_show.rename(
            columns={
                "session_datetime": "Date & Time",
                "meeting_link": "Link",
            },
            inplace=True,
        )

        def highlight_row(row):
            color = "background-color: #ffe5e5" if row["⚠️ PPT Pending"] == "YES" else ""
            return [color] * len(row)

        st.dataframe(
            df_show.style.apply(highlight_row, axis=1),
            use_container_width=True,
        )
else:
    st.info("No sessions logged yet.")

st.markdown("---")

# ---------- Invite input: text OR image ----------

st.subheader("Invite Input")

tab_text, tab_image = st.tabs(["Paste text", "Upload image"])

if "parsed_data" not in st.session_state:
    st.session_state["parsed_data"] = None

with tab_text:
    raw_text = st.text_area("Paste the full invite text here", height=180)
    col_parse, col_reset = st.columns([1, 1])

    with col_parse:
        if st.button("AI Parse from Text") and raw_text.strip():
            data = call_ai_parser_from_text(raw_text.strip())
            if data:
                st.session_state["parsed_data"] = data
                st.success("Parsed from text. Check and confirm below.")
    with col_reset:
        if st.button("Clear parsed data (text)"):
            st.session_state["parsed_data"] = None

with tab_image:
    uploaded = st.file_uploader(
        "Upload invite poster/schedule (PNG/JPG)", type=["png", "jpg", "jpeg"]
    )
    col_parse_img, col_reset_img = st.columns([1, 1])

    with col_parse_img:
        if st.button("AI Parse from Image") and uploaded is not None:
            data = call_ai_parser_from_image(uploaded)
            if data:
                st.session_state["parsed_data"] = data
                st.success("Parsed from image. Check and confirm below.")
    with col_reset_img:
        if st.button("Clear parsed data (image)"):
            st.session_state["parsed_data"] = None

parsed = st.session_state.get("parsed_data") or {}

if parsed and (not parsed.get("date_iso") or not parsed.get("start_time_24h")):
    st.warning(
        "AI could not detect date or time properly. Please fill those fields manually below."
    )

# ---------- Form to confirm/save ----------

st.subheader("Confirm Session Details")

def_str_date = parsed.get("date_iso") or date.today().isoformat()
try:
    def_date = datetime.fromisoformat(def_str_date).date()
except Exception:
    def_date = date.today()

def_str_time = parsed.get("start_time_24h") or "11:00"
try:
    def_time = datetime.strptime(def_str_time, "%H:%M").time()
except Exception:
    def_time = time(11, 0)

def_duration = parsed.get("duration_min") or 60

with st.form("session_form"):
    c1, c2, c3 = st.columns(3)
    with c1:
        s_date = st.date_input("Date", value=def_date)
    with c2:
        s_time = st.time_input("Start time", value=def_time)
    with c3:
        duration_min = st.number_input(
            "Duration (minutes)",
            min_value=10,
            max_value=600,
            value=int(def_duration),
            step=5,
        )

    topic = st.text_input("Topic / Title", value=parsed.get("topic") or "")
    c4, c5 = st.columns(2)
    with c4:
        organizer_name = st.text_input(
            "Organizer name", value=parsed.get("organizer_name") or ""
        )
        institution = st.text_input(
            "Institution", value=parsed.get("institution") or ""
        )
    with c5:
        contact_whatsapp = st.text_input(
            "WhatsApp / Phone", value=parsed.get("contact_whatsapp") or ""
        )
        mode = st.selectbox(
            "Mode",
            ["Online", "Offline"],
            index=0 if (parsed.get("mode") or "Online") == "Online" else 1,
        )
        platform_or_venue = st.text_input(
            "Platform / Venue", value=parsed.get("platform_or_venue") or ""
        )

    meeting_link = st.text_input(
        "Meeting link", value=parsed.get("meeting_link") or ""
    )
    ppt_status = st.selectbox(
        "PPT status", ["Not Started", "In Progress", "Ready"], index=0
    )
    notes = st.text_area("Notes", height=60, value=parsed.get("notes") or "")

    submitted = st.form_submit_button("Save session")

    if submitted:
        s_datetime = datetime.combine(s_date, s_time)
        reminder1_at = s_datetime - timedelta(days=2)
        reminder2_at = s_datetime - timedelta(hours=1)

        row = {
            "date_iso": s_date.isoformat(),
            "start_time_24h": s_time.strftime("%H:%M"),
            "session_datetime": s_datetime.isoformat(),
            "duration_min": int(duration_min),
            "topic": topic,
            "institution": institution,
            "organizer_name": organizer_name,
            "contact_whatsapp": contact_whatsapp,
            "mode": mode,
            "platform_or_venue": platform_or_venue,
            "meeting_link": meeting_link,
            "notes": notes,
            "ppt_status": ppt_status,
            "reminder1_at": reminder1_at.isoformat(),
            "reminder2_at": reminder2_at.isoformat(),
        }
        insert_session(row)
        st.success("Session saved.")
        st.session_state["parsed_data"] = None

st.markdown("---")

# ---------- All Sessions ----------

st.subheader("All Sessions")

df_sessions = load_sessions()
if not df_sessions.empty:
    df_all = df_sessions.copy()
    df_all["session_datetime"] = pd.to_datetime(df_all["session_datetime"])
    df_all = df_all.sort_values("session_datetime", ascending=True)

    colf1, colf2 = st.columns(2)
    with colf1:
        show_future_only = st.checkbox("Show only future sessions", value=True)
    with colf2:
        ppt_filter = st.multiselect(
            "Filter by PPT status",
            options=["Not Started", "In Progress", "Ready"],
        )

    if show_future_only:
        df_all = df_all[df_all["session_datetime"] >= datetime.now()]

    if ppt_filter:
        df_all = df_all[df_all["ppt_status"].isin(ppt_filter)]

    st.dataframe(df_all, use_container_width=True)
else:
    st.info("No sessions logged yet.")
