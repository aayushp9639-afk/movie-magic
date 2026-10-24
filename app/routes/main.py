"""Main Blueprint: Home, catalog, movie details, search, and health check."""
from flask import Blueprint, render_template, request, jsonify, current_app
from app.services import movie_service

main_bp = Blueprint("main", __name__)


@main_bp.route("/health", methods=["GET"])
def health_check():
    """Application Health Check endpoint.
    Used for local verification, load balancers, and EC2 readiness probes.
    """
    return jsonify({
        "status": "healthy",
        "service": "Movie Magic",
        "version": "1.75.0-verified-posters",
        "environment": current_app.config.get("ENV", "development"),
        "default_city": "Kolhapur",
        "aws_mode": "mock/demo" if current_app.config.get("USE_AWS_MOCK") else "live",
    }), 200


@main_bp.route("/", methods=["GET"])
def index():
    """Home landing page featuring hero showcase, categories, and Kolhapur cinemas."""
    selected_city = request.args.get("city", "Kolhapur")
    selected_category = request.args.get("category", "All")
    selected_language = request.args.get("language", "All")
    selected_genre = request.args.get("genre", "All")
    selected_sort = request.args.get("sort", "default")
    search_query = request.args.get("q", "").strip()

    featured_movies = movie_service.get_featured_movies()
    top_rated_movies = movie_service.get_top_rated_movies(limit=4)
    recent_movies = movie_service.get_recent_and_upcoming_movies(limit=4)
    all_movies = movie_service.list_movies(
        city=selected_city,
        genre=selected_genre,
        category=selected_category,
        language=selected_language,
        search_query=search_query,
        sort_by=selected_sort if selected_sort != "default" else None,
    )

    anime_movies = movie_service.get_movies_by_category("Anime")
    marvel_movies = movie_service.get_movies_by_category("Marvel")
    south_movies = movie_service.get_movies_by_category("South Indian")

    theaters = movie_service.get_theaters(city=selected_city)
    cities = movie_service.get_available_cities()
    categories = movie_service.get_available_categories()
    languages = movie_service.get_available_languages()
    genres = movie_service.get_available_genres()

    # Get all showtimes for badges
    all_showtimes = movie_service.get_showtimes()
    movies_with_shows = {s.get("movie_id") for s in all_showtimes}

    return render_template(
        "main/index.html",
        featured_movies=featured_movies,
        top_rated_movies=top_rated_movies,
        recent_movies=recent_movies,
        movies=all_movies,
        anime_movies=anime_movies,
        marvel_movies=marvel_movies,
        south_movies=south_movies,
        theaters=theaters,
        cities=cities,
        categories=categories,
        languages=languages,
        genres=genres,
        selected_city=selected_city,
        selected_category=selected_category,
        selected_language=selected_language,
        selected_genre=selected_genre,
        selected_sort=selected_sort,
        search_query=search_query,
        movies_with_shows=movies_with_shows,
    )


@main_bp.route("/movies", methods=["GET"])
def movies_catalog():
    """Browse curated movie catalog with search, sorting, and multifaceted filters."""
    selected_city = request.args.get("city", "Kolhapur")
    selected_category = request.args.get("category", "All")
    selected_language = request.args.get("language", "All")
    selected_genre = request.args.get("genre", "All")
    selected_sort = request.args.get("sort", "default")
    search_query = request.args.get("q", "").strip()

    movies = movie_service.list_movies(
        city=selected_city,
        genre=selected_genre,
        category=selected_category,
        language=selected_language,
        search_query=search_query,
        sort_by=selected_sort if selected_sort != "default" else None,
    )
    cities = movie_service.get_available_cities()
    categories = movie_service.get_available_categories()
    languages = movie_service.get_available_languages()
    genres = movie_service.get_available_genres()

    # Track which movies currently have showtimes scheduled
    all_showtimes = movie_service.get_showtimes()
    movies_with_shows = {s.get("movie_id") for s in all_showtimes}

    return render_template(
        "main/movies.html",
        movies=movies,
        cities=cities,
        categories=categories,
        languages=languages,
        genres=genres,
        selected_city=selected_city,
        selected_category=selected_category,
        selected_language=selected_language,
        selected_genre=selected_genre,
        selected_sort=selected_sort,
        search_query=search_query,
        movies_with_shows=movies_with_shows,
    )


@main_bp.route("/watchlist", methods=["GET"])
def watchlist():
    """Personal watchlist page displaying saved movies and full catalogue metadata."""
    selected_city = request.args.get("city", "Kolhapur")
    all_movies = movie_service.list_movies()
    all_showtimes = movie_service.get_showtimes()
    movies_with_shows = {s.get("movie_id") for s in all_showtimes}
    return render_template(
        "main/watchlist.html",
        movies=all_movies,
        selected_city=selected_city,
        movies_with_shows=movies_with_shows,
    )


@main_bp.route("/movies/<movie_id>", methods=["GET"])
def movie_detail(movie_id):
    """Movie details page showing verified metadata, showtimes, or cinema referral links."""
    movie = movie_service.get_movie_by_id(movie_id)
    if not movie:
        return render_template("errors/404.html", message="Movie not found"), 404

    selected_city = request.args.get("city", "Kolhapur")
    theaters = movie_service.get_theaters(city=selected_city)
    cities = movie_service.get_available_cities()

    # Fetch showtimes specifically scheduled for this movie
    movie_showtimes = movie_service.get_showtimes(movie_id=movie_id)

    # Filter showtimes by selected city
    city_theater_ids = {t["id"] for t in theaters}
    city_showtimes = [s for s in movie_showtimes if s.get("theater_id") in city_theater_ids]

    similar_movies = movie_service.get_similar_movies(movie, limit=4)
    all_showtimes = movie_service.get_showtimes()
    movies_with_shows = {s.get("movie_id") for s in all_showtimes}

    return render_template(
        "main/movie_detail.html",
        movie=movie,
        theaters=theaters,
        showtimes=city_showtimes,
        cities=cities,
        selected_city=selected_city,
        similar_movies=similar_movies,
        movies_with_shows=movies_with_shows,
    )


@main_bp.route("/api/movies", methods=["GET"])
def api_movies():
    """Public JSON API for movie catalogue discovery, search, and filtering."""
    selected_city = request.args.get("city", "Kolhapur")
    selected_category = request.args.get("category", "All")
    selected_language = request.args.get("language", "All")
    selected_genre = request.args.get("genre", "All")
    selected_sort = request.args.get("sort", "default")
    search_query = request.args.get("q", "").strip()

    movies = movie_service.list_movies(
        city=selected_city,
        genre=selected_genre,
        category=selected_category,
        language=selected_language,
        search_query=search_query,
        sort_by=selected_sort if selected_sort != "default" else None,
    )
    return jsonify({
        "status": "success",
        "count": len(movies),
        "movies": movies,
        "filters": {
            "city": selected_city,
            "category": selected_category,
            "language": selected_language,
            "genre": selected_genre,
            "sort": selected_sort,
            "q": search_query,
        },
    }), 200
