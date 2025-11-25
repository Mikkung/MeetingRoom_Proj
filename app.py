###############################################
#             IMPORTS & INITIAL SETUP         #
###############################################

import streamlit as st
import datetime
import pandas as pd
import json
import io
import os

# ต้องติดตั้ง: pip install firebase-admin bcrypt streamlit-cookies-manager

# bcrypt (สำหรับ hashing password)
try:
    import bcrypt
    bcrypt_installed = True
except ImportError:
    bcrypt_installed = False
    st.warning("⚠️ Missing bcrypt — running in Mock Mode", icon="🚨")

# Firebase Admin SDK
try:
    from firebase_admin import credentials, firestore, initialize_app, get_app
    firebase_installed = True
except ImportError:
    firebase_installed = False
    st.error("❌ Missing firebase-admin library", icon="🚨")

# 🔐 Cookie Manager
from streamlit_cookies_manager import EncryptedCookieManager

# Load cookie encryption password
try:
    cookie_password = st.secrets["COOKIE_PASSWORD"]
except Exception:
    cookie_password = "CHANGE_THIS_COOKIE_PASSWORD"  # fallback (dev only)

cookies = EncryptedCookieManager(
    prefix="ise_meeting_",
    password=cookie_password
)

# ต้องรอ cookies.ready() มิฉะนั้น Streamlit จะ error
if not cookies.ready():
    st.stop()


###############################################
#      DEFAULT CONFIG / MOCK USER / ROOMS     #
###############################################

MOCK_USER_FALLBACK = {
    "admin.user": {
        "email": "admin@ise.com",
        "hashed_password": "$2b$12$FAKEHASH-DO-NOT-USE-IN-PROD",
        "role": "admin"
    }
}

ROOMS = {
    "ISE_Meeting_Room_I_305_Fl1": {"capacity": 8, "has_projector": True},
    "ISE_Meeting_Room_II_Fl2": {"capacity": 20, "has_projector": True},
    "ISE_Meeting_Room_III_304/1_Fl1": {"capacity": 20, "has_projector": True}
}


###############################################
#         FIREBASE INITIAL CONNECTION         #
###############################################

def init_database_connection():
    if 'db_ready' in st.session_state:
        return

    if not firebase_installed:
        st.session_state.db_ready = False
        return

    try:
        try:
            get_app()
        except Exception:
            key_dict = json.loads(st.secrets["firestore_credentials"])
            cred = credentials.Certificate(key_dict)
            initialize_app(cred)

        st.session_state.db = firestore.client()
        st.session_state.db_ready = True
        st.sidebar.success("🌐 Firestore Connected")

    except Exception as e:
        st.session_state.db_ready = False
        st.sidebar.error(f"❌ Firestore Error: {e}")


###############################################
#          SESSION INITIALIZATION             #
###############################################

def initialize_state():
    init_database_connection()

    if "rooms" not in st.session_state:
        st.session_state.rooms = ROOMS

    # ⭐ Auto-login using cookies
    if "authenticated_user" not in st.session_state:
        saved_user = cookies.get("auth_user")
        saved_role = cookies.get("auth_role")
        st.session_state.authenticated_user = saved_user if saved_user else None
        st.session_state.user_role = saved_role if saved_role else None

    if "mode" not in st.session_state:
        st.session_state.mode = "login"


###############################################
#                DATABASE OPS                 #
###############################################

@st.cache_data(ttl=3600)
def load_users_from_db():
    if not st.session_state.db_ready:
        return MOCK_USER_FALLBACK

    try:
        users = {}
        docs = st.session_state.db.collection("users").stream()
        for doc in docs:
            users[doc.id] = doc.to_dict()
        return users if users else MOCK_USER_FALLBACK

    except Exception:
        return MOCK_USER_FALLBACK


@st.cache_data(ttl=5)
def load_bookings_from_db():
    if not st.session_state.db_ready:
        return []

    try:
        docs = st.session_state.db.collection("bookings").stream()
        bookings = []
        for doc in docs:
            d = doc.to_dict()
            d["doc_id"] = doc.id
            bookings.append(d)
        return bookings
    except Exception:
        return []


def save_new_user_to_db(username, email, hashed_password):
    if not st.session_state.db_ready:
        return False

    try:
        st.session_state.db.collection("users").document(username).set({
            "email": email,
            "hashed_password": hashed_password,
            "role": "user"
        })
        load_users_from_db.clear()
        return True
    except:
        return False


def save_booking_to_db(new_booking):
    if not st.session_state.db_ready:
        return False

    try:
        payload = {k: v for k, v in new_booking.items() if not k.endswith("_obj")}
        st.session_state.db.collection("bookings").add(payload)
        load_bookings_from_db.clear()
        return True
    except:
        return False


def delete_booking_from_db(doc_id):
    if not st.session_state.db_ready:
        return False

    try:
        st.session_state.db.collection("bookings").document(doc_id).delete()
        load_bookings_from_db.clear()
        return True
    except:
        return False


###############################################
#             BUSINESS LOGIC                  #
###############################################

def is_conflict(new, existing):
    room = new["room"]
    date = new["date_obj"]

    ns = new["start_time_obj"]
    ne = new["end_time_obj"]

    ns_sec = ns.hour * 3600 + ns.minute * 60
    ne_sec = ne.hour * 3600 + ne.minute * 60

    for b in existing:
        try:
            bd = datetime.date.fromisoformat(b["date"])
            if bd != date or b["room"] != room:
                continue

            s = datetime.time.fromisoformat(b["start_time"])
            e = datetime.time.fromisoformat(b["end_time"])

            s_sec = s.hour * 3600 + s.minute * 60
            e_sec = e.hour * 3600 + e.minute * 60

            if not (ne_sec <= s_sec or ns_sec >= e_sec):
                return True
        except:
            continue

    return False


def handle_signup(username, email, pw, pw2):
    users = load_users_from_db()

    if username in users:
        st.toast("⛔ Username already exists")
        return

    if pw != pw2:
        st.toast("❌ Password mismatch")
        return

    if bcrypt_installed:
        hashed = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    else:
        hashed = "MOCK_HASH_FOR_" + username

    if save_new_user_to_db(username, email, hashed):
        st.toast("🎉 Sign up success!")
        st.session_state.mode = "login"
        st.rerun()
    else:
        st.toast("❌ Could not save user")


def handle_logout():
    st.session_state.authenticated_user = None
    st.session_state.user_role = None

    cookies["auth_user"] = ""
    cookies["auth_role"] = ""
    cookies.save()

    st.session_state.mode = "login"
    st.rerun()


###############################################
#                 UI COMPONENTS               #
###############################################

def display_profile_card():
    user = st.session_state.authenticated_user
    users = load_users_from_db()
    info = users.get(user, {})

    st.sidebar.markdown("---")
    st.sidebar.write(f"👤 **{user}**")
    st.sidebar.write(f"📧 {info.get('email')}")
    st.sidebar.write(f"🏷️ Role: {info.get('role')}")

    st.sidebar.button("Logout", on_click=handle_logout)


def display_login_form():
    st.sidebar.subheader("🔓 Login")

    users = load_users_from_db()

    with st.sidebar.form("login_form"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        ok = st.form_submit_button("Login")

    if ok:
        if u not in users:
            st.toast("❌ User not found")
            return

        stored = users[u]["hashed_password"]

        correct = False
        if bcrypt_installed and stored.startswith("$2b$"):
            correct = bcrypt.checkpw(p.encode(), stored.encode())
        else:
            correct = (stored == "MOCK_HASH_FOR_" + u)

        if correct:
            st.session_state.authenticated_user = u
            st.session_state.user_role = users[u]["role"]

            cookies["auth_user"] = u
            cookies["auth_role"] = users[u]["role"]
            cookies.save()

            st.rerun()
        else:
            st.toast("❌ Wrong password")

    if st.sidebar.button("Sign Up"):
        st.session_state.mode = "signup"
        st.rerun()


def display_signup_form():
    st.sidebar.subheader("📝 Sign Up")

    with st.sidebar.form("signup_form"):
        u = st.text_input("Username")
        e = st.text_input("Email")
        p1 = st.text_input("Password", type="password")
        p2 = st.text_input("Confirm Password", type="password")
        ok = st.form_submit_button("Create Account")

    if ok:
        handle_signup(u, e, p1, p2)

    if st.sidebar.button("Back to Login"):
        st.session_state.mode = "login"
        st.rerun()


###############################################
#      DISPLAY BOOKING + AVAILABILITY UI      #
###############################################

def display_booking_form():
    st.subheader("📝 New Booking")

    user = st.session_state.authenticated_user
    email = load_users_from_db()[user]["email"]

    with st.form("booking_form", clear_on_submit=True):
        room = st.selectbox("Room", list(ROOMS.keys()))
        date = st.date_input("Date", datetime.date.today())
        start = st.time_input("Start", datetime.time(9, 0))
        end = st.time_input("End", datetime.time(10, 0))

        ok = st.form_submit_button("Book")

    if ok:
        if start >= end:
            st.toast("❌ Start must be before end")
            return

        existing = load_bookings_from_db()

        new = {
            "room": room,
            "date": date.isoformat(),
            "start_time": start.isoformat(timespec="minutes"),
            "end_time": end.isoformat(timespec="minutes"),
            "user_id": user,
            "user_email": email,
            "date_obj": date,
            "start_time_obj": start,
            "end_time_obj": end
        }

        if is_conflict(new, existing):
            st.toast("❌ Time conflict!")
            return

        if save_booking_to_db(new):
            st.toast("✅ Booking successful!")


def display_availability_matrix():
    st.subheader("📅 Room Availability Today")

    view_date = st.date_input("Select Date", datetime.date.today())
    bookings = load_bookings_from_db()

    time_slots = []
    for h in range(8, 17):
        time_slots.append(f"{h:02d}:00")
        time_slots.append(f"{h:02d}:30")

    df = pd.DataFrame("🟢", index=time_slots, columns=list(ROOMS.keys()))

    for b in bookings:
        if b["date"] != view_date.isoformat():
            continue

        room = b["room"]
        s = datetime.time.fromisoformat(b["start_time"])
        e = datetime.time.fromisoformat(b["end_time"])

        for t in time_slots:
            slot = datetime.datetime.strptime(t, "%H:%M").time()
            slot_end = (datetime.datetime.combine(view_date, slot) +
                        datetime.timedelta(minutes=30)).time()

            if not (slot_end <= s or slot >= e):
                df.loc[t, room] = "🔴"

    st.dataframe(df)


def display_data_and_export():
    st.subheader("📋 All Bookings")

    bookings = load_bookings_from_db()
    if not bookings:
        st.info("No bookings yet")
        return

    df = pd.DataFrame(bookings)
    df_show = df[["room", "date", "start_time", "end_time", "user_id"]]
    st.dataframe(df_show, hide_index=True)

    # Export (admin only)
    if st.session_state.user_role == "admin":
        csv = df.to_csv(index=False).encode()
        st.download_button("Download CSV", csv, "bookings.csv")


###############################################
#                  MAIN APP                   #
###############################################

def main():
    st.set_page_config(page_title="ISE Meeting Room", layout="wide")

    st.title("🏢 ISE Meeting Room Scheduler")

    initialize_state()

    # Sidebar auth logic
    if st.session_state.authenticated_user:
        display_profile_card()
    else:
        if st.session_state.mode == "login":
            display_login_form()
        else:
            display_signup_form()

    if not st.session_state.db_ready:
        st.error("❌ Firestore not connected")
        return

    # Main UI
    display_availability_matrix()
    st.markdown("---")

    c1, c2 = st.columns([1, 2])
    with c1:
        if st.session_state.authenticated_user:
            display_booking_form()
        else:
            st.info("Please login to book")

    with c2:
        display_data_and_export()


if __name__ == "__main__":
    main()
