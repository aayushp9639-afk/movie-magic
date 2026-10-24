"""Tests for administrator dashboard, role-based access control, venues, and showtime schedules."""


def test_admin_dashboard_anonymous_redirected(client):
    """Anonymous visitor must be redirected to sign in."""
    response = client.get("/admin/", follow_redirects=False)
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_admin_dashboard_regular_user_forbidden(auth_client):
    """Regular user accessing admin dashboard receives 403 Forbidden."""
    response = auth_client.get("/admin/")
    assert response.status_code == 403
    assert b"403" in response.data or b"Forbidden" in response.data


def test_admin_dashboard_admin_allowed(admin_client):
    """Administrator accessing admin dashboard receives 200 OK with management tables."""
    response = admin_client.get("/admin/")
    assert response.status_code == 200
    assert b"Operational Management" in response.data
    assert b"Cinema Venues &amp; Operational Status" in response.data or b"Cinema Venues & Operational Status" in response.data
    assert b"Showtimes Schedules" in response.data


def test_admin_add_movie(admin_client):
    """Admin can successfully add a new movie to the catalogue."""
    response = admin_client.post(
        "/admin/movies/new",
        data={
            "title": "Solo Leveling: ReAwakening",
            "original_title": "나 혼자만 레벨업",
            "category": "Anime",
            "language": "Japanese",
            "genre": "Animation",
            "duration": "1h 55m",
            "rating": "U/A",
            "imdb_score": 8.5,
            "release_year": 2024,
            "director": "Shunsuke Nakashige",
            "poster_url": "https://image.tmdb.org/t/p/w500/test.jpg",
            "synopsis": "Sung Jinwoo fights to survive in a deadly dungeon.",
            "badge": "Anime Feature",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Solo Leveling: ReAwakening" in response.data


def test_admin_delete_movie(admin_client):
    """Admin can delete a movie from catalogue."""
    response = admin_client.post("/admin/movies/mov-south-12/delete", follow_redirects=True)
    assert response.status_code == 200
    assert b"Movie removed from catalogue" in response.data


def test_admin_toggle_theater_status(admin_client):
    """Admin can toggle operational status of a cinema venue."""
    # Toggle Shahu Cinema to unverified
    response = admin_client.post("/admin/theaters/th-shahu/toggle-status", follow_redirects=True)
    assert response.status_code == 200
    assert b"status changed to" in response.data


def test_admin_schedule_showtime(admin_client):
    """Admin can create and schedule a new verified or demo showtime."""
    response = admin_client.post(
        "/admin/showtimes/new",
        data={
            "movie_id": "mov-south-1",
            "theater_id": "th-pvr-dyp",
            "date": "Tomorrow",
            "time": "09:30 PM",
            "language_version": "Telugu (English Subtitles)",
            "format": "2D",
            "screen": "Audi 1",
            "price": 280.00,
            "is_verified": "y",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Showtime scheduled successfully" in response.data
