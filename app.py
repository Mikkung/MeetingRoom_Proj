import streamlit as st
import datetime
import pandas as pd
import json
import io
# ต้องติดตั้ง: pip install firebase-admin bcrypt

# 🛑 ต้องใช้ try-except เนื่องจาก Streamlit Cloud อาจไม่ให้ติดตั้ง bcrypt ได้ง่ายๆ
try:
    import bcrypt
    bcrypt_installed = True
except ImportError:
    bcrypt_installed = False
    st.warning("⚠️ ไม่พบไลบรารี 'bcrypt' การตรวจสอบรหัสผ่าน/Sign Up จะทำงานใน Mock Mode", icon="🚨")


# 🛑 นำเข้าไลบรารี Firebase
try:
    from firebase_admin import credentials, firestore, initialize_app, get_app
    from firebase_admin.exceptions import InvalidArgumentError
    firebase_installed = True
except ImportError:
    from firebase_admin import get_app
    firebase_installed = False
    st.error("❌ ไม่พบไลบรารี 'firebase-admin' กรุณาติดตั้งเพื่อเชื่อมต่อ Firestore", icon="🚨")


# --- CONFIGURATION & UTILITIES ---

# 1. Mock User Database (ใช้ Hash ที่คุณสร้างและจะอัปเดต)
MOCK_USER_FALLBACK = {
    "admin.user": {
        "email": "admin@ise.com",
        "hashed_password": "$2b$12$FAKE.HASH.FOR.ADMIN.DO.NOT.USE.THIS.IN.PRODUCTION.3", 
        "role": "admin" 
    }
}

# 2. Room Configuration
ROOMS = {
    "ISE_Meeting_Room_I_305_Fl1": {"capacity": 8, "has_projector": True},
    "ISE_Meeting_Room_II_Fl2": {"capacity": 20, "has_projector": True},
    "ISE_Meeting_Room_III_304/1_Fl1": {"capacity": 20, "has_projector": True}
}

# 3. Time Slot Configuration 
TOTAL_MINUTES = 9 * 60 
START_HOUR = 8

def minutes_to_time(minutes):
    """แปลงนาทีตั้งแต่ 8:00 เป็นวัตถุ datetime.time"""
    total_minutes = START_HOUR * 60 + minutes
    hour = total_minutes // 60
    minute = total_minutes % 60
    return datetime.time(hour, minute)


# --- DATABASE / FIREBASE LOGIC ---

def init_database_connection():
    """เชื่อมต่อกับ Firestore และป้องกันการเริ่มต้นซ้ำ"""
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
            st.session_state.mode = 'login' 
            st.sidebar.success("✅ เชื่อมต่อ Firestore สำเร็จ", icon="🌐")
            
        except Exception as e:
            st.session_state.db_ready = False
            st.sidebar.error(f"❌ ข้อผิดพลาดในการเชื่อมต่อ Firestore: {e}", icon="🚨")
            st.sidebar.error("💡 ตรวจสอบ: Key 'firestore_credentials' ใน Streamlit Secrets", icon="🛠️")


@st.cache_data(ttl=3600)
def load_users_from_db():
    """โหลดข้อมูลผู้ใช้ทั้งหมดจาก Collection 'users' ใน Firestore"""
    if not st.session_state.db_ready:
        return MOCK_USER_FALLBACK 

    try:
        users = {}
        docs = st.session_state.db.collection("users").stream()
        for doc in docs:
            user_data = doc.to_dict()
            users[doc.id] = user_data
        
        if not users:
            st.warning("⚠️ Collection 'users' ว่างเปล่า ใช้ข้อมูล Mock Admin", icon="⚠️")
            return MOCK_USER_FALLBACK
            
        return users
    except Exception as e:
        st.error(f"❌ ข้อผิดพลาดในการโหลดข้อมูลผู้ใช้จาก DB: {e}", icon="🚨")
        return MOCK_USER_FALLBACK 


@st.cache_data(ttl=5) 
def load_bookings_from_db():
    """โหลดข้อมูลการจองทั้งหมดจาก Firestore (Near-Real-time)"""
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
        st.error(f"❌ ข้อผิดพลาดในการดึงข้อมูลการจองจาก DB: {e}", icon="🚨")
        return []


def save_booking_to_db(new_booking):
    """บันทึกการจองใหม่ไปยัง Firestore"""
    if not st.session_state.db_ready:
        return False

    try:
        booking_to_save = {k: v for k, v in new_booking.items() if not k.endswith('_obj')}
        st.session_state.db.collection("bookings").add(booking_to_save)
        load_bookings_from_db.clear() 
        return True
    except Exception as e:
        st.error(f"❌ ข้อผิดพลาดในการบันทึกข้อมูลลง DB: {e}", icon="🚨")
        return False


def delete_booking_from_db(doc_id):
    """ลบเอกสารการจองจาก Firestore ด้วย Document ID"""
    if not st.session_state.db_ready:
        return False
    
    if doc_id.startswith("Cancel-"):
        actual_doc_id = doc_id.split("-", 1)[1]
    else:
        actual_doc_id = doc_id
    
    try:
        st.session_state.db.collection("bookings").document(actual_doc_id).delete()
        load_bookings_from_db.clear()
        st.toast("🗑️ การจองถูกยกเลิกแล้ว", icon="🗑️")
        return True
    except Exception as e:
        st.error(f"❌ ข้อผิดพลาดในการลบการจอง: {e}", icon="🚨")
        return False


# --- Core Logic: Conflict Check & Callbacks ---

def is_conflict(new_booking, current_bookings):
    """ตรวจสอบความขัดแย้งของการจอง"""
    new_room = new_booking['room']
    new_date_obj = new_booking['date_obj']
    new_start_obj = new_booking['start_time_obj']
    new_end_obj = new_booking['end_time_obj']

    for booking in current_bookings:
        try:
            booking_date = datetime.date.fromisoformat(booking.get('date'))
            existing_start = datetime.time.fromisoformat(booking.get('start_time'))
            existing_end = datetime.time.fromisoformat(booking.get('end_time'))
        except (TypeError, ValueError, AttributeError):
            continue

        if booking['room'] == new_room and booking_date == new_date_obj:
            def time_to_seconds(t):
                return t.hour * 3600 + t.minute * 60 + t.second
            
            s_new, e_new = time_to_seconds(new_start_obj), time_to_seconds(new_end_obj)
            s_exist, e_exist = time_to_seconds(existing_start), time_to_seconds(existing_end)

            if not (e_new <= s_exist or s_new >= e_exist):
                return True
    return False


def handle_booking_submission(room_name, booking_date, start_time, end_time):
    """ประมวลผลข้อมูลฟอร์มและพยายามสร้างการจองใหม่"""
    
    if st.session_state.authenticated_user is None:
        st.toast("🔒 กรุณาเข้าสู่ระบบก่อนทำการจอง", icon="🔒")
        return
        
    if start_time >= end_time:
        st.toast("❌ เวลาเริ่มต้นต้องอยู่ก่อนเวลาสิ้นสุด", icon="⚠️")
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
        st.toast(f"❌ การจองขัดแย้ง! {room_name} ถูกจองแล้วในช่วงเวลานั้น", icon="🚨")
    else:
        if save_booking_to_db(new_booking):
            st.toast("✅ การจองสำเร็จ! ห้องของคุณถูกบันทึกแล้ว", icon="🎉")


def handle_signup(username, email, password, confirm_password):
    """จัดการการลงทะเบียนผู้ใช้ใหม่"""
    current_users = load_users_from_db()

    if not all([username, email, password, confirm_password]):
        st.toast("⚠️ กรุณากรอกข้อมูลให้ครบถ้วน", icon="⚠️")
        return
    
    if username in current_users:
        st.toast("⛔ ชื่อผู้ใช้นี้ถูกใช้งานแล้ว", icon="⛔")
        return
    
    if password != confirm_password:
        st.toast("❌ รหัสผ่านและยืนยันรหัสผ่านไม่ตรงกัน", icon="❌")
        return

    if bcrypt_installed:
        try:
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(12)).decode('utf-8')
        except Exception:
            st.toast("❌ ข้อผิดพลาดในการเข้ารหัสรหัสผ่าน (bcrypt)", icon="🚨")
            return
    else:
        hashed_password = "MOCK_HASH_FOR_" + username
        if password != "signup":
            st.toast("⚠️ Mock Mode: ต้องใช้รหัสผ่าน 'signup' ในโหมดนี้เพื่อลงทะเบียน", icon="⚠️")
            return
    
    if save_new_user_to_db(username, email, hashed_password):
        st.toast("🎉 ลงทะเบียนสำเร็จ! กรุณาเข้าสู่ระบบ", icon="🎉")
        st.session_state.mode = 'login'
        st.rerun()
    else:
        st.toast("❌ บันทึกผู้ใช้ใหม่ไม่สำเร็จ", icon="🚨")


# --- UI Components: Display Functions (Defined before main) ---

def display_profile_card():
    """แสดง Profile Card ของผู้ใช้ที่ล็อกอินแล้ว"""
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
        load_bookings_from_db.clear(),
        load_users_from_db.clear(),
        setattr(st.session_state, 'mode', 'login')
    ), use_container_width=True)


def authenticate_user():
    """จัดการกระบวนการล็อกอิน/ยืนยันตัวตนของผู้ใช้ด้วย Hashed Password โดยดึงข้อมูลจาก DB"""
    st.sidebar.subheader("🔒 เข้าสู่ระบบ (Production)")
    
    if st.session_state.authenticated_user:
        current_users = load_users_from_db() 
        current_role = current_users[st.session_state.authenticated_user]['role']
        role_thai = "ผู้ดูแลระบบ" if current_role == 'admin' else "ผู้ใช้งานทั่วไป"
        st.sidebar.success(f"เข้าสู่ระบบในชื่อ: **{st.session_state.authenticated_user}** ({role_thai})")
        if st.sidebar.button("ออกจากระบบ", key="logout_btn", use_container_width=True):
            st.session_state.authenticated_user = None
            st.session_state.user_role = None
            load_bookings_from_db.clear()
            load_users_from_db.clear()
            st.rerun()
        return True
    
    current_users = load_users_from_db() 

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
                        st.toast("❌ Hash Key ไม่สมบูรณ์ กรุณาตรวจสอบ Firestore Console", icon="🛠️")
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
                    st.rerun()
                else:
                    st.toast("⛔ ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", icon="⛔")
            else:
                st.toast("⛔ ชื่อผู้ใช้ไม่ถูกต้อง", icon="⛔")
    
    st.sidebar.markdown("---")
    if st.sidebar.button("สมัครสมาชิกใหม่", key="signup_toggle"):
        st.session_state.mode = 'signup'
        st.rerun()
    return False # ต้องมี return ค่านี้


def display_login_form():
    """Wrapper function for login form (for modularity)"""
    return authenticate_user()


def display_signup_form():
    """ฟอร์มสำหรับ Sign Up"""
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
    """แสดงตารางสถานะห้องว่างแบบเรียลไทม์"""
    st.subheader("🗓️ สถานะห้องว่างแบบตาราง")
    
    view_date = st.date_input(
        "เลือกวันที่เพื่อดูสถานะห้องว่าง", 
        value=datetime.date.today(),
        key="view_date_select"
    )

    current_bookings = load_bookings_from_db()

    if not current_bookings:
        st.info(f"💡 ห้องทั้งหมดว่างในวันที่ {view_date.strftime('%Y-%m-%d')}.", icon="💡")
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
    """แสดงฟอร์มสำหรับสร้างการจองใหม่"""
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
    """แสดงรายการห้องและการจองปัจจุบัน พร้อมปุ่ม export ที่จำกัดสิทธิ์ตามบทบาท"""
    
    st.subheader("🏢 รายละเอียดห้องประชุม")
    
    rooms_df = pd.DataFrame([
        {
            "Room Name": name, 
            "Capacity": info["capacity"], 
            "Projector": "✅ Yes" if info["has_projector"] else "❌ No"
        } 
        for name, info in ROOMS.items()
    ])
    st.dataframe(rooms_df, use_container_width=True, hide_index=True)

    st.subheader("📚 รายการจองทั้งหมดในปัจจุบัน")
    
    current_bookings = load_bookings_from_db()
    current_user = st.session_state.authenticated_user
    current_role = st.session_state.user_role

    if not current_bookings:
        st.info("💡 ไม่มีห้องที่ถูกจองอยู่ในขณะนี้", icon="💡")
    else:
        bookings_df = pd.DataFrame(current_bookings)

        bookings_for_display = []
        for b in current_bookings:
            is_owner = b['user_id'] == current_user
            can_cancel = is_owner or current_role == 'admin'
            
            row = {
                'ID': b['doc_id'][:6] + '...', 
                'ห้อง': b['room'],
                'วันที่': b['date'],
                'เวลาเริ่มต้น': b['start_time'],
                'เวลาสิ้นสุด': b['end_time'],
                'ผู้จอง': b['user_id'],
                'ยกเลิก': f"Cancel-{b['doc_id']}" if can_cancel else "" 
            }
            bookings_for_display.append(row)
            
        bookings_df_display = pd.DataFrame(bookings_for_display)

        st.data_editor(
            bookings_df_display, 
            column_config={
                "ยกเลิก": st.column_config.ButtonColumn(
                    "ยกเลิก",
                    help="คลิกเพื่อยกเลิกการจอง",
                    on_click=delete_booking_from_db,
                    args=['<item>'] 
                ),
            },
            hide_index=True,
            use_container_width=True,
            disabled=('ID', 'ห้อง', 'วันที่', 'เวลาเริ่มต้น', 'เวลาสิ้นสุด', 'ผู้จอง')
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
        
        
def initialize_state():
    """ฟังก์ชันเริ่มต้น Session State และการเชื่อมต่อ DB"""
    init_database_connection()
    
    if 'rooms' not in st.session_state:
        st.session_state.rooms = ROOMS
    if 'authenticated_user' not in st.session_state:
        st.session_state.authenticated_user = None
    if 'user_role' not in st.session_state:
        st.session_state.user_role = None
    if 'mode' not in st.session_state:
        st.session_state.mode = 'login'


def main():
    """ฟังก์ชันหลักสำหรับรันแอปพลิเคชัน Streamlit"""
    st.set_page_config(
        page_title="ISE Meeting Room Scheduler (Feature Complete)",
        page_icon="📅",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.title("ISE Meeting Room Scheduler 🏢 (Feature Complete)")
    st.info("💡 แอปพลิเคชันนี้เชื่อมต่อกับฐานข้อมูล Firestore แล้ว หากมีการตั้งค่า Secrets ถูกต้อง ข้อมูลจะถูกบันทึกอย่างถาวร")
    
    initialize_state()
    
    # 🛑 แก้ไข: เรียก authenticate_user() โดยตรง
    is_authenticated = authenticate_user()

    display_availability_matrix()
    st.markdown("---")

    col1, col2 = st.columns([1, 2])
    
    with col1:
        if st.session_state.authenticated_user:
            display_booking_form() 
        else:
            st.warning("👉 กรุณาเข้าสู่ระบบ/สมัครสมาชิกที่แถบด้านข้าง (Sidebar) เพื่อเข้าถึงฟอร์มการจอง", icon="👉")

    with col2:
        if st.session_state.authenticated_user:
            display_data_and_export()


if __name__ == "__main__":
    main()
