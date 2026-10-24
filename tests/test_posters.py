"""Tests for verified TMDB movie posters, fallback cards, sync utility, and attribution."""

import json
import subprocess
import sys
from pathlib import Path
from app.data.sample_movies import SAMPLE_MOVIES, SAMPLE_CATEGORIES
from app.repositories.movie_repository import movie_repository


def test_all_28_movies_have_poster_urls():
    """Verify that all 28 movies in SAMPLE_MOVIES have a non-empty, valid poster URL."""
    assert len(SAMPLE_MOVIES) == 28
    for movie in SAMPLE_MOVIES:
        poster_url = movie.get("poster_url")
        assert poster_url is not None, f"Movie {movie['id']} has no poster_url"
        assert poster_url.startswith("https://image.tmdb.org/t/p/w500/"), (
            f"Movie {movie['id']} URL does not follow TMDB format: {poster_url}"
        )
        assert poster_url.endswith(".jpg"), f"Movie {movie['id']} URL does not end with .jpg"


def test_poster_category_distribution():
    """Verify poster counts by category match the Phase 1.75 audit requirements."""
    anime = [m for m in SAMPLE_MOVIES if m["category"] == "Anime"]
    marvel = [m for m in SAMPLE_MOVIES if m["category"] == "Marvel"]
    south = [m for m in SAMPLE_MOVIES if m["category"] == "South Indian"]

    assert len(anime) == 8, f"Expected 8 Anime movies, found {len(anime)}"
    assert len(marvel) == 8, f"Expected 8 Marvel movies, found {len(marvel)}"
    assert len(south) == 12, f"Expected 12 South Indian movies, found {len(south)}"


def test_poster_manifest_file_integrity():
    """Verify app/data/poster_manifest.json exists, has 28 entries and required attribution."""
    manifest_path = Path(__file__).resolve().parent.parent / "app" / "data" / "poster_manifest.json"
    assert manifest_path.exists(), "poster_manifest.json does not exist"

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "posters" in data
    assert "_attribution" in data
    assert "This product uses the TMDB API but is not endorsed or certified by TMDB" in data["_attribution"]

    posters = data["posters"]
    assert len(posters) == 28

    for movie in SAMPLE_MOVIES:
        m_id = movie["id"]
        assert m_id in posters, f"Movie {m_id} missing from poster manifest"
        assert posters[m_id]["poster_url"] == movie["poster_url"]
        assert posters[m_id]["poster_path"] is not None


def test_movie_id_to_poster_mapping():
    """Verify specific key titles map to verified canonical TMDB poster paths."""
    movie_dict = {m["id"]: m for m in SAMPLE_MOVIES}

    # Anime checks
    assert movie_dict["mov-anime-1"]["poster_url"] == "https://image.tmdb.org/t/p/w500/1RgPyOhN4DRs225BGTlHJqCudII.jpg"
    assert movie_dict["mov-anime-2"]["poster_url"] == "https://image.tmdb.org/t/p/w500/q719jXXEzOoYaps6babgKnONONX.jpg"
    assert movie_dict["mov-anime-6"]["poster_url"] == "https://image.tmdb.org/t/p/w500/39wmItIWsg5sZMyRUHLkWBcuVCM.jpg"

    # Marvel checks
    assert movie_dict["mov-marvel-1"]["poster_url"] == "https://image.tmdb.org/t/p/w500/or06FN3Dka5tukK1e9sl16pB3iy.jpg"
    assert movie_dict["mov-marvel-5"]["poster_url"] == "https://image.tmdb.org/t/p/w500/8cdWjvZQUExUUTzyp4t6EDMubfO.jpg"
    assert movie_dict["mov-marvel-6"]["poster_url"] == "https://image.tmdb.org/t/p/w500/r2J02Z2OpNTctfOSN1Ydgii51I3.jpg"

    # South Indian checks
    assert movie_dict["mov-south-1"]["poster_url"] == "https://image.tmdb.org/t/p/w500/1T21FblunT0y8fz7YaW8JMYgUKm.jpg"
    assert movie_dict["mov-south-3"]["poster_url"] == "https://image.tmdb.org/t/p/w500/u0XUBNQWlOvrh0Gd97ARGpIkL0.jpg"
    assert movie_dict["mov-south-7"]["poster_url"] == "https://image.tmdb.org/t/p/w500/2XUHC4lp3tDsgfFLFygNZ2x2Um9.jpg"


def test_catalogue_rendering_contains_poster_elements(client):
    """Verify the /movies page renders images with onerror fallbacks and lazy loading."""
    response = client.get("/movies")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    # Check that posters are rendered
    assert "https://image.tmdb.org/t/p/w500/" in html
    assert 'class="poster-img"' in html
    assert 'loading="lazy"' in html
    assert 'onerror="this.style.display=\'none\'; this.nextElementSibling.style.display=\'flex\';"' in html
    assert 'class="poster-art"' in html


def test_detail_page_poster_and_fallback_rendering(client):
    """Verify movie detail view renders poster with fallback container."""
    response = client.get("/movies/mov-marvel-1")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    assert "https://image.tmdb.org/t/p/w500/or06FN3Dka5tukK1e9sl16pB3iy.jpg" in html
    assert 'alt="Avengers: Endgame"' in html
    assert 'class="poster-container' in html
    assert 'class="poster-art"' in html


def test_missing_poster_graceful_fallback(client):
    """Verify that a movie record with no poster_url still renders an attractive card without error."""
    # Add temporary movie without poster_url
    temp_movie = {
        "title": "Unreleased Test Movie",
        "category": "Marvel",
        "genre": "Action",
        "language": "English",
        "duration": "1h 30m",
        "duration_minutes": 90,
        "rating": "U/A",
        "imdb_score": 7.0,
        "release_year": 2026,
        "director": "Test Director",
        "synopsis": "Test synopsis for missing poster fallback.",
        "poster_url": None,
        "status": "Catalogue / Upcoming"
    }
    created = movie_repository.add_movie(temp_movie)
    try:
        response = client.get(f"/movies/{created['id']}")
        assert response.status_code == 200
        html = response.data.decode("utf-8")
        assert "Unreleased Test Movie" in html
        # When poster_url is None, poster-art should NOT be display: none
        assert 'class="poster-art"' in html
    finally:
        movie_repository.delete_movie(created["id"])


def test_footer_contains_tmdb_attribution(client):
    """Verify footer displays required TMDB attribution text and logo."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    assert "This product uses the TMDB API but is not endorsed or certified by TMDB" in html
    assert "https://www.themoviedb.org/" in html
    assert "The Movie Database (TMDB) Logo" in html


def test_admin_movie_form_contains_live_preview_elements(admin_client):
    """Verify the admin add/edit movie form contains live poster preview elements."""
    response = admin_client.get("/admin/movies/new")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    assert "Live Poster Preview" in html
    assert 'id="adminPosterImg"' in html
    assert 'id="adminPosterFallback"' in html
    assert 'id="moviePosterUrl"' in html
    assert 'id="posterValidationBadge"' in html
    assert "updatePreview()" in html


def test_sync_script_dry_run_execution():
    """Verify scripts/sync_movie_posters.py executes cleanly in --dry-run mode."""
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "sync_movie_posters.py"
    result = subprocess.run(
        [sys.executable, str(script_path), "--dry-run"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Sync script failed with output: {result.stderr}"
    assert "Total Movies:            28" in result.stdout
    assert "Successfully Matched:    28" in result.stdout
    assert "Unmatched Titles:        0" in result.stdout
    assert "[Dry Run] No files modified." in result.stdout
