import streamlit as st
import datetime
import pandas as pd
from io import BytesIO

# --- Configuration ---

# 1. Mock User Database with Roles (!!! คำเตือน: ตอนนี้เก็บรหัสผ่านเป็นข้อความธรรมดา - ไม่ปลอดภัย !!!)
# Test Credentials (Username / Password / Role):
# - john.doe / p123 / user
# - jane.smith / p456 / user
# - admin.user / p789 / admin
USERS_DB = {
    "john.doe": {
        "email": "john.doe@ise.com",
        "password": "p123", # <--- รหัสผ่านถูกเก็บเป็นข้อความธรรมดา
        "role": "user" 
    },
    "jane.smith": {
        "email": "jane.smith@ise.com",
        "password": "p456", # <--- รหัสผ่านถูกเก็บเป็นข้อความธรรมดา
        "role": "user"
    },
    "admin.user": {
        "email": "admin@ise.com",
        "password": "p789", # <--- รหัสผ่านถูกเก็บเป็นข้อความธรรมดา
        "role": "admin" 
    }
}

# 2. Room Configuration
ROOMS = {
    "ISE_Meeting_Room_I_305_Fl1": {"capacity": 8, "has_projector": True},
    "ISE_Meeting_Room_II_Fl2": {"capacity": 20, "has_projector": True},
    "ISE_Meeting_Room_III_304/1_Fl1": {"capacity": 20, "has_projector": False}
}

# --- State Management and Conflict Check ---

def initialize_state():
    """เริ่มต้นตัวแปร Session State ของ Streamlit"""
    if 'bookings' not in st.session_state:
        st.session_state.bookings = []
    
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

def is_conflict(new_booking):
    """ตรวจสอบว่าการจองใหม่ขัดแย้งกับการจองที่มีอยู่หรือไม่"""
    new_room = new_booking['room']
    new_date = new_booking['date']
    new_start = new_booking['start_time']
    new_end = new_booking['end_time']

    for booking in st.session_state.bookings:
        if booking['room'] == new_room and booking['date'] == new_date:
            existing_start = booking['start_time']
            existing_end = booking['end_time']
            
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
        
    new_booking = {
        'room': room_name,
        'date': booking_date,
        'start_time': start_time,
        'end_time': end_time,
        'user_id': st.session_state.authenticated_user,
        'user_email': user_email,
    }

    if is_conflict(new_booking):
        st.error(f"❌ การจองขัดแย้ง! {room_name} ถูกจองแล้วในวันที่ {booking_date.strftime('%Y-%m-%d')} ระหว่าง {start_time.strftime('%H:%M')} ถึง {end_time.strftime('%H:%M')}.", icon="🚨")
    else:
        st.session_state.bookings.append(new_booking)
        st.success(f"✅ สำเร็จ! {room_name} ถูกจองโดย {st.session_state.authenticated_user} สำหรับวันที่ {booking_date.strftime('%Y-%m-%d')} ตั้งแต่ {start_time.strftime('%H:%M')} ถึง {end_time.strftime('%H:%M')}.", icon="🎉")

# --- UI Components: Authentication ---

def authenticate_user():
    """จัดการกระบวนการล็อกอิน/ยืนยันตัวตนของผู้ใช้ด้วย username และ password"""
    st.sidebar.subheader("🔒 เข้าสู่ระบบ")
    
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
                # ตรรกะที่ไม่ปลอดภัย: เปรียบเทียบรหัสผ่านแบบข้อความธรรมดาโดยตรง
                if password == USERS_DB[username]['password']: 
                    st.session_state.authenticated_user = username
                    st.session_state.user_role = USERS_DB[username]['role'] 
                    st.success(f"ยินดีต้อนรับ, {username}!", icon="👋")
                    st.rerun()
                # ------------------------------------------------------------------
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
    df_export['date'] = df_export['date'].astype(str)
    df_export['start_time'] = df_export['start_time'].astype(str)
    df_export['end_time'] = df_export['end_time'].astype(str)
    
    df_export = df_export.rename(columns={
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

    if not st.session_state.bookings:
        st.info(f"💡 ห้องทั้งหมดว่างในวันที่ {view_date.strftime('%Y-%m-%d')}.", icon="💡")
        return

    daily_bookings = [
        b for b in st.session_state.bookings if b['date'] == view_date
    ]

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
        
        book_start_dt = datetime.datetime.combine(view_date, booking['start_time'])
        book_end_dt = datetime.datetime.combine(view_date, booking['end_time'])
        
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
    
    if not st.session_state.bookings:
        st.info("💡 ไม่มีห้องที่ถูกจองอยู่ในขณะนี้", icon="💡")
    else:
        bookings_df = pd.DataFrame(st.session_state.bookings)
        bookings_df = bookings_df.sort_values(by=['date', 'start_time'], ascending=True)
        
        bookings_df_display = bookings_df.rename(columns={
            'room': 'ห้อง',
            'date': 'วันที่',
            'start_time': 'เวลาเริ่มต้น',
            'end_time': 'เวลาสิ้นสุด',
            'user_id': 'ชื่อผู้ใช้',
            'user_email': 'อีเมล'
        })
        
        st.dataframe(bookings_df_display, use_container_width=True, hide_index=True)

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
        page_title="ISE Meeting Room Scheduler",
        page_icon="📅",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.title("ISE Meeting Room Scheduler 🏢")
    
    # เริ่มต้นสถานะ
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
                        step=600, # 10 minute step for flexibility
                        key="start_time_input"
                    )
                with cols_time[1]:
                    end_time = st.time_input(
                        "4. เวลาสิ้นสุด",
                        value=datetime.time(10, 0),
                        step=600, # 10 minute step for flexibility
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
