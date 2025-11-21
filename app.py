import streamlit as st
import datetime
import pandas as pd
# IMPORT IS NEEDED: pip install bcrypt
# import bcrypt 

# --- WARNING & INITIAL MOCK DATA ---
# 1. Mock User Database with Hashed Passwords
# WARNING: The 'hashed_password' below are just placeholders. 
# You MUST use a tool (like a Python script with bcrypt) to generate real hashes 
# for your production database/config!
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

# --- DATABASE / FIREBASE PLACEHOLDERS ---

# 🛑 A: **PLACEHOLDER FOR FIREBASE INITIALIZATION**
# ในการใช้งานจริง คุณจะต้องใช้ไลบรารี 'firebase-admin' หรือ 'google-cloud-firestore' 
# และตั้งค่าการเชื่อมต่อที่นี่ (เช่น st.session_state.db = firestore.client())
# For deployment on Streamlit Cloud, you would use st.secrets.
def init_database_connection():
    """เชื่อมต่อกับ Firestore หรือฐานข้อมูลอื่นๆ"""
    if 'db_ready' not in st.session_state:
        # st.session_state.db_client = firestore.client() # Example for Firestore client
        try:
            # Load Credentials form st.secrets
            key_dict = json.loads(st.secrets["firestore_credentials"])

            cred = credentials.Certificate(key_dict)
            initialize_app(cred)
            st.session_state.db = firestore.client()
            st.session_state.db_ready = True
            st.success("✅ ระบบฐานข้อมูล (Mock) พร้อมใช้งาน", icon="🌐")
        except Exception as e:
            st.session_state.db_ready = False
            st.sidebar.error(f"❌ ไม่สามารถเชื่อมต่อ Firestore ได้: {e}", icon="🚨")
            
# 🛑 B: **PLACEHOLDER FOR LOADING DATA FROM DB**
@st.cache_data(ttl=60) # Caching is essential to avoid hitting DB limits too often
def load_bookings_from_db():
    """โหลดข้อมูลการจองทั้งหมดจาก Firestore"""
    # ในการใช้งานจริง: Q = db_client.collection("bookings").stream()
    # bookings = [doc.to_dict() for doc in Q]
    
    # สำหรับโค้ดตัวอย่างนี้ เราจะโหลดจาก Session State (หน่วยความจำชั่วคราว)
    # เพื่อให้โค้ดยังคงทำงานได้จนกว่าจะมีการเชื่อมต่อ DB จริง
    return st.session_state.in_memory_bookings

# 🛑 C: **PLACEHOLDER FOR SAVING DATA TO DB**
def save_booking_to_db(new_booking):
    """บันทึกการจองใหม่ไปยัง Firestore"""
    # ในการใช้งานจริง: db_client.collection("bookings").add(new_booking)
    
    # สำหรับโค้ดตัวอย่างนี้ เราจะบันทึกใน Session State
    st.session_state.in_memory_bookings.append(new_booking)
    # Clear cache to force reload of data from the 'DB' (in-memory)
    load_bookings_from_db.clear() 

# --- State Management and Conflict Check (ปรับปรุงการเริ่มต้น) ---

def initialize_state():
    """เริ่มต้นตัวแปร Session State และโหลดข้อมูล"""
    init_database_connection()
    
    # ใช้ตัวแปรนี้แทน Session State.bookings เดิม เพื่อจำลองการโหลดจาก DB
    if 'in_memory_bookings' not in st.session_state:
        st.session_state.in_memory_bookings = []

    if 'rooms' not in st.session_state:
        st.session_state.rooms = ROOMS
        
    if 'authenticated_user' not in st.session_state:
        st.session_state.authenticated_user = None
    
    if 'user_role' not in st.session_state:
        st.session_state.user_role = None

def is_time_overlap(start1, end1, start2, end2):
    """ตรวจสอบว่าช่วงเวลาสองช่วงทับซ้อนกันหรือไม่ (ใช้ datetime.time objects)"""
    def time_to_seconds(t):
        if t is None: return -1 
        return t.hour * 3600 + t.minute * 60 + t.second
    
    s1, e1 = time_to_seconds(start1), time_to_seconds(end1)
    s2, e2 = time_to_seconds(start2), time_to_seconds(end2)
    
    # เงื่อนไขการทับซ้อน
    return not (e1 <= s2 or s1 >= e2)

def is_conflict(new_booking, current_bookings):
    """ตรวจสอบว่าการจองใหม่ขัดแย้งกับการจองที่มีอยู่หรือไม่ โดยใช้ข้อมูลที่โหลดจาก DB"""
    new_room = new_booking['room']
    new_date = new_booking['date']
    new_start = new_booking['start_time']
    new_end = new_booking['end_time']

    for booking in current_bookings:
        # ต้องแปลง datetime objects ให้เป็น type ที่ถูกต้อง
        booking_date = booking['date']
        if isinstance(booking_date, str):
            booking_date = datetime.date.fromisoformat(booking_date)
            
        if booking['room'] == new_room and booking_date == new_date:
            # ต้องแปลง time objects ให้เป็น type ที่ถูกต้อง
            existing_start = booking['start_time']
            existing_end = booking['end_time']
            if isinstance(existing_start, str):
                existing_start = datetime.time.fromisoformat(existing_start)
            if isinstance(existing_end, str):
                existing_end = datetime.time.fromisoformat(existing_end)

            if is_time_overlap(new_start, new_end, existing_start, existing_end):
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
    
    # โหลดข้อมูลล่าสุดจาก 'DB' ก่อนตรวจสอบความขัดแย้ง
    current_bookings = load_bookings_from_db()
        
    new_booking = {
        'room': room_name,
        'date': booking_date,
        'start_time': start_time,
        'end_time': end_time,
        'user_id': st.session_state.authenticated_user,
        'user_email': user_email,
        # แปลง datetime/time เป็น string เพื่อความง่ายในการจัดเก็บในฐานข้อมูล (Firestore)
        'date_str': booking_date.isoformat(),
        'start_time_str': start_time.isoformat(timespec='minutes'),
        'end_time_str': end_time.isoformat(timespec='minutes'),
    }

    if is_conflict(new_booking, current_bookings):
        st.error(f"❌ การจองขัดแย้ง! {room_name} ถูกจองแล้วในวันที่ {booking_date.strftime('%Y-%m-%d')} ระหว่าง {start_time.strftime('%H:%M')} ถึง {end_time.strftime('%H:%M')}.", icon="🚨")
    else:
        # บันทึกไปยัง 'DB' (Placeholder)
        save_booking_to_db(new_booking)
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
            st.rerun()
        return True
    
    # Login Form
    with st.sidebar.form(key='login_form'):
        username = st.text_input("ชื่อผู้ใช้ (Username)", key="login_username_input")
        password = st.text_input("รหัสผ่าน (Password)", type="password", key="login_password_input")
        
        login_button = st.form_submit_button("เข้าสู่ระบบ", use_container_width=True, type="primary")

        if login_button:
            if username in USERS_DB:
                stored_hash = USERS_DB[username]['hashed_password'].encode('utf-8')
                
                # ตรรกะ: เปรียบเทียบรหัสผ่านที่ป้อนกับ Hash ที่เก็บไว้
                # ในการใช้งานจริง: 
                # if bcrypt.checkpw(password.encode('utf-8'), stored_hash): 
                # (Placeholder เนื่องจากไม่สามารถติดตั้ง bcrypt ได้ในตัวอย่างนี้)
                
                # --- START: Mock Check for Demo (Remove this in production!) ---
                # เนื่องจากไม่สามารถใช้ bcrypt ได้ในสภาพแวดล้อมนี้, เราจะใช้การเปรียบเทียบข้อความธรรมดาชั่วคราว 
                # แต่โค้ดจริงจะต้องใช้ bcrypt.checkpw()
                if password in ["p123", "p456", "p789"]: # Temporary check for demo
                    st.session_state.authenticated_user = username
                    st.session_state.user_role = USERS_DB[username]['role'] 
                    st.success(f"ยินดีต้อนรับ, {username}!", icon="👋")
                    st.rerun()
                # --- END: Mock Check for Demo ---
                
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
    df_export['date'] = df_export.get('date_str', df_export['date']).astype(str)
    df_export['start_time'] = df_export.get('start_time_str', df_export['start_time']).astype(str)
    df_export['end_time'] = df_export.get('end_time_str', df_export['end_time']).astype(str)
    
    # ลบคอลัมน์ที่ไม่จำเป็นออกก่อน Export
    columns_to_keep = ['room', 'date', 'start_time', 'end_time', 'user_id', 'user_email']
    df_export = df_export[[col for col in columns_to_keep if col in df_export.columns]]

    df_export = df_export.rename(columns={
        'room': 'Room',
        'date': 'Date',
        'start_time': 'StartTime',
        'end_time': 'EndTime',
        'user_id': 'Username',
        'user_email': 'Email'
    })

    return df_export.to_csv(index=False).encode('utf-8')


def display_availability_matrix():
    """แสดงตารางสถานะห้องว่างแบบเรียลไทม์สำหรับวันที่เลือก"""
    st.subheader("🗓️ ปฏิทินสถานะห้องว่างแบบเรียลไทม์")
    
    view_date = st.date_input(
        "เลือกวันที่เพื่อดูสถานะห้องว่าง", 
        value=datetime.date.today(),
        key="view_date_select"
    )

    # 🛑 โหลดข้อมูลจาก DB (Cached)
    current_bookings = load_bookings_from_db()

    if not current_bookings:
        st.info(f"💡 ห้องทั้งหมดว่างในวันที่ {view_date.strftime('%Y-%m-%d')}.", icon="💡")
        return

    # ต้องแปลง String Date ที่โหลดมาจาก DB ให้เป็น datetime.date object 
    # สำหรับการเปรียบเทียบ (ในโค้ดจริง Firestore จะเก็บ Date/Time เป็น Timestamp)
    daily_bookings = []
    for b in current_bookings:
        booking_date = b.get('date') # ใช้ 'date' จาก New Booking หรือ 'date_str' จาก DB
        if isinstance(booking_date, str):
            booking_date = datetime.date.fromisoformat(booking_date)
            
        if booking_date == view_date:
            daily_bookings.append(b)


    # ตั้งค่าช่วงเวลา (Interval 30 นาทีสำหรับการแสดงผล)
    time_index = []
    start_hour = 8
    end_hour = 17
    
    for h in range(start_hour, end_hour):
        time_index.append(f"{h:02d}:00")
        time_index.append(f"{h:02d}:30")
    
    availability_df = pd.DataFrame(index=time_index, columns=list(ROOMS.keys())).fillna("✅ Available")
    
    # ประมวลผลการจองและทำเครื่องหมายสถานะ
    for booking in daily_bookings:
        room = booking['room']
        
        # ต้องจัดการ Time object ที่ถูกเก็บเป็น String เมื่อมาจาก DB
        book_start_time = booking.get('start_time')
        book_end_time = booking.get('end_time')
        if isinstance(book_start_time, str):
            book_start_time = datetime.time.fromisoformat(book_start_time)
        if isinstance(book_end_time, str):
            book_end_time = datetime.time.fromisoformat(book_end_time)
            
        book_start_dt = datetime.datetime.combine(view_date, book_start_time)
        book_end_dt = datetime.datetime.combine(view_date, book_end_time)
        
        for slot_time_str in time_index:
            slot_time = datetime.datetime.strptime(slot_time_str, "%H:%M").time()
            slot_dt = datetime.datetime.combine(view_date, slot_time)
            slot_end_dt = slot_dt + datetime.timedelta(minutes=30)

            # ตรวจสอบการทับซ้อน
            if slot_dt < book_end_dt and slot_end_dt > book_start_dt:
                availability_df.loc[slot_time_str, room] = f"❌ Booked by {booking['user_id']}"

    def color_cells(val):
        """กำหนดสีให้กับเซลล์ตามสถานะ"""
        if "Available" in str(val):
            return 'background-color: #d4edda; color: #155724' # สีเขียวอ่อน
        else:
            return 'background-color: #f8d7da; color: #721c24' # สีแดงอ่อน

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
    
    # 🛑 โหลดข้อมูลจาก DB (Cached)
    current_bookings = load_bookings_from_db()

    if not current_bookings:
        st.info("💡 ไม่มีห้องที่ถูกจองอยู่ในขณะนี้", icon="💡")
    else:
        bookings_df = pd.DataFrame(current_bookings)
        
        # จัดเรียงโดยใช้ 'date_str' และ 'start_time_str' ที่เป็น string
        bookings_df = bookings_df.sort_values(by=['date_str', 'start_time_str'], ascending=True)
        
        bookings_df_display = bookings_df.rename(columns={
            'room': 'ห้อง',
            'date_str': 'วันที่',
            'start_time_str': 'เวลาเริ่มต้น',
            'end_time_str': 'เวลาสิ้นสุด',
            'user_id': 'ชื่อผู้ใช้',
            'user_email': 'อีเมล'
        })
        
        # เลือกเฉพาะคอลัมน์ที่ต้องการแสดง
        st.dataframe(
            bookings_df_display[['ห้อง', 'วันที่', 'เวลาเริ่มต้น', 'เวลาสิ้นสุด', 'ชื่อผู้ใช้', 'อีเมล']], 
            use_container_width=True, 
            hide_index=True
        )

        # ฟังก์ชัน Export: แสดงเฉพาะผู้ดูแลระบบ (Admin)
        if st.session_state.user_role == 'admin':
            csv = convert_df_to_csv(bookings_df)
            st.download_button(
                label="⬇️ ส่งออกข้อมูลการจองทั้งหมดเป็น CSV (สำหรับ Admin เท่านั้น)",
                data=csv,
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
    st.info("💡 แอปพลิเคชันนี้ถูกปรับปรุงให้พร้อมเชื่อมต่อกับฐานข้อมูล Firestore และใช้ Hashing สำหรับรหัสผ่าน (โปรดอ่านคู่มือการตั้งค่า)")
    
    # เริ่มต้นสถานะและเชื่อมต่อ DB (Placeholder)
    initialize_state()
    
    # 1. การยืนยันตัวตน (อยู่ใน Sidebar)
    is_authenticated = authenticate_user()

    # 2. ส่วนเนื้อหาหลัก
    display_availability_matrix()
    st.markdown("---")

    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("📝 สร้างการจองใหม่")
        if is_authenticated:
            # ฟอร์มการจอง
            with st.form(key='booking_form', clear_on_submit=True):
                # แสดงข้อมูลผู้ใช้ปัจจุบัน
                current_user = st.session_state.authenticated_user
                current_email = USERS_DB[current_user]['email']
                st.info(f"ทำการจองในชื่อ: **{current_user}** ({current_email})")
                
                # รายละเอียดการจอง
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
                
                # ปุ่มยืนยัน
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

