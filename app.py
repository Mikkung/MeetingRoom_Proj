import streamlit as st
import datetime
import pandas as pd
import json
import io
import plotly.express as px
# ต้องติดตั้ง: pip install firebase-admin bcrypt plotly

# 🛑 ตรวจสอบการติดตั้งไลบรารีที่ซับซ้อน
try:
    import bcrypt
    bcrypt_installed = True
except ImportError:
    bcrypt_installed = False

try:
    from firebase_admin import credentials, firestore, initialize_app, get_app
    from firebase_admin.exceptions import InvalidArgumentError
    firebase_installed = True
except ImportError:
    from firebase_admin import get_app
    firebase_installed = False

if not firebase_installed:
    st.error("❌ ไม่พบไลบรารี 'firebase-admin' กรุณาติดตั้งเพื่อเชื่อมต่อ Firestore", icon="🚨")
if not bcrypt_installed:
    st.warning("⚠️ ไม่พบไลบรารี 'bcrypt' การตรวจสอบรหัสผ่าน/Sign Up จะทำงานใน Mock Mode", icon="🚨")


# --- CONFIGURATION & MOCK FALLBACK ---

# 1. Mock User Database (ใช้ Hash ที่คุณสร้างและจะอัปเดต)
# ⚠️ ข้อมูลนี้ใช้เป็น Fallback เท่านั้น หาก Firestore Collection 'users' ว่างเปล่า
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
    "ISE_Meeting_Room_III_304/1_Fl1": {"capacity": 20, "has_projector": False}
}

# 3. Time Slot Configuration (ใช้สำหรับ Slider: 8:00 ถึง 17:00, 540 นาที)
TOTAL_MINUTES = 9 * 60 # 9 hours (8:00 to 17:00)
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
            # ป้องกันการเรียก initialize_app ซ้ำ
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
            st.sidebar.error("💡 ตรวจสอบ: Key 'firestore_credentials' ใน Streamlit Secrets ว่าเป็น JSON ที่ถูกต้องหรือไม่", icon="🛠️")


# 🛑 B1: LOADING USERS FROM DB
@st.cache_data(ttl=3600) # Cache User List for 1 hour
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


# 🛑 B2: LOADING BOOKINGS FROM DB (TTL=5s for Near-Real-time)
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
            booking_data['doc_id'] = doc.id # Store the document ID
            bookings.append(booking_data)
            
        return bookings
    except Exception as e:
        st.error(f"❌ ข้อผิดพลาดในการดึงข้อมูลการจองจาก DB: {e}", icon="🚨")
        return []


# 🛑 C1: SAVING BOOKING TO DB
def save_booking_to_db(new_booking):
    """บันทึกการจองใหม่ไปยัง Firestore"""
    if not st.session_state.db_ready:
        return False

    try:
        st.session_state.db.collection("bookings").add(new_booking)
        load_bookings_from_db.clear() 
        return True
    except Exception as e:
        st.error(f"❌ ข้อผิดพลาดในการบันทึกข้อมูลลง DB: {e}", icon="🚨")
        return False

# 🛑 C2: DELETING BOOKING FROM DB
def delete_booking_from_db(doc_id):
    """ลบเอกสารการจองจาก Firestore ด้วย Document ID"""
    if not st.session_state.db_ready:
        return False
    
    # doc_id ถูกส่งมาในรูปแบบ 'Cancel-{doc_id}' จาก st.data_editor
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

# 🛑 C3: SAVING NEW USER TO DB
def save_new_user_to_db(username, email, hashed_password):
    """บันทึกผู้ใช้ใหม่ลงใน Collection 'users'"""
    if not st.session_state.db_ready:
        return False
    
    try:
        user_data = {
            "email": email,
            "hashed_password": hashed_password,
            "role": "user" # กำหนดบทบาทเริ่มต้นเป็น user
        }
        st.session_state.db.collection("users").document(username).set(user_data)
        load_users_from_db.clear() # Clear user cache
        return True
    except Exception as e:
        st.error(f"❌ ข้อผิดพลาดในการบันทึกผู้ใช้ใหม่: {e}", icon="🚨")
        return False


# --- State Management and Conflict Check ---

def initialize_state():
    """เริ่มต้นตัวแปร Session State และโหลดข้อมูล"""
    if 'rooms' not in st.session_state:
        st.session_state.rooms = ROOMS
    if 'authenticated_user' not in st.session_state:
        st.session_state.authenticated_user = None
    if 'user_role' not in st.session_state:
        st.session_state.user_role = None

    init_database_connection() # เชื่อมต่อ DB


def is_time_overlap(start1, end1, start2, end2):
    """ตรวจสอบว่าช่วงเวลาสองช่วงทับซ้อนกันหรือไม่ (ใช้ datetime.time objects)"""
    def time_to_seconds(t):
        if t is None: return -1 
        return t.hour * 3600 + t.minute * 60 + t.second
    
    s1, e1 = time_to_seconds(start1), time_to_seconds(end1)
    s2, e2 = time_to_seconds(start2), time_to_seconds(end2)
    
    return not (e1 <= s2 or s1 >= e2)

def is_conflict(new_booking, current_bookings):
    """ตรวจสอบว่าการจองใหม่ขัดแย้งกับการจองที่มีอยู่หรือไม่ โดยใช้ข้อมูลที่โหลดจาก DB"""
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
            if is_time_overlap(new_start_obj, new_end_obj, existing_start, existing_end):
                return True
    return False


# --- Callback function for Form Submission ---
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


# --- UI Components: Authentication & Sign Up ---

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


def display_login_form():
    """ฟอร์มสำหรับ Login"""
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
                        st.toast("❌ Hash Key ไม่สมบูรณ์ กรุณาตรวจสอบ Firestore Console", icon="🛠️")
                        return
                else:
                    # 🛑 Mock Check (สำหรับ Admin P789 หรือ Mock User)
                    if username == "admin.user" and password == 'p789':
                         is_correct = True
                    elif stored_hash_str.startswith("MOCK_HASH_FOR_"):
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


# --- UI Components: Display & Export ---

@st.cache_data
def convert_df_to_csv(df):
    """แปลง Pandas DataFrame เป็น CSV สำหรับดาวน์โหลด"""
    df_export = df.copy()
    
    df_export['Date'] = df_export['date'].astype(str)
    df_export['StartTime'] = df_export['start_time'].astype(str)
    df_export['EndTime'] = df_export['end_time'].astype(str)
    
    columns_to_keep = ['room', 'Date', 'StartTime', 'EndTime', 'user_id', 'user_email']
    df_export = df_export[[col for col in columns_to_keep if col in df_export.columns]]

    df_export = df_export.rename(columns={
        'room': 'Room',
        'user_id': 'Username',
        'user_email': 'Email'
    })

    output = io.StringIO()
    df_export.to_csv(output, index=False, encoding='utf-8')
    processed_data = output.getvalue().encode('utf-8')
    return processed_data


def display_availability_chart(bookings, view_date):
    """แสดงสถานะห้องว่างแบบ Graphical Calendar View (Plotly Gantt Chart)"""
    st.subheader(f"🗓️ สถานะห้องว่างแบบแผนภูมิ (วันที่ {view_date.strftime('%Y-%m-%d')})")

    daily_bookings = []
    for b in bookings:
        try:
            booking_date = datetime.date.fromisoformat(b.get('date'))
            if booking_date == view_date:
                daily_bookings.append({
                    'Room': b['room'],
                    'Start': datetime.datetime.combine(view_date, datetime.time.fromisoformat(b.get('start_time'))),
                    'Finish': datetime.datetime.combine(view_date, datetime.time.fromisoformat(b.get('end_time'))),
                    'User': b['user_id']
                })
        except Exception:
            continue
    
    if not daily_bookings:
        st.info("💡 ไม่มีห้องถูกจองในวันที่เลือก", icon="💡")
        return

    df = pd.DataFrame(daily_bookings)
    
    df['Color'] = df['User']

    fig = px.timeline(
        df, 
        x_start="Start", 
        x_end="Finish", 
        y="Room", 
        color="User",
        text="User",
        color_discrete_sequence=px.colors.qualitative.Bold,
        title=f"การจองห้องประชุมวันที่ {view_date.strftime('%Y-%m-%d')}"
    )
    # 

    fig.update_yaxes(autorange="reversed") 
    fig.update_layout(xaxis_title="เวลา", yaxis_title="ห้องประชุม", legend_title="ผู้จอง")
    fig.update_traces(opacity=0.8, textposition='inside')

    time_start = datetime.datetime.combine(view_date, minutes_to_time(0))
    time_end = datetime.datetime.combine(view_date, minutes_to_time(TOTAL_MINUTES))
    # 🛑 FIX: ลบ tickformat ที่มีสัญลักษณ์ % ออกเพื่อป้องกัน SyntaxError ของ Streamlit JS
    fig.update_xaxes(range=[time_start, time_end]) 

    st.plotly_chart(fig, use_container_width=True)


def display_booking_form():
    """แสดงฟอร์มสำหรับสร้างการจองใหม่"""
    st.subheader("📝 สร้างการจองใหม่")

    min_minutes = 0
    max_minutes = TOTAL_MINUTES 
    default_start_minutes = START_HOUR * 60 + 60 
    default_end_minutes = default_start_minutes + 60 

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
            
        time_range = st.slider(
            "3. เลือกช่วงเวลา (10 นาทีต่อก้าว)",
            min_value=min_minutes,
            max_value=max_minutes,
            value=(default_start_minutes, default_end_minutes),
            step=10,
            format='%H:%M',
            key="time_range_slider",
            label_visibility="visible"
        )
        
        start_time = minutes_to_time(time_range[0])
        end_time = minutes_to_time(time_range[1])

        st.markdown(f"**เวลาที่เลือก:** {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}")
        
        st.form_submit_button(
            label='ยืนยันการจอง',
            use_container_width=True,
            type="primary",
            on_click=handle_booking_submission,
            args=(room_name, booking_date, start_time, end_time)
        )


def display_data_and_export():
    """แสดงรายการห้องและการจองปัจจุบัน พร้อมปุ่ม export และ Cancel"""
    
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
        
        # สำหรับ Download Button
        if current_role == 'admin':
            bookings_df = pd.DataFrame(current_bookings)
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


# --- Main Application Layout ---
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
    
    if st.session_state.authenticated_user:
        display_profile_card()
    else:
        if 'mode' not in st.session_state:
             st.session_state.mode = 'login'

        if st.session_state.mode == 'login':
            display_login_form()
        elif st.session_state.mode == 'signup':
            display_signup_form()

    if st.session_state.db_ready == False:
        st.error("⛔ ไม่สามารถใช้งานได้: การเชื่อมต่อฐานข้อมูลล้มเหลว", icon="🚨")
        return

    view_date = st.date_input(
        "เลือกวันที่เพื่อดูสถานะห้องว่าง (Chart View)", 
        value=datetime.date.today(),
        key="chart_view_date"
    )

    current_bookings = load_bookings_from_db()
    display_availability_chart(current_bookings, view_date)

    st.markdown("---")

    col1, col2 = st.columns([1, 2])
    
    with col1:
        if st.session_state.authenticated_user:
            display_booking_form() 
        else:
            st.warning("👉 กรุณาเข้าสู่ระบบ/สมัครสมาชิกที่แถบด้านข้าง (Sidebar) เพื่อสร้างการจอง", icon="👉")

    with col2:
        if st.session_state.authenticated_user:
            display_data_and_export()


if __name__ == "__main__":
    main()
