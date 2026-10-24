"""Booking Blueprint: Seat selection, reservation checkout, and history."""
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from app.forms import BookingSubmissionForm
from app.services import booking_service, movie_service
from app.utils.decorators import login_required

booking_bp = Blueprint("booking", __name__)


@booking_bp.route("/book/seats/<movie_id>", methods=["GET"])
def select_seats(movie_id):
    """Cinematic seat selection layout with screen, tiers, and interactive seating grid."""
    movie = movie_service.get_movie_by_id(movie_id)
    if not movie:
        abort(404)

    theater_id = request.args.get("theater_id", "th-pvr-dyp")
    showtime = request.args.get("showtime", "10:30 AM")
    show_date = request.args.get("date", "Today")

    theater = movie_service.get_theater_by_id(theater_id)
    if not theater:
        theater = {
            "id": theater_id,
            "name": "PVR DYP City Mall",
            "city": "Kolhapur",
            "operational_status": "Operational",
            "is_verified": True,
        }

    # Guard: prevent reservations for unverified or non-operational venues
    if theater.get("operational_status") != "Operational" or not theater.get("is_verified", True):
        flash(
            f"'{theater.get('name')}' is currently unverified or not active for online ticket reservations.",
            "warning",
        )
        return redirect(url_for("main.movie_detail", movie_id=movie_id))

    # Identify if the requested showtime is verified or a demo schedule
    matching_shows = movie_service.get_showtimes(movie_id=movie_id, theater_id=theater_id)
    active_show = next((s for s in matching_shows if s.get("time") == showtime), None)
    is_demo_showtime = True if (not active_show or not active_show.get("is_verified")) else False

    seat_layout = booking_service.get_seat_layout(movie_id, theater_id, showtime)

    form = BookingSubmissionForm(
        movie_id=movie_id,
        theater_id=theater_id,
        showtime=showtime,
        show_date=show_date,
    )

    return render_template(
        "booking/select_seats.html",
        movie=movie,
        theater=theater,
        showtime=showtime,
        show_date=show_date,
        seat_layout=seat_layout,
        is_demo_showtime=is_demo_showtime,
        active_show=active_show,
        form=form,
    )


@booking_bp.route("/book/confirm", methods=["POST"])
@login_required
def confirm_booking():
    """Process ticket booking submission with CSRF validation."""
    form = BookingSubmissionForm()

    if not form.validate_on_submit():
        flash("Invalid booking request. Please select your seats again.", "danger")
        movie_id = request.form.get("movie_id")
        return redirect(url_for("booking.select_seats", movie_id=movie_id))

    movie_id = form.movie_id.data
    theater_id = form.theater_id.data
    showtime = form.showtime.data
    show_date = form.show_date.data
    raw_seats = form.selected_seats.data

    # Guard against unverified or closed theaters on submission
    theater = movie_service.get_theater_by_id(theater_id)
    if theater and (theater.get("operational_status") != "Operational" or not theater.get("is_verified", True)):
        flash(f"Bookings cannot be processed for unverified or closed venue '{theater.get('name')}'.", "danger")
        return redirect(url_for("main.movie_detail", movie_id=movie_id))

    try:
        if raw_seats.startswith("["):
            selected_seats = json.loads(raw_seats)
        else:
            selected_seats = [s.strip() for s in raw_seats.split(",") if s.strip()]
    except Exception:
        selected_seats = [s.strip() for s in raw_seats.split(",") if s.strip()]

    if not selected_seats:
        flash("Please select at least one seat to book.", "warning")
        return redirect(url_for("booking.select_seats", movie_id=movie_id, theater_id=theater_id, showtime=showtime))

    success, message, booking = booking_service.create_booking(
        user_id=session["user_id"],
        user_email=session["user_email"],
        movie_id=movie_id,
        theater_id=theater_id,
        showtime=showtime,
        show_date=show_date,
        seats=selected_seats,
    )

    if not success or not booking:
        flash(message, "danger")
        return redirect(url_for("booking.select_seats", movie_id=movie_id, theater_id=theater_id, showtime=showtime))

    flash("Booking successful! Your simulated e-ticket has been generated.", "success")
    return redirect(url_for("booking.booking_confirmation", booking_id=booking["id"]))


@booking_bp.route("/book/confirmation/<booking_id>", methods=["GET"])
def booking_confirmation(booking_id):
    """Booking confirmation and e-ticket display."""
    booking = booking_service.get_booking(booking_id)
    if not booking:
        abort(404)

    # Authorization guard: Ensure users can only view their own bookings, except for authorized admin operations
    current_user_id = session.get("user_id")
    is_admin = session.get("user_role") == "admin"
    if not is_admin and booking.get("user_id") != current_user_id:
        abort(403)

    movie = movie_service.get_movie_by_id(booking["movie_id"])

    return render_template(
        "booking/confirmation.html",
        booking=booking,
        movie=movie,
    )


@booking_bp.route("/bookings/history", methods=["GET"])
@login_required
def booking_history():
    """Display user's previous bookings."""
    user_id = session["user_id"]
    bookings = booking_service.get_user_bookings(user_id)

    return render_template(
        "booking/history.html",
        bookings=bookings,
    )
