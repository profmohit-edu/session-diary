import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, date, time, timedelta
import json
import os
from dateutil import parser as dateparser
from openai import OpenAI

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
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM sessions", conn)
    conn.close()
    return df

# ---------- AI parsing ----------

def call_ai_parser(raw_text: str):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        st.error("OPENAI_API_KEY not set. Please configure it in Streamlit secrets.")
        return None

    client = OpenAI(api_key=api_key)

    today_str = date.today().isoformat()

    system_prompt = """
You are an assistant that extracts session (talk/lecture/workshop) details from WhatsApp-style text.

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

    user_prompt = f"""
Today's date is: {today_str}

Extract one session from this text:

\"\"\"{raw_text}\"\"\"
"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        try:
            data = json.loads(content)
        except Exception:
            st.error("AI returned invalid JSON. Please click 'AI Parse & Prefill' again or fill manually.")
            return None
        # Basic sanity check
        if not data.get("date_iso") or not data.get("start_time_24h"):
            st.warning("AI could not detect date or time properly. Please fill those fields manually below.")
        return data
    except Exception as e:
        st.error(f"Error calling AI parser: {e}")
        return None

# ---------- Streamlit UI ----------

st.set_page_config(page_title="Session Diary", layout="wide")
st.title("Session Diary – AI Assisted")

init_db()

st.markdown("Paste WhatsApp invite → AI parses → you confirm → saved.")

# Load existing sessions
df_sessions = load_sessions() if os.path.exists(DB_PATH) else pd.DataFrame()

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
            use_container_width=True
        )
    else:
        st.info("No sessions today or tomorrow.")
else:
    st.info("No sessions logged yet.")

st.markdown("---")

