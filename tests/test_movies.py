"""Tests for curated movie catalogue, categories, Kolhapur theatres, and filtering."""


def test_index_page_loads(client):
    """Verify home page loads successfully with Kolhapur as default and real catalogue."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"Movie Magic" in response.data
    assert b"Kolhapur" in response.data
    assert b"Pushpa 2: The Rule" in response.data
    assert b"PVR DYP City Mall" in response.data


def test_kolhapur_default_location(client):
    """Verify Kolhapur is selected as the default location."""
    response = client.get("/")
    assert response.status_code == 200
    # Verified venue in Kolhapur
    assert b"Cinema Venues in Kolhapur" in response.data


def test_movies_catalog_loads(client):
    """Verify full movie catalogue view loads with curated categories."""
    response = client.get("/movies")
    assert response.status_code == 200
    assert b"Curated Movie Catalogue" in response.data
    assert b"Demon Slayer" in response.data
    assert b"Avengers: Endgame" in response.data
    assert b"Pushpa 2: The Rule" in response.data


def test_category_filter_anime(client):
    """Verify Anime category filtering returns anime titles only."""
    response = client.get("/movies?category=Anime")
    assert response.status_code == 200
    assert b"Demon Slayer" in response.data
    assert b"Your Name." in response.data
    assert b"Suzume" in response.data
    assert b"Avengers: Endgame" not in response.data
    assert b"Pushpa 2" not in response.data


def test_category_filter_marvel(client):
    """Verify Marvel category filtering returns Marvel titles."""
    response = client.get("/movies?category=Marvel")
    assert response.status_code == 200
    assert b"Avengers: Endgame" in response.data
    assert b"Spider-Man: Across the Spider-Verse" in response.data
    assert b"Deadpool &amp; Wolverine" in response.data or b"Deadpool & Wolverine" in response.data
    assert b"Your Name." not in response.data
    assert b"Kalki 2898 AD" not in response.data


def test_category_filter_south_indian(client):
    """Verify South Indian category filtering returns regional cinema titles."""
    response = client.get("/movies?category=South Indian")
    assert response.status_code == 200
    assert b"Pushpa 2: The Rule" in response.data
    assert b"Kalki 2898 AD" in response.data
    assert b"RRR" in response.data
    assert b"Manjummel Boys" in response.data
    assert b"Avengers: Endgame" not in response.data
    assert b"Suzume" not in response.data


def test_language_filter(client):
    """Verify language filtering works for Japanese, Telugu, and Malayalam."""
    # Test Japanese
    res_ja = client.get("/movies?language=Japanese")
    assert res_ja.status_code == 200
    assert b"Demon Slayer" in res_ja.data
    assert b"Pushpa 2" not in res_ja.data

    # Test Malayalam
    res_ml = client.get("/movies?language=Malayalam")
    assert res_ml.status_code == 200
    assert b"Manjummel Boys" in res_ml.data
    assert b"Aavesham" in res_ml.data
    assert b"Avengers: Endgame" not in res_ml.data


def test_movie_search_filter(client):
    """Test searching by title query across real movies."""
    response = client.get("/movies?q=Kalki")
    assert response.status_code == 200
    assert b"Kalki 2898 AD" in response.data
    assert b"Your Name." not in response.data


def test_kolhapur_theaters_and_sources(client):
    """Verify real Kolhapur cinema venues and public source listing URLs."""
    response = client.get("/")
    assert response.status_code == 200
    # PVR DYP City Mall
    assert b"PVR DYP City Mall" in response.data
    assert b"Kavala Naka" in response.data
    assert b"district.in" in response.data
    # INOX Reliance Mega Mall
    assert b"INOX Reliance Mega Mall" in response.data
    assert b"Laxmipuri" in response.data
    assert b"cinematimes.in" in response.data
    # Prabhat Royal Cineplex
    assert b"Prabhat Royal Cineplex" in response.data
    # Shahu Cinema
    assert b"Shahu Cinema" in response.data


def test_unverified_theater_status(client):
    """Verify unverified theatre (Padma Talkies) is visibly marked and not confirmed operational."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"Padma Talkies" in response.data
    assert b"Unverified" in response.data


def test_movie_detail_page_with_demo_showtimes(client):
    """Test movie details for film with demo showtimes displays visible demo notice."""
    response = client.get("/movies/mov-south-1")
    assert response.status_code == 200
    assert b"Pushpa 2: The Rule" in response.data
    assert b"Sukumar" in response.data
    assert b"DEMO DATA NOTICE" in response.data
    assert b"Select Seats (Demo)" in response.data


def test_movie_detail_without_showtimes_shows_referral(client):
    """Test catalogue movie without active showtimes displays 'Showtimes not verified' notice."""
    response = client.get("/movies/mov-anime-2")  # Your Name (catalogue only)
    assert response.status_code == 200
    assert b"Your Name." in response.data
    assert b"Showtimes not verified" in response.data
    assert b"district.in" in response.data or b"bookmyshow.com" in response.data


def test_movie_detail_not_found(client):
    """Test 404 for nonexistent movie."""
    response = client.get("/movies/mov-nonexistent-999")
    assert response.status_code == 404
    assert b"404" in response.data


def test_homepage_hero_is_brand_centric_not_movie_specific(client):
    """Verify homepage renders Movie Magic brand-centric hero and not Pushpa 2 dominant hero."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.data.decode("utf-8")

    # Assert brand-centric hero elements are present
    assert "Experience the Magic of" in html
    assert "Big-Screen Cinema" in html
    assert "Explore Movies" in html
    assert "Find Showtimes" in html
    assert "Kolhapur Cinema Hub" in html

    # Extract hero section specifically
    hero_section = html.split('<section class="hero-backdrop">')[1].split("</section>")[0]
    assert "Pushpa 2" not in hero_section
    assert "Sukumar" not in hero_section
    assert "Reserve Kolhapur Show" not in hero_section

    # Ensure Pushpa 2 remains in the catalogue grid on the page
    assert "Pushpa 2: The Rule" in html


def test_movie_cards_secondary_actions_for_available_and_unavailable_showtimes(client):
    """Verify movie cards render Shows when showtimes exist and high-contrast Unavailable when not."""
    # 1. Full catalogue page /movies
    response_catalog = client.get("/movies")
    assert response_catalog.status_code == 200
    html_catalog = response_catalog.data.decode("utf-8")

    assert "Shows" in html_catalog
    assert "Unavailable" in html_catalog
    assert "btn-disabled-action" in html_catalog
    # Old low-contrast button text is replaced
    assert ">Catalogue<" not in html_catalog

    # 2. Homepage /
    response_home = client.get("/")
    assert response_home.status_code == 200
    html_home = response_home.data.decode("utf-8")

    assert "Shows" in html_home
    assert "Unavailable" in html_home
    assert "btn-disabled-action" in html_home
    assert ">Catalogue<" not in html_home


def test_movies_catalog_sorting(client):
    """Verify sorting options on /movies (rating_desc, year_desc, title_asc)."""
    res_rating = client.get("/movies?sort=rating_desc")
    assert res_rating.status_code == 200
    html_rating = res_rating.data.decode("utf-8")
    assert "Top Rated" in html_rating

    res_title = client.get("/movies?sort=title_asc")
    assert res_title.status_code == 200
    html_title = res_title.data.decode("utf-8")
    # Aavesham should appear before Your Name. when sorted A-Z
    assert html_title.index("Aavesham") < html_title.index("Your Name.")


def test_watchlist_page_loads(client):
    """Verify the personal Watchlist page renders empty state and movie templates."""
    response = client.get("/watchlist")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "My Personal Watchlist" in html
    assert "watchlistMoviesGrid" in html
    assert "watchlistEmptyState" in html


def test_movie_detail_shows_similar_movies_and_watchlist_cta(client):
    """Verify movie detail view includes related movie recommendations and Watchlist CTA."""
    response = client.get("/movies/mov-anime-1")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "More in Anime Cinema" in html
    assert "Save to Watchlist" in html


def test_combined_search_genre_sort_and_missing_metadata_resilience(client):
    """Verify combined filters work together and missing optional metadata does not break templates."""
    from app.repositories.movie_repository import movie_repository

    res_combo = client.get("/movies?category=Anime&genre=Fantasy&sort=rating_desc")
    assert res_combo.status_code == 200
    assert b"Demon Slayer" in res_combo.data

    sparse_movie = movie_repository.add_movie({
        "title": "Sparse Metadata Test Film",
        "genre": None,
        "cast": None,
        "director": None,
        "poster_url": None,
    })
    try:
        for path in ("/", "/movies", "/watchlist", f"/movies/{sparse_movie['id']}"):
            resp = client.get(path)
            assert resp.status_code == 200
    finally:
        movie_repository.delete_movie(sparse_movie["id"])


def test_api_movies_endpoint(client):
    """Verify /api/movies returns valid JSON catalogue with filter support."""
    response = client.get("/api/movies")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "success"
    assert data["count"] >= 28
    assert len(data["movies"]) >= 28

    # Filter by category
    res_anime = client.get("/api/movies?category=Anime")
    assert res_anime.status_code == 200
    data_anime = res_anime.get_json()
    assert data_anime["count"] >= 8
    assert all(m["category"] == "Anime" for m in data_anime["movies"])



