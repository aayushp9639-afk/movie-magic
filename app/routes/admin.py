"""Admin Blueprint: Management dashboard, movie catalogue, theaters, showtimes, and bookings."""
from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.forms import MovieForm, TheaterForm, ShowtimeForm
from app.services import movie_service, booking_service
from app.repositories import user_repository
from app.utils.decorators import admin_required

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/", methods=["GET"])
@admin_required
def dashboard():
    """Admin dashboard layout showing metrics, movies, venues, showtimes, and bookings."""
    all_movies = movie_service.list_movies()
    all_theaters = movie_service.get_theaters()
    all_showtimes = movie_service.get_showtimes()
    all_bookings = booking_service.get_all_bookings()
    all_users = user_repository.get_all()

    total_revenue = sum(b.get("total_price", 0) for b in all_bookings)
    total_tickets = sum(b.get("ticket_count", 0) for b in all_bookings)

    stats = {
        "movie_count": len(all_movies),
        "theater_count": len(all_theaters),
        "showtime_count": len(all_showtimes),
        "booking_count": len(all_bookings),
        "user_count": len(all_users),
        "total_revenue": total_revenue,
        "total_tickets": total_tickets,
    }

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        movies=all_movies,
        theaters=all_theaters,
        showtimes=all_showtimes,
        recent_bookings=all_bookings[:10],
    )


# -----------------------------------------------------------------------------
# Movie Catalogue Management
# -----------------------------------------------------------------------------
@admin_bp.route("/movies/new", methods=["GET", "POST"])
@admin_required
def add_movie():
    """Add a new movie to the catalogue."""
    form = MovieForm()

    if form.validate_on_submit():
        movie_data = {
            "title": form.title.data.strip(),
            "original_title": form.original_title.data.strip() if form.original_title.data else "",
            "category": form.category.data,
            "language": form.language.data,
            "genre": form.genre.data,
            "duration": form.duration.data.strip(),
            "duration_minutes": 120,
            "rating": form.rating.data,
            "imdb_score": float(form.imdb_score.data),
            "release_year": int(form.release_year.data),
            "director": form.director.data.strip(),
            "cast": ["Official Cast Members TBD"],
            "synopsis": form.synopsis.data.strip(),
            "poster_url": form.poster_url.data.strip() if form.poster_url.data else "",
            "badge": form.badge.data.strip() if form.badge.data else "Catalogue Addition",
            "is_featured": False,
            "status": "Catalogue / Added",
        }
        movie_service.add_movie(movie_data)
        flash(f"Movie '{movie_data['title']}' added to catalogue!", "success")
        return redirect(url_for("admin.dashboard"))

    return render_template("admin/add_movie.html", form=form, action="Add")


@admin_bp.route("/movies/<movie_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_movie(movie_id):
    """Edit existing movie record."""
    movie = movie_service.get_movie_by_id(movie_id)
    if not movie:
        flash("Movie not found.", "warning")
        return redirect(url_for("admin.dashboard"))

    form = MovieForm(data=movie)

    if form.validate_on_submit():
        updated_data = {
            "title": form.title.data.strip(),
            "original_title": form.original_title.data.strip() if form.original_title.data else "",
            "category": form.category.data,
            "language": form.language.data,
            "genre": form.genre.data,
            "duration": form.duration.data.strip(),
            "rating": form.rating.data,
            "imdb_score": float(form.imdb_score.data),
            "release_year": int(form.release_year.data),
            "director": form.director.data.strip(),
            "synopsis": form.synopsis.data.strip(),
            "poster_url": form.poster_url.data.strip() if form.poster_url.data else "",
            "badge": form.badge.data.strip() if form.badge.data else movie.get("badge", ""),
        }
        movie_service.update_movie(movie_id, updated_data)
        flash(f"Movie '{updated_data['title']}' updated successfully!", "success")
        return redirect(url_for("admin.dashboard"))

    return render_template("admin/add_movie.html", form=form, action="Edit", movie=movie)


@admin_bp.route("/movies/<movie_id>/delete", methods=["POST"])
@admin_required
def delete_movie(movie_id):
    """Delete a movie from the catalogue."""
    success = movie_service.delete_movie(movie_id)
    if success:
        flash("Movie removed from catalogue.", "info")
    else:
        flash("Movie not found.", "warning")
    return redirect(url_for("admin.dashboard"))


# -----------------------------------------------------------------------------
# Cinema Venue Management
# -----------------------------------------------------------------------------
@admin_bp.route("/theaters/new", methods=["GET", "POST"])
@admin_required
def add_theater():
    """Add a new cinema venue record."""
    form = TheaterForm()

    if form.validate_on_submit():
        screens = [s.strip() for s in form.screens_list.data.split(",") if s.strip()] if form.screens_list.data else []
        th_data = {
            "name": form.name.data.strip(),
            "address": form.address.data.strip(),
            "city": form.city.data,
            "state": form.state.data.strip(),
            "postal_code": form.postal_code.data.strip() if form.postal_code.data else "",
            "operational_status": form.operational_status.data,
            "is_verified": form.is_verified.data,
            "source_url": form.source_url.data.strip() if form.source_url.data else "",
            "screens": screens,
            "venue_type": form.venue_type.data.strip() if form.venue_type.data else "Cinema Hall",
            "badge": "Verified Venue" if form.is_verified.data else "Unverified Venue",
            "description": f"Cinema venue located in {form.city.data}, {form.state.data.strip()}.",
        }
        movie_service.add_theater(th_data)
        flash(f"Venue '{th_data['name']}' added successfully!", "success")
        return redirect(url_for("admin.dashboard"))

    return render_template("admin/manage_theater.html", form=form, action="Add")


@admin_bp.route("/theaters/<theater_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_theater(theater_id):
    """Edit cinema venue details and operational status."""
    th = movie_service.get_theater_by_id(theater_id)
    if not th:
        flash("Theater not found.", "warning")
        return redirect(url_for("admin.dashboard"))

    screens_str = ", ".join(th.get("screens", []))
    form = TheaterForm(data=th)
    if request.method == "GET":
        form.screens_list.data = screens_str

    if form.validate_on_submit():
        screens = [s.strip() for s in form.screens_list.data.split(",") if s.strip()] if form.screens_list.data else []
        th_data = {
            "name": form.name.data.strip(),
            "address": form.address.data.strip(),
            "city": form.city.data,
            "state": form.state.data.strip(),
            "postal_code": form.postal_code.data.strip() if form.postal_code.data else "",
            "operational_status": form.operational_status.data,
            "is_verified": form.is_verified.data,
            "source_url": form.source_url.data.strip() if form.source_url.data else "",
            "screens": screens,
            "venue_type": form.venue_type.data.strip() if form.venue_type.data else th.get("venue_type", ""),
            "badge": "Verified Venue" if form.is_verified.data else "Unverified Venue",
        }
        movie_service.update_theater(theater_id, th_data)
        flash(f"Venue '{th_data['name']}' updated successfully!", "success")
        return redirect(url_for("admin.dashboard"))

    return render_template("admin/manage_theater.html", form=form, action="Edit", theater=th)


@admin_bp.route("/theaters/<theater_id>/toggle-status", methods=["POST"])
@admin_required
def toggle_theater_status(theater_id):
    """Quick toggle theater operational status."""
    th = movie_service.get_theater_by_id(theater_id)
    if not th:
        flash("Theater not found.", "warning")
        return redirect(url_for("admin.dashboard"))

    new_status = "Unverified" if th.get("operational_status") == "Operational" else "Operational"
    new_verified = True if new_status == "Operational" else False
    movie_service.update_theater(theater_id, {
        "operational_status": new_status,
        "is_verified": new_verified,
        "badge": "Verified Venue" if new_verified else "Unverified Venue",
    })
    flash(f"Venue '{th['name']}' status changed to {new_status}.", "info")
    return redirect(url_for("admin.dashboard"))


# -----------------------------------------------------------------------------
# Showtime Schedule Management
# -----------------------------------------------------------------------------
@admin_bp.route("/showtimes/new", methods=["GET", "POST"])
@admin_required
def add_showtime():
    """Create a new showtime schedule."""
    movies = movie_service.list_movies()
    theaters = movie_service.get_theaters()

    form = ShowtimeForm()
    form.movie_id.choices = [(m["id"], m["title"]) for m in movies]
    form.theater_id.choices = [(t["id"], f"{t['name']} ({t['city']})") for t in theaters]

    if form.validate_on_submit():
        show_data = {
            "movie_id": form.movie_id.data,
            "theater_id": form.theater_id.data,
            "date": form.date.data.strip(),
            "time": form.time.data.strip(),
            "language_version": form.language_version.data.strip(),
            "format": form.format.data,
            "screen": form.screen.data.strip(),
            "price": float(form.price.data),
            "is_verified": form.is_verified.data,
            "status": "Verified" if form.is_verified.data else "Demo / Sample",
            "disclaimer": "Confirmed schedule" if form.is_verified.data else "DEMO DATA: Sample schedule for demonstration only.",
        }
        movie_service.add_showtime(show_data)
        flash("Showtime scheduled successfully!", "success")
        return redirect(url_for("admin.dashboard"))

    return render_template("admin/manage_showtime.html", form=form)


@admin_bp.route("/showtimes/<show_id>/delete", methods=["POST"])
@admin_required
def delete_showtime(show_id):
    """Delete a showtime from schedule."""
    success = movie_service.delete_showtime(show_id)
    if success:
        flash("Showtime removed from schedule.", "info")
    else:
        flash("Showtime not found.", "warning")
    return redirect(url_for("admin.dashboard"))
