"""Unit tests for DynamoDB Catalogue Repository (Movies, Theatres, Showtimes).

Verifies:
- Movie retrieval by ID and category filtering via CategoryIndex GSI
- Theatre retrieval and filtering via CityStatusIndex GSI
- Showtime queries via MovieShowtimeIndex and TheaterShowtimeIndex GSIs
- Pagination handling across scans and queries
- Safe Decimal conversion and item field contract compatibility
- Preservation of demo showtime status and disclaimers
- Strict anti-degradation rule: USE_AWS_MOCK=False raises RuntimeError if misconfigured
- Zero live AWS calls (all AWS interactions mocked)
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch
import pytest
from botocore.exceptions import ClientError

from app.repositories.movie_repository import (
    InMemoryMovieRepository,
    DynamoDBMovieRepository,
    CataloguePersistenceError,
    clean_dynamodb_value,
    deserialize_dynamodb_item,
    get_movie_repository,
    MovieRepositoryProxy,
)


class TestTypeCleaningAndDeserialization:
    """Test DynamoDB type conversion and deserialization."""

    def test_clean_dynamodb_value_converts_decimals(self):
        assert clean_dynamodb_value(Decimal("8.5")) == 8.5
        assert isinstance(clean_dynamodb_value(Decimal("8.5")), float)
        assert clean_dynamodb_value(Decimal("2024")) == 2024
        assert isinstance(clean_dynamodb_value(Decimal("2024")), int)
        assert clean_dynamodb_value({"score": Decimal("9.0"), "tags": [Decimal("1")]}) == {
            "score": 9,
            "tags": [1],
        }

    def test_deserialize_dynamodb_item_sets_both_id_and_key(self):
        raw = {
            "movie_id": {"S": "mov-test-1"},
            "title": {"S": "Test Movie"},
            "imdb_score": {"N": "8.4"},
            "release_year": {"N": "2023"},
        }
        item = deserialize_dynamodb_item(raw, id_key="movie_id")
        assert item["movie_id"] == "mov-test-1"
        assert item["id"] == "mov-test-1"
        assert item["title"] == "Test Movie"
        assert item["imdb_score"] == 8.4
        assert item["release_year"] == 2023


class TestDynamoDBMovieOperations:
    """Test movie queries and index usage."""

    @pytest.fixture
    def mock_dynamo_client(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_dynamo_client):
        return DynamoDBMovieRepository(client=mock_dynamo_client, table_prefix="moviemagic_")

    def test_get_by_id_retrieves_movie(self, repo, mock_dynamo_client):
        mock_dynamo_client.get_item.return_value = {
            "Item": {
                "movie_id": {"S": "mov-anime-1"},
                "title": {"S": "Demon Slayer"},
                "category": {"S": "Anime"},
            }
        }
        movie = repo.get_by_id("mov-anime-1")
        assert movie is not None
        assert movie["id"] == "mov-anime-1"
        assert movie["title"] == "Demon Slayer"
        mock_dynamo_client.get_item.assert_called_once_with(
            TableName="moviemagic_movies",
            Key={"movie_id": {"S": "mov-anime-1"}},
        )

    def test_get_by_id_not_found_returns_none(self, repo, mock_dynamo_client):
        mock_dynamo_client.get_item.return_value = {}
        assert repo.get_by_id("nonexistent") is None

    def test_get_all_with_category_uses_category_index_gsi(self, repo, mock_dynamo_client):
        """When category filter is provided, repo must query CategoryIndex, NOT scan."""
        mock_dynamo_client.query.return_value = {
            "Items": [
                {
                    "movie_id": {"S": "mov-anime-1"},
                    "title": {"S": "Demon Slayer"},
                    "category": {"S": "Anime"},
                    "genre": {"S": "Action / Animation"},
                    "language": {"S": "Japanese"},
                }
            ]
        }
        movies = repo.get_all(category="Anime")
        assert len(movies) == 1
        assert movies[0]["title"] == "Demon Slayer"

        mock_dynamo_client.query.assert_called_once()
        _, kwargs = mock_dynamo_client.query.call_args
        assert kwargs["TableName"] == "moviemagic_movies"
        assert kwargs["IndexName"] == "CategoryIndex"
        assert kwargs["KeyConditionExpression"] == "#cat = :cat"
        mock_dynamo_client.scan.assert_not_called()

    def test_get_all_without_category_scans_with_pagination(self, repo, mock_dynamo_client):
        """When category is 'All' or omitted, repo scans with LastEvaluatedKey pagination."""
        mock_dynamo_client.scan.side_effect = [
            {
                "Items": [{"movie_id": {"S": "mov-1"}, "title": {"S": "M1"}}],
                "LastEvaluatedKey": {"movie_id": {"S": "mov-1"}},
            },
            {
                "Items": [{"movie_id": {"S": "mov-2"}, "title": {"S": "M2"}}],
            },
        ]
        movies = repo.get_all()
        assert len(movies) == 2
        assert mock_dynamo_client.scan.call_count == 2

    def test_add_and_delete_movie(self, repo, mock_dynamo_client):
        movie_data = {"title": "New Movie", "category": "Marvel", "release_year": 2025}
        added = repo.add_movie(movie_data)
        assert added["id"].startswith("mov-")
        mock_dynamo_client.put_item.assert_called_once()

        mock_dynamo_client.query.return_value = {"Items": []}  # No associated showtimes
        deleted = repo.delete_movie(added["id"])
        assert deleted is True
        mock_dynamo_client.delete_item.assert_called_once_with(
            TableName="moviemagic_movies",
            Key={"movie_id": {"S": added["id"]}},
        )


class TestDynamoDBTheaterOperations:
    """Test theater queries and CityStatusIndex GSI usage."""

    @pytest.fixture
    def mock_dynamo_client(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_dynamo_client):
        return DynamoDBMovieRepository(client=mock_dynamo_client, table_prefix="moviemagic_")

    def test_get_theater_by_id(self, repo, mock_dynamo_client):
        mock_dynamo_client.get_item.return_value = {
            "Item": {
                "theater_id": {"S": "th-pvr-dyp"},
                "name": {"S": "PVR DYP City Mall"},
                "city": {"S": "Kolhapur"},
                "operational_status": {"S": "Operational"},
            }
        }
        th = repo.get_theater_by_id("th-pvr-dyp")
        assert th is not None
        assert th["id"] == "th-pvr-dyp"
        assert th["name"] == "PVR DYP City Mall"

    def test_get_theaters_by_city_uses_city_status_index_gsi(self, repo, mock_dynamo_client):
        """When city and operational_only are provided, queries CityStatusIndex with composite key."""
        mock_dynamo_client.query.return_value = {
            "Items": [
                {
                    "theater_id": {"S": "th-pvr-dyp"},
                    "name": {"S": "PVR DYP City Mall"},
                    "city": {"S": "Kolhapur"},
                    "operational_status": {"S": "Operational"},
                    "is_verified": {"BOOL": True},
                }
            ]
        }
        theaters = repo.get_theaters(city="Kolhapur", operational_only=True)
        assert len(theaters) == 1

        mock_dynamo_client.query.assert_called_once()
        _, kwargs = mock_dynamo_client.query.call_args
        assert kwargs["TableName"] == "moviemagic_theaters"
        assert kwargs["IndexName"] == "CityStatusIndex"
        assert kwargs["KeyConditionExpression"] == "#city = :city AND #status = :status"


class TestDynamoDBShowtimeOperations:
    """Test showtime queries and dual GSI usage."""

    @pytest.fixture
    def mock_dynamo_client(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_dynamo_client):
        return DynamoDBMovieRepository(client=mock_dynamo_client, table_prefix="moviemagic_")

    def test_get_showtimes_by_movie_id_uses_movie_showtime_index(self, repo, mock_dynamo_client):
        """When movie_id is provided, queries MovieShowtimeIndex GSI."""
        mock_dynamo_client.query.return_value = {
            "Items": [
                {
                    "showtime_id": {"S": "show-1"},
                    "movie_id": {"S": "mov-south-1"},
                    "theater_id": {"S": "th-pvr-dyp"},
                    "date": {"S": "Today"},
                    "time": {"S": "10:30 AM"},
                    "date_time": {"S": "Today 10:30 AM"},
                    "status": {"S": "Demo / Sample"},
                    "is_verified": {"BOOL": False},
                    "price": {"N": "220"},
                }
            ]
        }
        # Mock get_item calls for theater and movie enrichment
        mock_dynamo_client.get_item.side_effect = [
            {"Item": {"theater_id": {"S": "th-pvr-dyp"}, "name": {"S": "PVR DYP City Mall"}, "city": {"S": "Kolhapur"}, "is_verified": {"BOOL": True}}},
            {"Item": {"movie_id": {"S": "mov-south-1"}, "title": {"S": "Pushpa 2: The Rule"}}},
        ]

        shows = repo.get_showtimes(movie_id="mov-south-1")
        assert len(shows) == 1
        show = shows[0]
        assert show["id"] == "show-1"
        assert show["theater_name"] == "PVR DYP City Mall"
        assert show["movie_title"] == "Pushpa 2: The Rule"
        assert show["status"] == "Demo / Sample"
        assert show["is_verified"] is False  # Demo status preserved!

        mock_dynamo_client.query.assert_called_once()
        _, kwargs = mock_dynamo_client.query.call_args
        assert kwargs["IndexName"] == "MovieShowtimeIndex"
        assert kwargs["KeyConditionExpression"] == "movie_id = :mid"

    def test_get_showtimes_by_theater_id_uses_theater_showtime_index(self, repo, mock_dynamo_client):
        """When theater_id is provided, queries TheaterShowtimeIndex GSI."""
        mock_dynamo_client.query.return_value = {
            "Items": [
                {
                    "showtime_id": {"S": "show-2"},
                    "movie_id": {"S": "mov-south-2"},
                    "theater_id": {"S": "th-inox-mega"},
                    "date_time": {"S": "Today 02:30 PM"},
                }
            ]
        }
        mock_dynamo_client.get_item.return_value = {}

        shows = repo.get_showtimes(theater_id="th-inox-mega")
        assert len(shows) == 1
        mock_dynamo_client.query.assert_called_once()
        _, kwargs = mock_dynamo_client.query.call_args
        assert kwargs["IndexName"] == "TheaterShowtimeIndex"
        assert kwargs["KeyConditionExpression"] == "theater_id = :tid"


class TestConfigurationAndAntiDegradation:
    """Verify repository selection and strict anti-degradation rule."""

    def test_mock_mode_active_returns_in_memory_repository(self, monkeypatch):
        monkeypatch.setenv("USE_AWS_MOCK", "True")
        repo = get_movie_repository()
        assert isinstance(repo, InMemoryMovieRepository)

    def test_live_mode_misconfiguration_raises_runtime_error(self, monkeypatch):
        """When USE_AWS_MOCK=False but client cannot be initialized, raise RuntimeError."""
        monkeypatch.setenv("USE_AWS_MOCK", "False")
        with patch("app.repositories.movie_repository.get_boto3_client", return_value=None):
            with pytest.raises(RuntimeError) as exc_info:
                get_movie_repository()
            assert "Silent fallback to in-memory mock is prohibited" in str(exc_info.value)

    def test_movie_repository_proxy_delegation(self):
        proxy = MovieRepositoryProxy()
        # In mock mode, returns 28 catalogue movies
        movies = proxy.get_all()
        assert len(movies) == 28
        assert proxy.get_theater_by_id("th-pvr-dyp") is not None
        assert len(proxy.get_cities()) == 3
