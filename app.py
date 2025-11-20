import streamlit as st
import datetime
import pandas as pd
from io import BytesIO

# --- Configuration ---
ROOMS = {
    "ISE_Meeting_Room_I_305_Fl1": {"capacity": 8, "has_projector": True},
    "ISE_Meeting_Room_II_Fl2": {"capacity": 20, "has_projector": True},
    "ISE_Meeting_Room_III_304/1_Fl1": {"capacity": 20, "has_projector": False}
}

# Define authorized users for simple authentication (replace with real database/auth system for production)
AUTHORIZED_USERS = ["thanaphon.a@chula.ac.th", "jane.smith", "admin.user", "user@ise.com"] 

# --- State Initialization ---
def initialize_state():
    """Initializes Streamlit session state variables."""
    if 'bookings' not in st.session_state:
        # Structure: [{'room': str, 'date': date, 'start_time': time, 'end_time': time, 'user': str}]
        st.session_state.bookings = []
    
    if 'rooms' not in st.session_state:
        st.session_state.rooms = ROOMS
        
    if 'authenticated_user' not in st.session_state:
        st.session_state.authenticated_user = None

# --- Core Logic: Conflict Check (Updated for flexible time) ---
def is_time_overlap(start1, end1, start2, end2):
    """
    Checks if two time ranges overlap.
    A conflict occurs if (Start1 < End2) AND (End1 > Start2).
    We use strict inequality for overlapping ranges, meaning a booking ending at 10:00 
    and a new one starting at 10:00 do NOT conflict.
    """
    return start1 < end2 and end1 > start2

def is_conflict(new_booking):
    """Checks if a new booking conflicts with any existing booking."""
    new_room = new_booking['room']
    new_date = new_booking['date']
    new_start = new_booking['start_time']
    new_end = new_booking['end_time']

    for booking in st.session_state.bookings:
        # 1. Check if the room and date match
        if booking['room'] == new_room and booking['date'] == new_date:
            
            # 2. Check for time overlap
            existing_start = booking['start_time']
            existing_end = booking['end_time']
            
            if is_time_overlap(new_start, new_end, existing_start, existing_end):
                return True
    return False

# --- Callback function for Form Submission ---
def handle_booking_submission(user_name, room_name, booking_date, start_time, end_time):
    """Processes the form data and attempts to create a new booking."""
    
    # Check if user is authenticated (should be handled by form, but good for security)
    if st.session_state.authenticated_user is None:
        st.error("Authentication required to submit a booking.", icon="🔒")
        return
        
    # 1. Basic time validation
    if start_time >= end_time:
        st.error("❌ The start time must be before the end time.", icon="⚠️")
        return
        
    # 2. Create the new booking object
    new_booking = {
        'room': room_name,
        'date': booking_date,
        'start_time': start_time,
        'end_time': end_time,
        'user': st.session_state.authenticated_user, # Use the verified username
    }

    # 3. Conflict Check
    if is_conflict(new_booking):
        st.error(f"❌ Booking conflict! {room_name} is already booked on {booking_date.strftime('%Y-%m-%d')} between {start_time.strftime('%H:%M')} and {end_time.strftime('%H:%M')}.", icon="🚨")
    else:
        # 4. Add booking and success message
        st.session_state.bookings.append(new_booking)
        st.success(f"✅ Success! {room_name} booked by {st.session_state.authenticated_user} for {booking_date.strftime('%Y-%m-%d')} from {start_time.strftime('%H:%M')} to {end_time.strftime('%H:%M')}.", icon="🎉")


# --- UI Components ---

def authenticate_user():
    """Handles the user login/authentication process."""
    st.sidebar.subheader("🔒 User Authorization")
    
    if st.session_state.authenticated_user:
        st.sidebar.success(f"Logged in as: **{st.session_state.authenticated_user}**")
        if st.sidebar.button("Logout", key="logout_btn", use_container_width=True):
            st.session_state.authenticated_user = None
            st.rerun()
        return True
    
    with st.sidebar.form(key='login_form'):
        username_input = st.text_input("Enter your authorized username/email", key="auth_user_input")
        login_button = st.form_submit_button("Log In", use_container_width=True, type="primary")

        if login_button:
            if username_input.lower() in [u.lower() for u in AUTHORIZED_USERS]:
                st.session_state.authenticated_user = username_input
                st.success(f"Welcome, {username_input}!", icon="👋")
                st.rerun()
            else:
                st.error("Access Denied. Your username is not in the authorized list.", icon="⛔")
    return False

@st.cache_data
def convert_df_to_csv(df):
    """Converts a Pandas DataFrame to a CSV for download."""
    # Convert time and date objects to strings for clean export
    df_export = df.copy()
    df_export['date'] = df_export['date'].astype(str)
    df_export['start_time'] = df_export['start_time'].astype(str)
    df_export['end_time'] = df_export['end_time'].astype(str)
    
    return df_export.to_csv(index=False).encode('utf-8')


def display_availability_matrix():
    """Displays a visual matrix of room availability for a selected day."""
    st.subheader("🗓️ Real-Time Availability Calendar")
    
    # 1. Date Selector
    view_date = st.date_input(
        "Select Date to View Availability", 
        value=datetime.date.today(),
        key="view_date_select"
    )

    if not st.session_state.bookings:
        st.info(f"All rooms are available on {view_date.strftime('%Y-%m-%d')}.")
        return

    # Filter bookings for the selected day
    daily_bookings = [
        b for b in st.session_state.bookings if b['date'] == view_date
    ]

    # 2. Setup Time Slots (30-minute intervals for visualization)
    time_index = []
    start_hour = 8 # Start visualization at 8:00
    end_hour = 17 # End visualization at 17:00 (5 PM)
    
    for h in range(start_hour, end_hour):
        time_index.append(f"{h:02d}:00")
        time_index.append(f"{h:02d}:30")
    
    # 3. Create Availability DataFrame
    availability_df = pd.DataFrame(index=time_index, columns=list(ROOMS.keys())).fillna("✅ Available")
    
    # Populate the DataFrame with booking info
    for booking in daily_bookings:
        room = booking['room']
        
        # Convert time objects to minutes since midnight for easy comparison
        book_start_dt = datetime.datetime.combine(view_date, booking['start_time'])
        book_end_dt = datetime.datetime.combine(view_date, booking['end_time'])
        
        # Iterate through the 30-minute slots in the index
        for slot_time_str in time_index:
            slot_time = datetime.datetime.strptime(slot_time_str, "%H:%M").time()
            slot_dt = datetime.datetime.combine(view_date, slot_time)
            
            # Define the 30-minute window for the slot
            slot_end_dt = slot_dt + datetime.timedelta(minutes=30)

            # Check for conflict in this slot: Slot starts before booking ends AND Slot ends after booking starts
            if slot_dt < book_end_dt and slot_end_dt > book_start_dt:
                availability_df.loc[slot_time_str, room] = f"❌ Booked by {booking['user']}"

    # 4. Styling and Display
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
    """Displays the list of rooms and the current bookings with an export button."""
    
    # 1. Room Information
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

    # 2. Current Bookings and Export
    st.subheader("📚 All Current Bookings")
    
    if not st.session_state.bookings:
        st.info("No rooms are currently booked.", icon="💡")
    else:
        bookings_df = pd.DataFrame(st.session_state.bookings)
        
        # Sort data for better readability
        bookings_df = bookings_df.sort_values(by=['date', 'start_time'], ascending=True)
        
        # Rename columns for display
        bookings_df_display = bookings_df.rename(columns={
            'room': 'Room',
            'date': 'Date',
            'start_time': 'Start Time',
            'end_time': 'End Time',
            'user': 'Booked By'
        })
        
        st.dataframe(bookings_df_display, use_container_width=True, hide_index=True)

        # Export Functionality
        csv = convert_df_to_csv(bookings_df)
        st.download_button(
            label="⬇️ Export All Bookings to CSV",
            data=csv,
            file_name=f'meeting_room_bookings_{datetime.date.today()}.csv',
            mime='text/csv',
            type="secondary",
            use_container_width=True
        )


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
    
    # First section: Availability Matrix
    display_availability_matrix()
    st.markdown("---")


    # Second section: Booking Form (only for authenticated users) and Data Display
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("📝 New Booking Request")
        if is_authenticated:
            # Booking Form
            with st.form(key='booking_form', clear_on_submit=True):
                # User is pre-filled/known from authentication
                st.write(f"Booking as: **{st.session_state.authenticated_user}**")
                
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
                submit_button = st.form_submit_button(
                    label='Confirm Booking',
                    use_container_width=True,
                    type="primary",
                    on_click=handle_booking_submission,
                    # Arguments passed to the callback function
                    args=(st.session_state.authenticated_user, room_name, booking_date, start_time, end_time)
                )
        else:
            st.warning("Please log in on the sidebar to make a new booking.", icon="👉")

    with col2:
        # Display Rooms Specs and all Bookings with Export button
        display_data_and_export()


if __name__ == "__main__":
    main()
