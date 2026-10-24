"""Tests for seat selection, booking flow, pricing, collision prevention, and venue guards."""
import json
from app.services import booking_service


def test_seat_selection_page_loads(client):
    """Verify seat selection view renders screen and seating grid for Kolhapur show."""
    response = client.get("/book/seats/mov-south-1?theater_id=th-pvr-dyp&showtime=10:30%20AM")
    assert response.status_code == 200
    assert b"CINEMATIC SCREEN" in response.data
    assert b"Booking Summary" in response.data
    assert b"PVR DYP City Mall" in response.data


def test_unverified_theater_booking_rejected(client):
    """Attempting to select seats or book at an unverified theatre redirects with warning."""
    response = client.get(
        "/book/seats/mov-south-1?theater_id=th-padma&showtime=10:30%20AM",
        follow_redirects=False,
    )
    # Redirects back to movie detail
    assert response.status_code == 302
    assert "/movies/mov-south-1" in response.headers["Location"]


def test_seat_booking_price_calculation():
    """Verify tiered seat pricing calculation in INR."""
    # Row A (VIP) = ₹320.00
    price_vip, tier_vip = booking_service.calculate_total(["A1"])
    assert price_vip == 320.00
    assert "VIP" in tier_vip

    # Row D (Gold) = ₹220.00
    price_gold, tier_gold = booking_service.calculate_total(["D1"])
    assert price_gold == 220.00
    assert "Gold" in tier_gold

    # Row G (Silver) = ₹160.00
    price_silver, tier_silver = booking_service.calculate_total(["G1"])
    assert price_silver == 160.00
    assert "Silver" in tier_silver

    # Multiple seats: A1 (₹320) + G1 (₹160) = ₹480.00
    price_combo, tier_combo = booking_service.calculate_total(["A1", "G1"])
    assert price_combo == 480.00


def test_unauthenticated_user_redirected_on_booking(client):
    """Anonymous user attempting to submit booking is redirected to login."""
    response = client.post(
        "/book/confirm",
        data={
            "movie_id": "mov-south-1",
            "theater_id": "th-pvr-dyp",
            "showtime": "10:30 AM",
            "show_date": "Today",
            "selected_seats": json.dumps(["F1", "F2"]),
        },
        follow_redirects=False,
    )
    # Redirects to login
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_authenticated_user_booking_flow(auth_client):
    """Logged in user can successfully complete a booking."""
    response = auth_client.post(
        "/book/confirm",
        data={
            "movie_id": "mov-south-1",
            "theater_id": "th-pvr-dyp",
            "showtime": "10:30 AM",
            "show_date": "Today",
            "selected_seats": json.dumps(["B1", "B2"]),
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"RESERVATION CONFIRMED" in response.data
    assert b"B1" in response.data
    assert b"B2" in response.data

    # Verify simulated QR code disclaimer and non-scannable demo caption
    html = response.data.decode("utf-8")
    assert "Demo QR — not scannable" in html
    assert "Decorative graphic only" in html
    assert "Not a valid ticket barcode" in html
    assert "Scan at Turnstile" not in html


def test_duplicate_seat_booking_prevention(auth_client):
    """Attempting to book an already occupied seat should be rejected."""
    # First booking: reserve H8
    success1, _, _ = booking_service.create_booking(
        user_id="usr-demo-1",
        user_email="demo@moviemagic.com",
        movie_id="mov-south-1",
        theater_id="th-pvr-dyp",
        showtime="10:30 AM",
        show_date="Today",
        seats=["H8"],
    )
    assert success1 is True

    # Second booking attempting the same seat H8: should fail
    success2, msg, _ = booking_service.create_booking(
        user_id="usr-demo-1",
        user_email="demo@moviemagic.com",
        movie_id="mov-south-1",
        theater_id="th-pvr-dyp",
        showtime="10:30 AM",
        show_date="Today",
        seats=["H8"],
    )
    assert success2 is False
    assert "already been reserved" in msg


def test_booking_history_page(auth_client):
    """Verify user booking history page displays bookings."""
    response = auth_client.get("/bookings/history")
    assert response.status_code == 200
    assert b"My Booking History" in response.data
    assert b"CONFIRMED" in response.data
