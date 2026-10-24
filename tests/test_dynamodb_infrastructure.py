"""Tests for DynamoDB Client Factory, Schema Inspection, and Table Infrastructure.

Verifies:
- AWS client factory behavior in mock vs real modes
- Region resolution defaulting to ap-south-1 (Mumbai)
- DynamoDB endpoint URL support for local containers/testing
- Table definitions for all 6 core tables with PAY_PER_REQUEST billing
- Primary keys and Global Secondary Index (GSI) accuracy
- Schema mismatch detection logic
- Protection of customer tables (users, bookings, show_seats) during seeding
- Idempotent seeding logic and float-to-Decimal conversions
"""

import os
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.aws.client_factory import (
    DEFAULT_REGION,
    get_default_region,
    get_boto3_client,
    get_boto3_resource,
    is_mock_mode_active,
)
from app.aws.dynamodb import DynamoDBService
from scripts.create_dynamodb_tables import (
    get_table_definitions,
    inspect_table_schema,
    check_tables,
    create_tables,
)
from scripts.seed_dynamodb import (
    to_dynamodb_compatible,
    prepare_movie_items,
    prepare_theater_items,
    prepare_showtime_items,
    seed_table,
    PROTECTED_TABLE_CATEGORIES,
)


class TestClientFactory:
    """Test AWS client factory functionality and safety guarantees."""

    def test_default_region_is_ap_south_1(self):
        """Verify DEFAULT_REGION is set to ap-south-1 (Mumbai)."""
        assert DEFAULT_REGION == "ap-south-1"

    def test_get_default_region_reads_env_or_default(self, monkeypatch):
        """Verify region resolution respects AWS_REGION env var or defaults to ap-south-1."""
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        assert get_default_region() == "ap-south-1"

        monkeypatch.setenv("AWS_REGION", "ap-south-1")
        assert get_default_region() == "ap-south-1"

    def test_mock_mode_returns_none_without_network_calls(self, monkeypatch):
        """When USE_AWS_MOCK is True, client factory returns None immediately."""
        monkeypatch.setenv("USE_AWS_MOCK", "True")
        assert is_mock_mode_active() is True
        assert get_boto3_client("dynamodb") is None
        assert get_boto3_resource("dynamodb") is None

    def test_endpoint_url_passed_to_boto3(self, monkeypatch):
        """Verify custom endpoint_url (e.g. for DynamoDB Local) is passed to boto3."""
        monkeypatch.setenv("USE_AWS_MOCK", "False")
        with patch("boto3.client") as mock_client:
            mock_client.return_value = MagicMock()
            client = get_boto3_client("dynamodb", endpoint_url="http://localhost:8000")
            assert client is not None
            mock_client.assert_called_once()
            _, kwargs = mock_client.call_args
            assert kwargs["endpoint_url"] == "http://localhost:8000"
            assert kwargs["region_name"] == "ap-south-1"

    def test_dynamodb_service_mock_mode(self):
        """Verify DynamoDBService reports correct mock mode status."""
        service = DynamoDBService(use_mock=True)
        assert service.is_mock is True
        assert service.client is None
        assert service.resource is None


class TestDynamoDBTableDefinitions:
    """Test schema specifications and table definitions for all 6 tables."""

    @pytest.fixture
    def tables(self):
        return get_table_definitions(prefix="test_moviemagic_")

    def test_table_definitions_contain_all_six_tables(self, tables):
        """Ensure all 6 core tables are specified."""
        expected_tables = {
            "test_moviemagic_users",
            "test_moviemagic_movies",
            "test_moviemagic_theaters",
            "test_moviemagic_showtimes",
            "test_moviemagic_bookings",
            "test_moviemagic_show_seats",
        }
        assert set(tables.keys()) == expected_tables

    def test_all_tables_use_pay_per_request_billing(self, tables):
        """Verify all tables use on-demand (PAY_PER_REQUEST) billing to prevent idle costs."""
        for t_name, schema in tables.items():
            assert schema["BillingMode"] == "PAY_PER_REQUEST", (
                f"Table {t_name} does not use PAY_PER_REQUEST billing."
            )

    def test_users_table_keys_and_indexes(self, tables):
        """Verify users table primary key (user_id) and EmailIndex GSI."""
        schema = tables["test_moviemagic_users"]
        assert schema["KeySchema"] == [{"AttributeName": "user_id", "KeyType": "HASH"}]
        gsis = schema.get("GlobalSecondaryIndexes", [])
        assert len(gsis) == 1
        assert gsis[0]["IndexName"] == "EmailIndex"
        assert gsis[0]["KeySchema"] == [{"AttributeName": "email", "KeyType": "HASH"}]

    def test_movies_table_keys_and_indexes(self, tables):
        """Verify movies table primary key (movie_id) and CategoryIndex GSI."""
        schema = tables["test_moviemagic_movies"]
        assert schema["KeySchema"] == [{"AttributeName": "movie_id", "KeyType": "HASH"}]
        gsis = schema.get("GlobalSecondaryIndexes", [])
        assert len(gsis) == 1
        assert gsis[0]["IndexName"] == "CategoryIndex"
        assert gsis[0]["KeySchema"] == [
            {"AttributeName": "category", "KeyType": "HASH"},
            {"AttributeName": "release_year", "KeyType": "RANGE"},
        ]

    def test_theaters_table_keys_and_indexes(self, tables):
        """Verify theaters table primary key (theater_id) and CityStatusIndex GSI."""
        schema = tables["test_moviemagic_theaters"]
        assert schema["KeySchema"] == [{"AttributeName": "theater_id", "KeyType": "HASH"}]
        gsis = schema.get("GlobalSecondaryIndexes", [])
        assert len(gsis) == 1
        assert gsis[0]["IndexName"] == "CityStatusIndex"
        assert gsis[0]["KeySchema"] == [
            {"AttributeName": "city", "KeyType": "HASH"},
            {"AttributeName": "operational_status", "KeyType": "RANGE"},
        ]

    def test_showtimes_table_keys_and_indexes(self, tables):
        """Verify showtimes table primary key (showtime_id) and dual GSIs."""
        schema = tables["test_moviemagic_showtimes"]
        assert schema["KeySchema"] == [{"AttributeName": "showtime_id", "KeyType": "HASH"}]
        gsi_names = {g["IndexName"]: g["KeySchema"] for g in schema.get("GlobalSecondaryIndexes", [])}
        assert "MovieShowtimeIndex" in gsi_names
        assert "TheaterShowtimeIndex" in gsi_names
        assert gsi_names["MovieShowtimeIndex"] == [
            {"AttributeName": "movie_id", "KeyType": "HASH"},
            {"AttributeName": "date_time", "KeyType": "RANGE"},
        ]
        assert gsi_names["TheaterShowtimeIndex"] == [
            {"AttributeName": "theater_id", "KeyType": "HASH"},
            {"AttributeName": "date_time", "KeyType": "RANGE"},
        ]

    def test_bookings_table_keys_and_indexes(self, tables):
        """Verify bookings table primary key (booking_id) and UserBookingsIndex GSI."""
        schema = tables["test_moviemagic_bookings"]
        assert schema["KeySchema"] == [{"AttributeName": "booking_id", "KeyType": "HASH"}]
        gsis = schema.get("GlobalSecondaryIndexes", [])
        assert len(gsis) == 1
        assert gsis[0]["IndexName"] == "UserBookingsIndex"
        assert gsis[0]["KeySchema"] == [
            {"AttributeName": "user_id", "KeyType": "HASH"},
            {"AttributeName": "created_at", "KeyType": "RANGE"},
        ]

    def test_show_seats_table_atomic_composite_keys(self, tables):
        """Verify atomic concurrency seat table composite key (show_key + seat_code)."""
        schema = tables["test_moviemagic_show_seats"]
        assert schema["KeySchema"] == [
            {"AttributeName": "show_key", "KeyType": "HASH"},
            {"AttributeName": "seat_code", "KeyType": "RANGE"},
        ]


class TestSchemaInspector:
    """Test the schema inspection and difference detection logic."""

    def test_matching_schema_returns_true(self):
        """Exact match should report is_match=True with empty mismatches list."""
        definition = {
            "KeySchema": [{"AttributeName": "movie_id", "KeyType": "HASH"}],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "CategoryIndex",
                    "KeySchema": [
                        {"AttributeName": "category", "KeyType": "HASH"},
                        {"AttributeName": "release_year", "KeyType": "RANGE"},
                    ],
                }
            ],
            "BillingMode": "PAY_PER_REQUEST",
        }
        actual = {
            "KeySchema": [{"AttributeName": "movie_id", "KeyType": "HASH"}],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "CategoryIndex",
                    "KeySchema": [
                        {"AttributeName": "category", "KeyType": "HASH"},
                        {"AttributeName": "release_year", "KeyType": "RANGE"},
                    ],
                }
            ],
            "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"},
        }
        is_match, mismatches = inspect_table_schema(definition, actual)
        assert is_match is True
        assert len(mismatches) == 0

    def test_detects_keyschema_mismatch(self):
        """Detects difference in table Primary Key schema."""
        expected = {"KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}]}
        actual = {"KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}]}
        is_match, mismatches = inspect_table_schema(expected, actual)
        assert is_match is False
        assert any("KeySchema mismatch" in m for m in mismatches)

    def test_detects_missing_gsi(self):
        """Detects missing Global Secondary Index."""
        expected = {
            "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}],
            "GlobalSecondaryIndexes": [
                {"IndexName": "EmailIndex", "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}]}
            ],
        }
        actual = {
            "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}],
            "GlobalSecondaryIndexes": [],
        }
        is_match, mismatches = inspect_table_schema(expected, actual)
        assert is_match is False
        assert any("Missing GSI: EmailIndex" in m for m in mismatches)

    def test_detects_billing_mode_mismatch(self):
        """Detects table provisioned with incorrect billing mode."""
        expected = {
            "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
            "BillingMode": "PAY_PER_REQUEST",
        }
        actual = {
            "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
            "BillingModeSummary": {"BillingMode": "PROVISIONED"},
        }
        is_match, mismatches = inspect_table_schema(expected, actual)
        assert is_match is False
        assert any("BillingMode mismatch" in m for m in mismatches)


class TestTableCreationAndChecking:
    """Test check_tables and create_tables functions with mock boto3 client."""

    def test_check_tables_detects_nonexistent_table(self):
        """check_tables marks table as NOT_FOUND when describe_table raises ResourceNotFoundException."""
        mock_client = MagicMock()
        mock_client.exceptions.ResourceNotFoundException = type(
            "ResourceNotFoundException", (Exception,), {}
        )
        mock_client.describe_table.side_effect = mock_client.exceptions.ResourceNotFoundException

        tables = {"test_table": {"KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}]}}
        report = check_tables(mock_client, tables)

        assert "test_table" in report
        assert report["test_table"]["exists"] is False
        assert report["test_table"]["status"] == "NOT_FOUND"

    def test_create_tables_calls_client_create_when_missing(self):
        """create_tables calls client.create_table for missing tables."""
        mock_client = MagicMock()
        mock_client.meta.region_name = "ap-south-1"
        mock_client.exceptions.ResourceNotFoundException = type(
            "ResourceNotFoundException", (Exception,), {}
        )
        mock_client.describe_table.side_effect = mock_client.exceptions.ResourceNotFoundException

        tables = {
            "test_table": {
                "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
                "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
                "BillingMode": "PAY_PER_REQUEST",
            }
        }
        success = create_tables(mock_client, tables, wait_for_active=False)
        assert success is True
        mock_client.create_table.assert_called_once_with(
            TableName="test_table",
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )


class TestCatalogueSeedingUtility:
    """Test the data preparation and safety guarantees of seed_dynamodb.py."""

    def test_protected_tables_include_customer_data(self):
        """Customer tables must be strictly protected from seeding."""
        assert "users" in PROTECTED_TABLE_CATEGORIES
        assert "bookings" in PROTECTED_TABLE_CATEGORIES
        assert "show_seats" in PROTECTED_TABLE_CATEGORIES

    def test_to_dynamodb_compatible_converts_floats_to_decimal(self):
        """Floats must be recursively converted to Decimal for DynamoDB serialization."""
        data = {
            "rating": 8.5,
            "cast": ["Actor A", "Actor B"],
            "nested": {"score": 9.2, "count": 10},
        }
        converted = to_dynamodb_compatible(data)
        assert isinstance(converted["rating"], Decimal)
        assert converted["rating"] == Decimal("8.5")
        assert isinstance(converted["nested"]["score"], Decimal)
        assert converted["nested"]["score"] == Decimal("9.2")
        assert converted["nested"]["count"] == 10  # ints unchanged

    def test_prepare_movie_items_has_all_28_titles(self):
        """Verify prepare_movie_items prepares all 28 movies with movie_id primary key."""
        items = prepare_movie_items()
        assert len(items) == 28
        for item in items:
            assert "movie_id" in item
            assert item["movie_id"] == item["id"]
            assert "title" in item
            assert "category" in item
            assert isinstance(item["imdb_score"], Decimal)

    def test_prepare_theater_items_has_all_5_venues(self):
        """Verify prepare_theater_items prepares all 5 Kolhapur venues with theater_id."""
        items = prepare_theater_items()
        assert len(items) == 5
        for item in items:
            assert "theater_id" in item
            assert item["theater_id"] == item["id"]
            assert item["city"] == "Kolhapur"
            assert "operational_status" in item

    def test_prepare_showtime_items_has_separated_schedules(self):
        """Verify demo showtimes are prepared with showtime_id and date_time."""
        items = prepare_showtime_items()
        assert len(items) == 6
        for item in items:
            assert "showtime_id" in item
            assert "movie_id" in item
            assert "theater_id" in item
            assert "date_time" in item
            assert isinstance(item["price"], Decimal)

    def test_seed_table_dry_run_performs_no_writes(self):
        """In dry-run mode (default), seed_table counts actions but does not call put_item."""
        mock_table = MagicMock()
        mock_table.get_item.return_value = {}  # Item not found

        items = [{"movie_id": "mov-1", "title": "Movie 1"}]
        stats = seed_table(mock_table, items, pk_name="movie_id", dry_run=True)

        assert stats["created"] == 1
        assert stats["updated"] == 0
        assert stats["skipped"] == 0
        assert stats["failed"] == 0
        mock_table.put_item.assert_not_called()

    def test_seed_table_skips_identical_records(self):
        """When an identical item already exists in DynamoDB, seed_table skips it."""
        mock_table = MagicMock()
        item = {"movie_id": "mov-1", "title": "Movie 1"}
        mock_table.get_item.return_value = {"Item": item}

        stats = seed_table(mock_table, [item], pk_name="movie_id", dry_run=False)

        assert stats["skipped"] == 1
        assert stats["created"] == 0
        assert stats["updated"] == 0
        mock_table.put_item.assert_not_called()

    def test_seed_table_updates_changed_records(self):
        """When item exists but content differs, seed_table performs update."""
        mock_table = MagicMock()
        existing_item = {"movie_id": "mov-1", "title": "Old Title"}
        new_item = {"movie_id": "mov-1", "title": "Updated Title"}
        mock_table.get_item.return_value = {"Item": existing_item}

        stats = seed_table(mock_table, [new_item], pk_name="movie_id", dry_run=False)

        assert stats["updated"] == 1
        assert stats["created"] == 0
        mock_table.put_item.assert_called_once_with(Item=new_item)
