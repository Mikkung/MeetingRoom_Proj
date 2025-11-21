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
    st.warning("⚠️ ไม่พบไลบรารี 'bcrypt' การตรวจสอบรหัสผ่านจะใช้ Mock Logic แทน", icon="🚨")


# 🛑 นำเข้าไลบรารี Firebase
try:
    from firebase_admin import credentials, firestore, initialize_app
    firebase_installed = True
except ImportError:
    firebase_installed = False
    st.error("❌ ไม่พบไลบรารี 'firebase-admin' กรุณาติดตั้งเพื่อเชื่อมต่อ Firestore", icon="🚨")


# --- WARNING & INITIAL MOCK DATA ---
# 1. Mock User Database with Hashed Passwords (ใช้ Hash ที่คุณสร้างและจะอัปเดต)
# ⚠️ WARNING: REPLACE THESE PLACEHOLDER HASHES WITH YOUR ACTUAL BCRYPT HASHES
USERS_DB = {
    "john.doe": {
        "email": "john.doe@ise.com",
        "hashed_password": "$2b$12$itktik45CGlbHKXQ6NvFWuMJXqh9sqU.MTb9RWbf1Ru4jIsQzZbC.", 
        "role": "user" 
    },
    "jane.smith": {
        "email": "jane.smith@ise.com",
        "hashed_password": "$2b$12$FAKE.HASH.FOR.JANE.DO.NOT.USE.THIS.IN.PRODUCTION.2", 
        "role": "user"
    },
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


# --- DATABASE / FIREBASE LOGIC ---

def init_database_connection():
    """เชื่อมต่อกับ Firestore โดยใช้ st.secrets"""
    if 'db_ready' not in st.session_state:
        if not firebase_installed:
            st.session_state.db_ready = False
            return
            
        try:
            # 1. โหลด Credentials จาก st.secrets (ชื่อ key: 'firestore_credentials')
            key_dict = json.loads(st.secrets["firestore_credentials"])
            
            # 2. ยืนยันตัวตนและเริ่มต้น Firebase App
            cred = credentials.Certificate(key_dict)
            initialize_app(cred)
            
            # 3. สร้าง Firestore Client
            st.session_state.db = firestore.client()
            st.session_state.db_ready = True
            st.sidebar.success("✅ เชื่อมต่อ Firestore สำเร็จ", icon="🌐")
            
        except Exception as e:
            st.session_state.db_ready = False
            st.sidebar.error(f"❌ ข้อผิดพลาดในการเชื่อมต่อ Firestore: {e}", icon="🚨")


# 🛑 B: LOADING DATA FROM DB (Real Firestore Logic)
@st.cache_data(ttl=60)
def load_bookings_from_db():
    """โหลดข้อมูลการจองทั้งหมดจาก Firestore"""
    if not st.session_state.db_ready:
        return []

    try:
        # ดึงข้อมูลจาก Collection 'bookings'
        docs = st.session_state.db.collection("bookings").stream()
        bookings = [doc.to_dict() for doc in docs]
        return bookings
    except Exception as e:
        st.error(f"❌ ข้อผิดพลาดในการดึงข้อมูลจาก DB: {e}", icon="🚨")
        return []


# 🛑 C: SAVING DATA TO DB (Real Firestore Logic)
def save_booking_to_db(new_booking):
    """บันทึกการจองใหม่ไปยัง Firestore"""
    if not st.session_state.db_ready:
        return

    try:
        # บันทึกข้อมูลลงใน Collection 'bookings'
        st.session_state.db.collection("bookings").add(new_booking)
        load_bookings_from_db.clear() # ล้าง Cache
        return True
    except Exception as e:
        st.error(f"❌ ข้อผิดพลาดในการบันทึกข้อมูลลง DB: {e}", icon="🚨")
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

    # เรียกใช้ฟังก์ชันเชื่อมต่อฐานข้อมูล
    init_database_connection()


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
    new_date_obj = new_booking['date_obj'] # ใช้ object สำหรับเปรียบเทียบ date
    new_start_obj = new_booking['start_time_obj']
    new_end_obj = new_booking['end_time_obj']


    for booking in current_bookings:
        # ดึง Date/Time objects สำหรับการเปรียบเทียบ (แปลงจาก ISO string ที่เก็บใน DB)
        try:
            booking_date = datetime.date.fromisoformat(booking.get('date'))
            existing_start = datetime.time.fromisoformat(booking.get('start_time'))
            existing_end = datetime.time.fromisoformat(booking.get('end_time'))
        except (TypeError, ValueError, AttributeError):
             # จัดการกับข้อมูลเก่าหรือข้อมูลที่ไม่มี format ที่ถูกต้อง (ควรล้างข้อมูลใน DB)
            continue


        if booking['room'] == new_room and booking_date == new_date_obj:
            if is_time_overlap(new_start_obj, new_end_obj, existing_start, existing_end):
                return True
    return False

# --- Callback function for Form Submission ---
def handle_booking_submission(room_name, booking_date, start_time, end_time):
    """ประมวลผลข้อมูลฟอร์มและพยายามสร้างการจองใหม่"""
    
    if st.session_state.authenticated_user is None:
        st.error("🔒 ต้องทำการยืนยันตัวตนเพื่อทำการจอง", icon="🔒")
        return
        
    if start_time >= end_time:
        st.error("❌ เวลาเริ่มต้นต้องอยู่ก่อนเวลาสิ้นสุด", icon="⚠️")
        return
    
    current_user_data = USERS_DB[st.session_state.authenticated_user]
    user_email = current_user_data['email']
    
    # ดึงข้อมูลล่าสุดจาก DB (Cached)
    current_bookings = load_bookings_from_db()
        
    # ข้อมูลที่จะถูกส่งไป Firestore (ใช้ ISO string format)
    new_booking = {
        'room': room_name,
        'date': booking_date.isoformat(), 
        'start_time': start_time.isoformat(timespec='minutes'), 
        'end_time': end_time.isoformat(timespec='minutes'), 
        'user_id': st.session_state.authenticated_user,
        'user_email': user_email,
        # เก็บ object ชั่วคราวสำหรับ conflict check ในรันนี้เท่านั้น
        'date_obj': booking_date, 
        'start_time_obj': start_time,
        'end_time_obj': end_time,
    }

    if is_conflict(new_booking, current_bookings):
        st.error(f"❌ การจองขัดแย้ง! {room_name} ถูกจองแล้วในวันที่ {booking_date.strftime('%Y-%m-%d')} ระหว่าง {start_time.strftime('%H:%M')} ถึง {end_time.strftime('%H:%M')}.", icon="🚨")
    else:
        if save_booking_to_db(new_booking):
            st.success(f"✅ สำเร็จ! {room_name} ถูกจองโดย {st.session_state.authenticated_user} สำหรับวันที่ {booking_date.strftime('%Y-%m-%d')} ตั้งแต่ {start_time.strftime('%H:%M')} ถึง {end_time.strftime('%H:%M')}.", icon="🎉")

# --- UI Components: Authentication (ใช้ bcrypt) ---

def authenticate_user():
    """จัดการกระบวนการล็อกอิน/ยืนยันตัวตนของผู้ใช้ด้วย Hashed Password"""
    st.sidebar.subheader("🔒 เข้าสู่ระบบ (Production)")
    
    if st.session_state.authenticated_user:
        role_thai = "ผู้ดูแลระบบ" if st.session_state.user_role == 'admin' else "ผู้ใช้งานทั่วไป"
        st.sidebar.success(f"เข้าสู่ระบบในชื่อ: **{st.session_state.authenticated_user}** ({role_thai})")
        if st.sidebar.button("ออกจากระบบ", key="logout_btn", use_container_width=True):
            st.session_state.authenticated_user = None
            st.session_state.user_role = None
            load_bookings_from_db.clear() # Clear cache on logout
            st.rerun()
        return True
    
    with st.sidebar.form(key='login_form'):
        username = st.text_input("ชื่อผู้ใช้ (Username)", key="login_username_input")
        password = st.text_input("รหัสผ่าน (Password)", type="password", key="login_password_input")
        
        login_button = st.form_submit_button("เข้าสู่ระบบ", use_container_width=True, type="primary")

        if login_button:
            if username in USERS_DB:
                stored_hash = USERS_DB[username]['hashed_password'].encode('utf-8')
                
                is_correct = False
                if bcrypt_installed:
                    # 🛑 ตรวจสอบด้วย bcrypt จริง (ต้องมี bcrypt ติดตั้ง)
                    try:
                        if bcrypt.checkpw(password.encode('utf-8'), stored_hash):
                            is_correct = True
                    except Exception:
                        pass # Hash error, treat as incorrect
                else:
                    # 🛑 Mock Check (ใช้รหัสผ่าน Plain Text สำหรับการทดสอบเมื่อไม่มี bcrypt)
                    if (username == "john.doe" and password == "p123") or \
                       (username == "jane.smith" and password == "p456") or \
                       (username == "admin.user" and password == "p789"):
                        is_correct = True
                
                if is_correct:
                    st.session_state.authenticated_user = username
                    st.session_state.user_role = USERS_DB[username]['role'] 
                    st.success(f"ยินดีต้อนรับ, {username}!", icon="👋")
                    load_bookings_from_db.clear() # Clear cache on successful login
                    st.rerun()
                else:
                    st.error("⛔ รหัสผ่านไม่ถูกต้อง", icon="⛔")
            else:
                st.error("⛔ ชื่อผู้ใช้ไม่ถูกต้อง กรุณาตรวจสอบข้อมูล", icon="⛔")
    return False

# --- UI Components: Data Export and Availability ---

@st.cache_data
def convert_df_to_csv(df):
    """แปลง Pandas DataFrame เป็น CSV สำหรับดาวน์โหลด"""
    df_export = df.copy()
    
    # ใช้คอลัมน์ที่เป็น string ในการ export
    df_export['Date'] = df_export['date'].astype(str)
    df_export['StartTime'] = df_export['start_time'].astype(str)
    df_export['EndTime'] = df_export['end_time'].astype(str)
    
    columns_to_keep = ['room', 'Date', 'StartTime', 'EndTime', 'user_id', 'user_email']
    # ลบคอลัมน์ที่ไม่ใช่ข้อมูลหลักออก
    df_export = df_export[[col for col in columns_to_keep if col in df_export.columns]]

    df_export = df_export.rename(columns={
        'room': 'Room',
        'user_id': 'Username',
        'user_email': 'Email'
    })

    # ใช้ BytesIO ในการสร้างไฟล์
    output = io.StringIO()
    df_export.to_csv(output, index=False, encoding='utf-8')
    processed_data = output.getvalue().encode('utf-8')
    return processed_data


def display_availability_matrix():
    """แสดงตารางสถานะห้องว่างแบบเรียลไทม์สำหรับวันที่เลือก"""
    st.subheader("🗓️ ปฏิทินสถานะห้องว่างแบบเรียลไทม์")
    
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
        # ใช้ .get('date') เพราะเป็น ISO string ที่แน่นอนว่าอยู่ใน DB
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

def display_data_and_export():
    """แสดงรายการห้องและการจองปัจจุบัน พร้อมปุ่ม export ที่จำกัดสิทธิ์ตามบทบาท"""
    
    st.subheader("🏢 รายละเอียดห้องประชุม")
    
    rooms_df = pd.DataFrame([
        {
            "Room Name": name, 
            "Capacity": info["capacity"], 
            "Projector": "✅ Yes" if info["has_projector"] else "❌ No"
        } 
        for name, info in st.session_state.rooms.items()
    ])
    st.dataframe(rooms_df, use_container_width=True, hide_index=True)

    st.subheader("📚 รายการจองทั้งหมดในปัจจุบัน")
    
    current_bookings = load_bookings_from_db()

    if not current_bookings:
        st.info("💡 ไม่มีห้องที่ถูกจองอยู่ในขณะนี้", icon="💡")
    else:
        bookings_df = pd.DataFrame(current_bookings)
        
        bookings_df = bookings_df.sort_values(by=['date', 'start_time'], ascending=True)
        
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

        if st.session_state.user_role == 'admin':
            csv_data = convert_df_to_csv(bookings_df)
            st.download_button(
                label="⬇️ ส่งออกข้อมูลการจองทั้งหมดเป็น CSV (สำหรับ Admin เท่านั้น)",
                data=csv_data,
                file_name=f'meeting_room_bookings_{datetime.date.today()}.csv',
                mime='text/csv',
                type="primary",
                use_container_width=True
            )
        elif st.session_state.authenticated_user:
            st.info("คุณต้องเป็นผู้ดูแลระบบ (Admin) เท่านั้น จึงจะสามารถส่งออกข้อมูลสถิติการจองทั้งหมดได้")
        else:
            st.info("เข้าสู่ระบบเพื่อดูข้อมูลการจองและตัวเลือกการส่งออกสำหรับ Admin")


# --- Main Application Layout ---
def main():
    """ฟังก์ชันหลักสำหรับรันแอปพลิเคชัน Streamlit"""
    st.set_page_config(
        page_title="ISE Meeting Room Scheduler (Production Ready)",
        page_icon="📅",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.title("ISE Meeting Room Scheduler 🏢 (Production Ready)")
    st.info("💡 แอปพลิเคชันนี้เชื่อมต่อกับฐานข้อมูล Firestore แล้ว หากมีการตั้งค่า Secrets ถูกต้อง ข้อมูลจะถูกบันทึกอย่างถาวร")
    
    initialize_state()
    
    is_authenticated = authenticate_user()

    display_availability_matrix()
    st.markdown("---")

    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("📝 สร้างการจองใหม่")
        if st.session_state.db_ready == False:
            st.error("⛔ ไม่สามารถใช้งานฟอร์มได้: การเชื่อมต่อฐานข้อมูลล้มเหลว", icon="🚨")
        elif is_authenticated:
            with st.form(key='booking_form', clear_on_submit=True):
                current_user = st.session_state.authenticated_user
                current_email = USERS_DB[current_user]['email']
                st.info(f"ทำการจองในชื่อ: **{current_user}** ({current_email})")
                
                room_name = st.selectbox(
                    "1. เลือกห้อง", 
                    options=list(st.session_state.rooms.keys()),
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
        else:
            st.warning("👉 กรุณาเข้าสู่ระบบที่แถบด้านข้าง (Sidebar) เพื่อเข้าถึงฟอร์มการจอง", icon="👉")

    with col2:
        display_data_and_export()


if __name__ == "__main__":
    main()

