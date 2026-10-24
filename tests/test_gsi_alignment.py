"""Verification test for Global Secondary Index (GSI) schema alignment.
Ensures every GSI referenced in application repositories exactly matches
the definitions in scripts/create_dynamodb_tables.py.
"""
from scripts.create_dynamodb_tables import get_table_definitions
from app.repositories.user_repository import DynamoDBUserRepository
from app.repositories.movie_repository import DynamoDBMovieRepository
from app.repositories.booking_repository import DynamoDBBookingRepository


def test_table_definitions_gsi_schemas():
    """Verify all 5 GSIs are present in table schemas with correct names and key types."""
    tables = get_table_definitions(prefix="moviemagic_")

    # 1. Users table
    users_table = tables["moviemagic_users"]
    user_gsis = {g["IndexName"]: g["KeySchema"] for g in users_table.get("GlobalSecondaryIndexes", [])}
    assert "EmailIndex" in user_gsis
    assert user_gsis["EmailIndex"] == [{"AttributeName": "email", "KeyType": "HASH"}]

    # 2. Movies table
    movies_table = tables["moviemagic_movies"]
    movie_gsis = {g["IndexName"]: g["KeySchema"] for g in movies_table.get("GlobalSecondaryIndexes", [])}
    assert "CategoryIndex" in movie_gsis
    assert movie_gsis["CategoryIndex"] == [
        {"AttributeName": "category", "KeyType": "HASH"},
        {"AttributeName": "release_year", "KeyType": "RANGE"},
    ]

    # 3. Theaters table
    theaters_table = tables["moviemagic_theaters"]
    theater_gsis = {g["IndexName"]: g["KeySchema"] for g in theaters_table.get("GlobalSecondaryIndexes", [])}
    assert "CityStatusIndex" in theater_gsis
    assert theater_gsis["CityStatusIndex"] == [
        {"AttributeName": "city", "KeyType": "HASH"},
        {"AttributeName": "operational_status", "KeyType": "RANGE"},
    ]

    # 4. Showtimes table
    showtimes_table = tables["moviemagic_showtimes"]
    showtime_gsis = {g["IndexName"]: g["KeySchema"] for g in showtimes_table.get("GlobalSecondaryIndexes", [])}
    assert "MovieShowtimeIndex" in showtime_gsis
    assert "TheaterShowtimeIndex" in showtime_gsis
    assert showtime_gsis["MovieShowtimeIndex"] == [
        {"AttributeName": "movie_id", "KeyType": "HASH"},
        {"AttributeName": "date_time", "KeyType": "RANGE"},
    ]
    assert showtime_gsis["TheaterShowtimeIndex"] == [
        {"AttributeName": "theater_id", "KeyType": "HASH"},
        {"AttributeName": "date_time", "KeyType": "RANGE"},
    ]

    # 5. Bookings table
    bookings_table = tables["moviemagic_bookings"]
    booking_gsis = {g["IndexName"]: g["KeySchema"] for g in bookings_table.get("GlobalSecondaryIndexes", [])}
    assert "UserBookingsIndex" in booking_gsis
    assert booking_gsis["UserBookingsIndex"] == [
        {"AttributeName": "user_id", "KeyType": "HASH"},
        {"AttributeName": "created_at", "KeyType": "RANGE"},
    ]


def test_repository_gsi_references_match_table_definitions():
    """Verify repository methods reference exact GSI names defined in create_dynamodb_tables.py."""
    tables = get_table_definitions(prefix="moviemagic_")

    all_defined_gsis = set()
    for table_def in tables.values():
        for gsi in table_def.get("GlobalSecondaryIndexes", []):
            all_defined_gsis.add(gsi["IndexName"])

    expected_gsis = {
        "EmailIndex",
        "CategoryIndex",
        "CityStatusIndex",
        "MovieShowtimeIndex",
        "TheaterShowtimeIndex",
        "UserBookingsIndex",
    }
    assert all_defined_gsis == expected_gsis
