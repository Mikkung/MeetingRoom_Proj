import streamlit as st
import datetime
import pandas as pd
import json
import io
import time # นำเข้าสำหรับ time.sleep (สำหรับ mock mode)
from typing import Dict, Any, Optional

# --- INITIALIZATION AND DB CONNECTION ---
# ต้องติดตั้ง: pip install firebase-admin bcrypt
try:
    import bcrypt
    bcrypt_installed = True
except ImportError:
    bcrypt_installed = False
    st.warning("⚠️ Cannot find 'bcrypt' library. Password check will use Mock Logic.", icon="🚨")

try:
    from firebase_admin import credentials, firestore, initialize_app, get_app
    from firebase_admin.exceptions import InvalidArgumentError
    firebase_installed = True
except ImportError:
    from firebase_admin import get_app
    firebase_installed = False
    st.error("❌ Cannot find 'firebase-admin' library. Please install to connect Firestore.", icon="🚨")


# --- CONFIGURATION & UTILITIES ---

MOCK_USER_FALLBACK: Dict[str, Dict[str, Any]] = {
    "admin.user": {
        "email": "admin@ise.com",
        "hashed_password": "$2b$12$FAKE.HASH.FOR.ADMIN.DO.NOT.USE.THIS.IN.PRODUCTION.3", 
        "role": "admin" 
    }
}

ROOMS = {
    "ISE_Meeting_Room_I_305_Fl1": {"capacity": 8, "has_projector": True},
    "ISE_Meeting_Room_II_Fl2": {"capacity": 20, "has_projector": True},
    "ISE_Meeting_Room_III_304/1_Fl1": {"capacity": 20, "has_projector": True}
}

def init_database_connection():
    """Connects to Firestore and prevents re-initialization."""
    if 'db_ready' not in st.session_state:
        if not firebase_installed:
            st.session_state.db_ready = False
            return
            
        try:
            try:
                get_app()
            except ValueError:
                key_dict = json.loads(st.secrets["firestore_credentials"])
                cred = credentials.Certificate(key_dict)
                initialize_app(cred)
            
            st.session_state.db = firestore.client()
            st.session_state.db_ready = True
            st.sidebar.success("✅ Firestore connected", icon="🌐")
            
        except Exception as e:
            st.session_state.db_ready = False
            st.sidebar.error(f"❌ Firestore connection error: {e}", icon="🚨")
            st.sidebar.error("💡 Check 'firestore_credentials' in Streamlit Secrets", icon="🛠️")


def initialize_state():
    """Initializes Streamlit Session State variables and DB connection."""
    init_database_connection()
    
    if 'rooms' not in st.session_state:
        st.session_state.rooms = ROOMS
    if 'authenticated_user' not in st.session_state:
        st.session_state.authenticated_user = None
    if 'user_role' not in st.session_state:
        st.session_state.user_role = None
    if 'mode' not in st.session_state:
        st.session_state.mode = 'login'


# --- DATABASE OPERATIONS ---

@st.cache_data(ttl=3600) # Cache User List for 1 hour
def load_users_from_db():
    """Loads all users from the 'users' Firestore Collection."""
    if not st.session_state.db_ready:
        return MOCK_USER_FALLBACK 

    try:
        users = {}
        docs = st.session_state.db.collection("users").stream()
        for doc in docs:
            user_data = doc.to_dict()
            users[doc.id] = user_data
        
        if not users:
            st.warning("⚠️ 'users' Collection is empty. Using Mock Admin data.", icon="⚠️")
            return MOCK_USER_FALLBACK
            
        return users
    except Exception as e:
        st.error(f"❌ Error loading user data from DB: {e}", icon="🚨")
        return MOCK_USER_FALLBACK 


@st.cache_data(ttl=5) 
def load_bookings_from_db():
    """Loads all bookings from Firestore (Near-Real-time)."""
    if not st.session_state.db_ready:
        return []

    try:
        docs = st.session_state.db.collection("bookings").stream()
        bookings = []
        for doc in docs:
            booking_data = doc.to_dict()
            booking_data['doc_id'] = doc.id
            bookings.append(booking_data)
            
        return bookings
    except Exception as e:
        st.error(f"❌ Error fetching bookings from DB: {e}", icon="🚨")
        return []


def save_booking_to_db(new_booking: Dict[str, Any]) -> bool:
    """Saves a new booking to Firestore."""
    if not st.session_state.db_ready:
        return False

    try:
        # Filter out temporary datetime objects before saving
        booking_to_save = {k: v for k, v in new_booking.items() if not k.endswith('_obj')}
        st.session_state.db.collection("bookings").add(booking_to_save)
        load_bookings_from_db.clear() 
        return True
    except Exception as e:
        st.error(f"❌ Error saving data to DB: {e}", icon="🚨")
        return False


def delete_booking_from_db(doc_id: str) -> bool:
    """Deletes a booking document from Firestore."""
    if not st.session_state.db_ready:
        return False
    
    # Extract actual doc_id from the button value
    actual_doc_id = doc_id.split("-", 1)[1] if doc_id.startswith("Cancel-") else doc_id
    
    try:
        st.session_state.db.collection("bookings").document(actual_doc_id).delete()
        load_bookings_from_db.clear()
        st.toast("🗑️ Booking cancelled", icon="🗑️")
        return True
    except Exception as e:
        st.error(f"❌ Error deleting booking: {e}", icon="🚨")
        return False


def save_new_user_to_db(username: str, email: str, hashed_password: str) -> bool:
    """Saves a new user to the 'users' Collection."""
    if not st.session_state.db_ready:
        return False
    
    try:
        user_data = {
            "email": email,
            "hashed_password": hashed_password,
            "role": "user"
        }
        st.session_state.db.collection("users").document(username).set(user_data)
        load_users_from_db.clear() 
        return True
    except Exception as e:
        st.error(f"❌ Error saving new user: {e}", icon="🚨")
        return False


# --- CORE LOGIC & CALLBACKS ---

def is_time_overlap(start1: datetime.time, end1: datetime.time, start2: datetime.time, end2: datetime.time) -> bool:
    """Checks for time range overlap."""
    def time_to_seconds(t: Optional[datetime.time]) -> int:
        return t.hour * 3600 + t.minute * 60 if t else -1
    
    s1, e1 = time_to_seconds(start1), time_to_seconds(end1)
    s2, e2 = time_to_seconds(start2), time_to_seconds(end2)
    
    return not (e1 <= s2 or s1 >= e2)

def is_conflict(new_booking: Dict[str, Any], current_bookings: list) -> bool:
    """Checks if a new booking conflicts with existing ones."""
    new_room = new_booking['room']
    new_date_obj: datetime.date = new_booking['date_obj']
    new_start_obj: datetime.time = new_booking['start_time_obj']
    new_end_obj: datetime.time = new_booking['end_time_obj']

    for booking in current_bookings:
        try:
            booking_date = datetime.date.fromisoformat(booking.get('date'))
            existing_start = datetime.time.fromisoformat(booking.get('start_time'))
            existing_end = datetime.time.fromisoformat(booking.get('end_time'))
        except (TypeError, ValueError, AttributeError):
            continue

        if booking['room'] == new_room and booking_date == new_date_obj:
            if is_time_overlap(new_start_obj, new_end_obj, existing_start, existing_end):
                return True
    return False

def handle_booking_submission(room_name: str, booking_date: datetime.date, start_time: datetime.time, end_time: datetime.time):
    """Processes form data and attempts a new booking."""
    
    if st.session_state.authenticated_user is None:
        st.toast("🔒 Please log in to make a booking", icon="🔒")
        return
        
    if start_time >= end_time:
        st.toast("❌ Start time must be before end time", icon="⚠️")
        return
    
    current_users = load_users_from_db() 
    user_email = current_users[st.session_state.authenticated_user]['email']
    current_bookings = load_bookings_from_db()
        
    new_booking = {
        'room': room_name,
        'date': booking_date.isoformat(), 
        'start_time': start_time.isoformat(timespec='minutes'), 
        'end_time': end_time.isoformat(timespec='minutes'), 
        'user_id': st.session_state.authenticated_user,
        'user_email': user_email,
        'date_obj': booking_date, 
        'start_time_obj': start_time,
        'end_time_obj': end_time,
    }

    if is_conflict(new_booking, current_bookings):
        st.toast(f"❌ Conflict! {room_name} is already booked during that time.", icon="🚨")
    else:
        if save_booking_to_db(new_booking):
            st.toast("✅ Booking success! Your room is confirmed.", icon="🎉")


def handle_signup(username: str, email: str, password: str, confirm_password: str):
    """Handles new user registration."""
    current_users = load_users_from_db()

    if not all([username, email, password, confirm_password]):
        st.toast("⚠️ Please fill in all fields", icon="⚠️")
        return
    
    if username in current_users:
        st.toast("⛔ Username already exists", icon="⛔")
        return
    
    if password != confirm_password:
        st.toast("❌ Passwords do not match", icon="❌")
        return

    if bcrypt_installed:
        try:
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(12)).decode('utf-8')
        except Exception:
            st.toast("❌ Error hashing password (bcrypt)", icon="🚨")
            return
    else:
        hashed_password = "MOCK_HASH_FOR_" + username
        if password != "signup":
            st.toast("⚠️ Mock Mode: Must use password 'signup' to register", icon="⚠️")
            return
    
    if save_new_user_to_db(username, email, hashed_password):
        st.toast("🎉 Sign up successful! Please log in.", icon="🎉")
        st.session_state.mode = 'login'
        st.rerun()
    else:
        st.toast("❌ Failed to save new user", icon="🚨")


def check_query_params_for_auth(current_users: Dict[str, Any]):
    """Checks URL Query Params to persist login state on refresh."""
    if st.session_state.authenticated_user is None and st.query_params:
        user_id_from_url = st.query_params.get('user')
        if user_id_from_url and user_id_from_url in current_users:
            st.session_state.authenticated_user = user_id_from_url
            st.session_state.user_role = current_users[user_id_from_url]['role']


# --- UI COMPONENTS ---

def display_profile_card():
    """Displays the profile card of the logged-in user."""
    current_users = load_users_from_db() 
    user_id = st.session_state.authenticated_user
    user_data = current_users.get(user_id, {})
    current_role = user_data.get('role', 'unknown')
    role_thai = "ผู้ดูแลระบบ" if current_role == 'admin' else "ผู้ใช้งานทั่วไป"
    
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**👤 {user_id.capitalize()}**")
    st.sidebar.markdown(f"📧 `{user_data.get('email', '-')}`")
    st.sidebar.markdown(f"🏷️ **{role_thai.upper()}**")
    st.sidebar.button("ออกจากระบบ", key="logout_btn", on_click=lambda: (
        setattr(st.session_state, 'authenticated_user', None),
        setattr(st.session_state, 'user_role', None),
        setattr(st.session_state, 'mode', 'login'),
        st.query_params.clear(),
        load_bookings_from_db.clear(),
        load_users_from_db.clear()
    ), use_container_width=True)


def display_login_form():
    """Login form."""
    current_users = load_users_from_db() 
    st.sidebar.subheader("🔒 เข้าสู่ระบบ")

    with st.sidebar.form(key='login_form'):
        username = st.text_input("ชื่อผู้ใช้ (Username)", key="login_username_input")
        password = st.text_input("รหัสผ่าน (Password)", type="password", key="login_password_input")
        
        login_button = st.form_submit_button("เข้าสู่ระบบ", use_container_width=True, type="primary")

        if login_button:
            if username in current_users:
                stored_hash_str = current_users[username].get('hashed_password', '')
                is_correct = False
                
                if bcrypt_installed and stored_hash_str.startswith("$2b$"):
                    try:
                        stored_hash_bytes = stored_hash_str.encode('utf-8')
                        password_bytes = password.encode('utf-8')
                        if bcrypt.checkpw(password_bytes, stored_hash_bytes):
                            is_correct = True
                    except Exception:
                        st.toast("❌ Hash Key is invalid. Check Firestore Console.", icon="🛠️")
                        return
                else:
                    if username == "admin.user" and password == 'p789':
                         is_correct = True
                    elif stored_hash_str == "MOCK_HASH_FOR_" + username:
                         is_correct = True

                if is_correct:
                    st.session_state.authenticated_user = username
                    st.session_state.user_role = current_users[username]['role'] 
                    st.toast(f"ยินดีต้อนรับ, {username}!", icon="👋")
                    # 🛑 Persist login status in URL
                    st.experimental_set_query_params(user=username) 
                    st.rerun()
                else:
                    st.toast("⛔ Invalid username or password", icon="⛔")
            else:
                st.toast("⛔ Invalid username", icon="⛔")
    
    st.sidebar.markdown("---")
    if st.sidebar.button("สมัครสมาชิกใหม่", key="signup_toggle"):
        st.session_state.mode = 'signup'
        st.rerun()


def display_signup_form():
    """Sign Up form."""
    st.sidebar.subheader("📝 สมัครสมาชิก")
    
    with st.sidebar.form(key='signup_form'):
        username = st.text_input("ชื่อผู้ใช้ (Username)", key="signup_username")
        email = st.text_input("อีเมล", key="signup_email")
        password = st.text_input("รหัสผ่าน", type="password", key="signup_password")
        confirm_password = st.text_input("ยืนยันรหัสผ่าน", type="password", key="signup_confirm_password")
        
        signup_button = st.form_submit_button("ลงทะเบียน", use_container_width=True, type="primary")
        
        if signup_button:
            handle_signup(username, email, password, confirm_password)

    st.sidebar.markdown("---")
    if st.sidebar.button("กลับสู่หน้าเข้าสู่ระบบ", key="login_toggle"):
        st.session_state.mode = 'login'
        st.rerun()


def display_availability_matrix():
    """Displays the real-time room availability matrix."""
    st.subheader("🗓️ Room Status")
    
    view_date = st.date_input(
        "Choose Date: ", 
        value=datetime.date.today(),
        key="view_date_select"
    )

    current_bookings = load_bookings_from_db()

    if not current_bookings:
        st.info(f"💡 All Room Avialable on {view_date.strftime('%Y-%m-%d')}.", icon="💡")
        return

    daily_bookings = []
    for b in current_bookings:
        booking_date = datetime.date.fromisoformat(b.get('date'))
        if booking_date == view_date:
            daily_bookings.append(b)

    time_index = []
    start_hour = 8
    end_hour = 17
    
    for h in range(start_hour, end_hour):
        time_index.append(f"{h:02d}:00")
        time_index.append(f"{h:02d}:30")
    
    availability_df = pd.DataFrame(index=time_index, columns=list(ROOMS.keys())).fillna("✅ Available")
    
    for booking in daily_bookings:
        room = booking['room']
        
        book_start_time = datetime.time.fromisoformat(booking.get('start_time'))
        book_end_time = datetime.time.fromisoformat(booking.get('end_time'))

        book_start_dt = datetime.datetime.combine(view_date, book_start_time)
        book_end_dt = datetime.datetime.combine(view_date, book_end_time)
        
        for slot_time_str in time_index:
            slot_time = datetime.datetime.strptime(slot_time_str, "%H:%M").time()
            slot_dt = datetime.datetime.combine(view_date, slot_time)
            slot_end_dt = slot_dt + datetime.timedelta(minutes=30)

            if slot_dt < book_end_dt and slot_end_dt > book_start_dt:
                availability_df.loc[slot_time_str, room] = f"❌ Booked by {booking['user_id']}"

    def color_cells(val):
        if "Available" in str(val):
            return 'background-color: #d4edda; color: #155724'
        else:
            return 'background-color: #f8d7da; color: #721c24'

    st.dataframe(
        availability_df.style.applymap(color_cells), 
        use_container_width=True,
        column_config={
            col: st.column_config.TextColumn(col, width="small")
            for col in availability_df.columns
        }
    )


def display_booking_form():
    """Displays the form for making a new booking."""
    st.subheader("📝 สร้างการจองใหม่")

    current_users = load_users_from_db()
    current_user = st.session_state.authenticated_user
    current_email = current_users[current_user]['email']
    
    st.info(f"ทำการจองในชื่อ: **{current_user}** ({current_email})")
    
    with st.form(key='booking_form', clear_on_submit=True):
        room_name = st.selectbox(
            "1. เลือกห้อง", 
            options=list(ROOMS.keys()),
            key="room_select"
        )

        booking_date = st.date_input(
            "2. วันที่", 
            value=datetime.date.today(),
            min_value=datetime.date.today(),
            key="date_select"
        )
            
        cols_time = st.columns(2)
        with cols_time[0]:
            start_time = st.time_input(
                "3. เวลาเริ่มต้น",
                value=datetime.time(9, 0),
                step=600, 
                key="start_time_input"
            )
        with cols_time[1]:
            end_time = st.time_input(
                "4. เวลาสิ้นสุด",
                value=datetime.time(10, 0),
                step=600, 
                key="end_time_input"
            )
        
        st.form_submit_button(
            label='ยืนยันการจอง',
            use_container_width=True,
            type="primary",
            on_click=handle_booking_submission,
            args=(room_name, booking_date, start_time, end_time)
        )


def display_data_and_export():
    """Displays current bookings, export button, and cancellation form."""
    
    st.subheader("🏢 Room Specifications")
    
    rooms_df = pd.DataFrame([
        {
            "Room Name": name, 
            "Capacity": info["capacity"], 
            "Projector": "✅ Yes" if info["has_projector"] else "❌ No"
        } 
        for name, info in ROOMS.items()
    ])
    st.dataframe(rooms_df, use_container_width=True, hide_index=True)

    st.subheader("📚 Booking List")
    
    current_bookings = load_bookings_from_db()
    current_user = st.session_state.authenticated_user
    current_role = st.session_state.user_role

    if not current_bookings:
        st.info("💡 ไม่มีห้องที่ถูกจองอยู่ในขณะนี้", icon="💡")
    else:
        bookings_df = pd.DataFrame(current_bookings)

        # 🛑 ส่วนการยกเลิก (ใช้ Select Box ที่เสถียรที่สุด)
        if current_user and (current_role == 'admin' or any(b['user_id'] == current_user for b in current_bookings)):
            st.markdown("---")
            st.markdown("##### 🗑️ ยกเลิกการจอง")

            cancellable_bookings = [
                (f"{b['date']} {b['start_time']} ({b['room']} โดย {b['user_id']})", b['doc_id'])
                for b in current_bookings
                if b['user_id'] == current_user or current_role == 'admin'
            ]
            
            if cancellable_bookings:
                options, doc_ids = zip(*cancellable_bookings)
                selected_booking_id_str = st.selectbox("เลือกรายการจองที่ต้องการยกเลิก", options, key="cancel_select")
                
                if st.button("ยืนยันการยกเลิก", key="cancel_button", type="secondary"):
                    selected_doc_id = doc_ids[options.index(selected_booking_id_str)]
                    delete_booking_from_db(selected_doc_id)
            else:
                st.info("คุณไม่มีสิทธิ์ยกเลิกการจองในขณะนี้", icon="🔒")


        bookings_df_display = bookings_df.rename(columns={
            'room': 'ห้อง',
            'date': 'วันที่',
            'start_time': 'เวลาเริ่มต้น',
            'end_time': 'เวลาสิ้นสุด',
            'user_id': 'ชื่อผู้ใช้',
            'user_email': 'อีเมล'
        })
        
        st.dataframe(
            bookings_df_display[['ห้อง', 'วันที่', 'เวลาเริ่มต้น', 'เวลาสิ้นสุด', 'ชื่อผู้ใช้', 'อีเมล']], 
            use_container_width=True, 
            hide_index=True
        )

        if current_role == 'admin':
            csv_data = convert_df_to_csv(bookings_df)
            st.download_button(
                label="⬇️ ส่งออกข้อมูลการจองทั้งหมดเป็น CSV (สำหรับ Admin เท่านั้น)",
                data=csv_data,
                file_name=f'meeting_room_bookings_{datetime.date.today()}.csv',
                mime='text/csv',
                type="primary",
                use_container_width=True
            )
        elif current_user:
            st.info("คุณต้องเป็นผู้ดูแลระบบ (Admin) เท่านั้น จึงจะสามารถส่งออกข้อมูลสถิติการจองทั้งหมดได้")

# --- MAIN APPLICATION ENTRY POINT ---

def main():
    """The main function to run the Streamlit application."""
    st.set_page_config(
        page_title="ISE Meeting Room Scheduler",
        page_icon="📅",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.title("ISE Meeting Room Scheduler 🏢")
    st.info("💡 แอปพลิเคชันนี้เชื่อมต่อกับฐานข้อมูล Firestore และจดจำสถานะล็อกอินผ่าน URL")
    
    initialize_state()
    current_users = load_users_from_db()

    # 🛑 Persist Login State on Refresh
    check_query_params_for_auth(current_users)
    
    is_authenticated = st.session_state.authenticated_user is not None

    # 1. SIDEBAR (Auth/Profile)
    if is_authenticated:
        display_profile_card()
    else:
        if st.session_state.mode == 'login':
            display_login_form()
        elif st.session_state.mode == 'signup':
            display_signup_form()

    # 2. MAIN CONTENT (Matrix)
    if st.session_state.db_ready == False:
        st.error("⛔ Cannot use the app: Database connection failed.", icon="🚨")
        return

    display_availability_matrix()
    st.markdown("---")

    col1, col2 = st.columns([1, 2])
    
    with col1:
        if is_authenticated:
            display_booking_form() 
        else:
            st.warning("👉 Please log in/sign up in the sidebar to access the booking form.", icon="👉")

    with col2:
        if is_authenticated:
            display_data_and_export()


if __name__ == "__main__":
    main()
