import streamlit as st
import datetime
import pandas as pd
import hashlib
from io import BytesIO

# --- Configuration ---

# 1. Mock User Database with Roles (In a real application, this would be a secure database query)
# Test Credentials (Username / Password / Role):
# - john.doe / p123 / user
# - jane.smith / p456 / user
# - admin.user / p789 / admin
USERS_DB = {
    "Mikkung": {
        "email": "thanaphon.a@chula.ac.th",
        "hashed_password": "mikkyja", # hash of "p123"
        "role": "admin" 
    },
    "jane.smith": {
        "email": "jane.smith@ise.com",
        "hashed_password": "e7228a8d1163462f4e8b34c26a578a05f01dd531853d858348af7dd4c4a45a6c", # hash of "p456"
        "role": "user"
    },
    "admin.user": {
        "email": "admin@ise.com",
        "hashed_password": "95a5f78233f811568478d6b8c4c7c59573887c2b3c220265275817d23f309d94", # hash of "p789"
        "role": "admin" # <-- ONLY ADMIN CAN EXPORT STATS
    }
}

# 2. Room Configuration
ROOMS = {
    "ISE_Meeting_Room_I_305_Fl1": {"capacity": 8, "has_projector": True},
    "ISE_Meeting_Room_II_Fl2": {"capacity": 20, "has_projector": True},
    "ISE_Meeting_Room_III_304/1_Fl1": {"capacity": 20, "has_projector": False}
}

# --- Utility Functions ---

def hash_password(password):
    """Generates a SHA256 hash of the input password."""
    return hashlib.sha256(password.encode()).hexdigest()

# --- State Management and Conflict Check ---

def initialize_state():
    """Initializes Streamlit session state variables."""
    if 'bookings' not in st.session_state:
        st.session_state.bookings = []
    
    if 'rooms' not in st.session_state:
        st.session_state.rooms = ROOMS
        
    if 'authenticated_user' not in st.session_state:
        st.session_state.authenticated_user = None
    
    if 'user_role' not in st.session_state:
        st.session_state.user_role = None

def is_time_overlap(start1, end1, start2, end2):
    """Checks if two time ranges overlap. Times are datetime.time objects."""
    # Convert to seconds since midnight for robust comparison
    def time_to_seconds(t):
        # Handle cases where t might be None if widget is empty, though st.time_input prevents this
        if t is None: return -1 
        return t.hour * 3600 + t.minute * 60 + t.second
    
    s1, e1 = time_to_seconds(start1), time_to_seconds(end1)
    s2, e2 = time_to_seconds(start2), time_to_seconds(end2)
    
    # Non-overlap condition: (End1 <= Start2) OR (Start1 >= End2)
    # Overlap is the negation: NOT ((End1 <= Start2) OR (Start1 >= End2))
    return not (e1 <= s2 or s1 >= e2)

def is_conflict(new_booking):
    """Checks if a new booking conflicts with any existing booking."""
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
    """Processes the form data and attempts to create a new booking."""
    
    if st.session_state.authenticated_user is None:
        st.error("Authentication required to submit a booking.", icon="🔒")
        return
        
    if start_time >= end_time:
        st.error("❌ The start time must be before the end time.", icon="⚠️")
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
        st.error(f"❌ Booking conflict! {room_name} is already booked on {booking_date.strftime('%Y-%m-%d')} between {start_time.strftime('%H:%M')} and {end_time.strftime('%H:%M')}.", icon="🚨")
    else:
        st.session_state.bookings.append(new_booking)
        st.success(f"✅ Success! {room_name} booked by {st.session_state.authenticated_user} for {booking_date.strftime('%Y-%m-%d')} from {start_time.strftime('%H:%M')} to {end_time.strftime('%H:%M')}.", icon="🎉")

# --- UI Components: Authentication ---

def authenticate_user():
    """Handles the user login/authentication process using username and password."""
    st.sidebar.subheader("🔒 User Login")
    
    if st.session_state.authenticated_user:
        role = st.session_state.user_role.upper()
        st.sidebar.success(f"Logged in as: **{st.session_state.authenticated_user}** ({role})")
        if st.sidebar.button("Logout", key="logout_btn", use_container_width=True):
            st.session_state.authenticated_user = None
            st.session_state.user_role = None
            st.rerun()
        return True
    
    # Login Form
    with st.sidebar.form(key='login_form'):
        username = st.text_input("Username", key="login_username_input")
        password = st.text_input("Password", type="password", key="login_password_input")
        
        login_button = st.form_submit_button("Log In", use_container_width=True, type="primary")

        if login_button:
            if username in USERS_DB:
                entered_hash = hash_password(password)
                
                if entered_hash == USERS_DB[username]['hashed_password']:
                    st.session_state.authenticated_user = username
                    st.session_state.user_role = USERS_DB[username]['role'] # <-- Store Role
                    st.success(f"Welcome back, {username}!", icon="👋")
                    st.rerun()
                else:
                    st.error("Invalid password.", icon="⛔")
            else:
                st.error("Invalid username. Please check your credentials.", icon="⛔")
    return False

# --- UI Components: Data Export and Availability ---

@st.cache_data
def convert_df_to_csv(df):
    """Converts a Pandas DataFrame to a CSV for download."""
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
    """Displays a visual matrix of room availability for a selected day."""
    st.subheader("🗓️ Real-Time Availability Calendar")
    
    view_date = st.date_input(
        "Select Date to View Availability", 
        value=datetime.date.today(),
        key="view_date_select"
    )

    if not st.session_state.bookings:
        st.info(f"All rooms are available on {view_date.strftime('%Y-%m-%d')}.", icon="💡")
        return

    daily_bookings = [
        b for b in st.session_state.bookings if b['date'] == view_date
    ]

    # Setup Time Slots (30-minute intervals for visualization)
    time_index = []
    start_hour = 8
    end_hour = 17
    
    for h in range(start_hour, end_hour):
        time_index.append(f"{h:02d}:00")
        time_index.append(f"{h:02d}:30")
    
    availability_df = pd.DataFrame(index=time_index, columns=list(ROOMS.keys())).fillna("✅ Available")
    
    # Process bookings and mark availability
    for booking in daily_bookings:
        room = booking['room']
        
        # We combine date and time to create datetime objects for boundary checks
        book_start_dt = datetime.datetime.combine(view_date, booking['start_time'])
        book_end_dt = datetime.datetime.combine(view_date, booking['end_time'])
        
        for slot_time_str in time_index:
            slot_time = datetime.datetime.strptime(slot_time_str, "%H:%M").time()
            slot_dt = datetime.datetime.combine(view_date, slot_time)
            slot_end_dt = slot_dt + datetime.timedelta(minutes=30)

            # Check for conflict: Slot starts before booking ends AND Slot ends after booking starts
            if slot_dt < book_end_dt and slot_end_dt > book_start_dt:
                availability_df.loc[slot_time_str, room] = f"❌ Booked by {booking['user_id']}"

    def color_cells(val):
        """Color code for the availability table."""
        if "Available" in str(val):
            return 'background-color: #d4edda; color: #155724' # Light green
        else:
            return 'background-color: #f8d7da; color: #721c24' # Light red

    st.dataframe(
        availability_df.style.applymap(color_cells), 
        use_container_width=True,
        column_config={
            col: st.column_config.TextColumn(col, width="small")
            for col in availability_df.columns
        }
    )

def display_data_and_export():
    """Displays the list of rooms and the current bookings with a role-based export button."""
    
    st.subheader("🏢 Meeting Room Specs")
    
    rooms_df = pd.DataFrame([
        {
            "Room Name": name, 
            "Capacity": info["capacity"], 
            "Projector": "✅ Yes" if info["has_projector"] else "❌ No"
        } 
        for name, info in st.session_state.rooms.items()
    ])
    st.dataframe(rooms_df, use_container_width=True, hide_index=True)

    st.subheader("📚 All Current Bookings")
    
    if not st.session_state.bookings:
        st.info("No rooms are currently booked.", icon="💡")
    else:
        bookings_df = pd.DataFrame(st.session_state.bookings)
        bookings_df = bookings_df.sort_values(by=['date', 'start_time'], ascending=True)
        
        bookings_df_display = bookings_df.rename(columns={
            'room': 'Room',
            'date': 'Date',
            'start_time': 'Start Time',
            'end_time': 'End Time',
            'user_id': 'Username',
            'user_email': 'Email'
        })
        
        st.dataframe(bookings_df_display, use_container_width=True, hide_index=True)

        # Export Functionality: Only show to admins
        if st.session_state.user_role == 'admin':
            csv = convert_df_to_csv(bookings_df)
            st.download_button(
                label="⬇️ Export All Bookings to CSV (Admin Only)",
                data=csv,
                file_name=f'meeting_room_bookings_{datetime.date.today()}.csv',
                mime='text/csv',
                type="primary",
                use_container_width=True
            )
        elif st.session_state.authenticated_user:
            st.info("You must be an admin to export the full booking statistics.")
        else:
            st.info("Log in to view booking data and potential admin export options.")


# --- Main Application Layout ---
def main():
    """The main function to run the Streamlit application."""
    st.set_page_config(
        page_title="ISE Meeting Room Scheduler",
        page_icon="📅",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    st.title("ISE Meeting Room Scheduler 🏢")
    
    # Initialize state on first run
    initialize_state()
    
    # 1. Authentication happens in the sidebar
    is_authenticated = authenticate_user()

    # 2. Main Content Layout
    display_availability_matrix()
    st.markdown("---")

    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("📝 New Booking Request")
        if is_authenticated:
            # Booking Form
            with st.form(key='booking_form', clear_on_submit=True):
                # Display current user info
                current_user = st.session_state.authenticated_user
                current_email = USERS_DB[current_user]['email']
                st.info(f"Booking as: **{current_user}** ({current_email})")
                
                # Booking details
                room_name = st.selectbox(
                    "1. Select Room", 
                    options=list(st.session_state.rooms.keys()),
                    key="room_select"
                )

                booking_date = st.date_input(
                    "2. Date", 
                    value=datetime.date.today(),
                    min_value=datetime.date.today(),
                    key="date_select"
                )
                    
                cols_time = st.columns(2)
                with cols_time[0]:
                    start_time = st.time_input(
                        "3. Start Time",
                        value=datetime.time(9, 0),
                        step=600, # 10 minute step for flexibility
                        key="start_time_input"
                    )
                with cols_time[1]:
                    end_time = st.time_input(
                        "4. End Time",
                        value=datetime.time(10, 0),
                        step=600, # 10 minute step for flexibility
                        key="end_time_input"
                    )
                
                # Submit button
                st.form_submit_button(
                    label='Confirm Booking',
                    use_container_width=True,
                    type="primary",
                    on_click=handle_booking_submission,
                    args=(room_name, booking_date, start_time, end_time)
                )
        else:
            st.warning("Please log in on the sidebar to access the booking form.", icon="👉")

    with col2:
        display_data_and_export()


if __name__ == "__main__":
    main()

