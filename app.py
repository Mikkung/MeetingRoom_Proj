import streamlit as st
import datetime
import pandas as pd

# --- Configuration ---
ROOMS = {
    "ISE_Meeting_Room_I_305_Fl1": {"capacity": 8, "has_projector": True},
    "ISE_Meeting_Room_II_Fl2": {"capacity": 20, "has_projector": True},
    "ISE_Meeting_Room_III_304/1_Fl1": {"capacity": 20, "has_projector": False}
}
TIME_SLOTS = [
    "09:00 - 10:00", "10:00 - 11:00", "11:00 - 12:00", 
    "12:00 - 13:00", "13:00 - 14:00", "14:00 - 15:00",
    "15:00 - 16:00", "16:00 - 17:00"
]

# --- State Initialization ---
def initialize_state():
    """Initializes Streamlit session state variables."""
    if 'bookings' not in st.session_state:
        # Structure: [{'room': str, 'date': date, 'time_slot': str, 'user': str}]
        st.session_state.bookings = []
    
    if 'rooms' not in st.session_state:
        st.session_state.rooms = ROOMS

# --- Core Logic: Conflict Check ---
def is_conflict(new_booking):
    """
    Checks if a new booking conflicts with any existing booking.
    Conflict occurs if room, date, and time_slot all match.
    """
    new_room = new_booking['room']
    new_date = new_booking['date']
    new_time_slot = new_booking['time_slot']

    for booking in st.session_state.bookings:
        if (booking['room'] == new_room and
            booking['date'] == new_date and
            booking['time_slot'] == new_time_slot):
            return True
    return False

# --- Callback function for Form Submission ---
def handle_booking_submission(user_name, room_name, booking_date, time_slot):
    """Processes the form data and attempts to create a new booking."""
    
    # 1. Basic validation
    if not user_name:
        st.error("Please enter your name.", icon="⚠️")
        return

    new_booking = {
        'room': room_name,
        'date': booking_date,
        'time_slot': time_slot,
        'user': user_name,
    }

    # 2. Conflict Check
    if is_conflict(new_booking):
        st.error(f"❌ Booking conflict! {room_name} is already booked on {booking_date.strftime('%Y-%m-%d')} for the slot {time_slot}.", icon="🚨")
    else:
        # 3. Add booking
        st.session_state.bookings.append(new_booking)
        st.success(f"✅ Success! {room_name} booked by {user_name} for {booking_date.strftime('%Y-%m-%d')} at {time_slot}.", icon="🎉")
        
        # Manually rerun to clear form inputs if using direct st.session_state keys
        # For simplicity, we rely on the form clearing itself unless explicitly keyed

# --- UI Functions ---

def display_rooms_and_bookings():
    """Displays the list of rooms and the current bookings."""
    
    # 1. Room Information
    st.subheader("🏢 Available Meeting Rooms")
    
    rooms_df = pd.DataFrame([
        {
            "Room Name": name, 
            "Capacity": info["capacity"], 
            "Projector": "✅ Yes" if info["has_projector"] else "❌ No"
        } 
        for name, info in st.session_state.rooms.items()
    ])
    st.dataframe(
        rooms_df, 
        use_container_width=True, 
        hide_index=True,
        column_config={
            "Capacity": st.column_config.NumberColumn(format="%d pax"),
        }
    )

    # 2. Current Bookings
    st.subheader("📅 Current Bookings")
    
    if not st.session_state.bookings:
        st.info("No rooms are currently booked.", icon="💡")
    else:
        # Prepare data for display
        bookings_df = pd.DataFrame(st.session_state.bookings)
        bookings_df['date'] = bookings_df['date'].astype(str)
        
        # Sort by date and then time slot
        bookings_df = bookings_df.sort_values(by=['date', 'time_slot'], ascending=True)
        
        # Rename columns for a nicer display
        bookings_df = bookings_df.rename(columns={
            'room': 'Room',
            'date': 'Date',
            'time_slot': 'Time Slot',
            'user': 'Booked By'
        })
        
        st.dataframe(bookings_df, use_container_width=True, hide_index=True)


def display_booking_form():
    """Displays the form for making a new booking."""
    st.subheader("➕ Make a New Booking")

    with st.form(key='booking_form', clear_on_submit=True):
        
        # User details
        user_name = st.text_input("Your Name", key="user_name_input")
        
        # Booking details
        cols = st.columns(2)
        
        with cols[0]:
            room_name = st.selectbox(
                "Select Room", 
                options=list(st.session_state.rooms.keys()),
                key="room_select"
            )

        with cols[1]:
            booking_date = st.date_input(
                "Date", 
                value=datetime.date.today(),
                min_value=datetime.date.today(),
                key="date_select"
            )
            
        time_slot = st.selectbox(
            "Select Time Slot (1 hour)", 
            options=TIME_SLOTS,
            key="time_slot_select"
        )
        
        # Submit button
        submit_button = st.form_submit_button(
            label='Book Room',
            use_container_width=True,
            on_click=handle_booking_submission,
            # Arguments passed to the callback function
            args=(user_name, room_name, booking_date, time_slot)
        )


# --- Main Application Layout ---
def main():
    """The main function to run the Streamlit application."""
    st.set_page_config(
        page_title="Meeting Room Booking",
        page_icon="📅",
        layout="wide",
        initial_sidebar_state="auto"
    )

    st.title("Meeting Room Scheduler 🚀")
    
    # Initialize state on first run
    initialize_state()

    # Layout: Sidebar for quick actions, Main column for display/form
    col1, col2 = st.columns([1, 2])
    
    with col1:
        # Booking Form
        display_booking_form()

    with col2:
        # Display Rooms and Bookings
        display_rooms_and_bookings()


if __name__ == "__main__":

    main()
