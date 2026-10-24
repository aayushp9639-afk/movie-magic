"""Unit tests for DynamoDB Booking Repository, atomic seat concurrency, and authorization.

Verifies:
- Atomic booking creation and seat reservations via DynamoDB TransactWriteItems
- Strict duplicate seat collision prevention (mapping conditional check failures to DuplicateSeatError)
- Server-side price calculation and validation (rejecting >10 seats, duplicates, invalid syntax)
- UserBookingsIndex GSI query for user booking history
- Direct partition key query on moviemagic_show_seats for occupied seats
- Ownership access control: users can only view their own bookings, admins can view any
- Strict anti-degradation rule: USE_AWS_MOCK=False raises RuntimeError if misconfigured
- Zero live AWS calls (all AWS interactions mocked)
"""

from unittest.mock import MagicMock, patch
import pytest
from botocore.exceptions import ClientError

from app.repositories.booking_repository import (
    InMemoryBookingRepository,
    DynamoDBBookingRepository,
    DuplicateSeatError,
    BookingPersistenceError,
    get_booking_repository,
    BookingRepositoryProxy,
)
from app.services.booking_service import BookingService


class TestDynamoDBBookingOperations:
    """Test DynamoDB booking operations and TransactWriteItems."""

    @pytest.fixture
    def mock_dynamo_client(self):
        return MagicMock()

    @pytest.fixture
    def repo(self, mock_dynamo_client):
        return DynamoDBBookingRepository(client=mock_dynamo_client, table_prefix="moviemagic_")

    def test_create_booking_submits_atomic_transaction(self, repo, mock_dynamo_client):
        """create_booking must submit 1 Booking Put + N Seat Puts in a single transaction."""
        booking = repo.create_booking(
            user_id="usr-123",
            user_email="fan@moviemagic.com",
            movie_id="mov-south-1",
            movie_title="Pushpa 2: The Rule",
            theater_id="th-pvr-dyp",
            theater_name="PVR DYP City Mall",
            showtime="10:30 AM",
            show_date="Today",
            seats=["A1", "A2"],
            tier="VIP",
            total_price=640.00,
        )

        assert booking["id"].startswith("MM-2026-")
        assert booking["user_id"] == "usr-123"
        assert booking["seats"] == ["A1", "A2"]
        assert booking["total_price"] == 640.00

        mock_dynamo_client.transact_write_items.assert_called_once()
        _, kwargs = mock_dynamo_client.transact_write_items.call_args
        items = kwargs["TransactItems"]

        # Item 0: Booking Record
        assert len(items) == 3  # 1 booking + 2 seats
        booking_put = items[0]["Put"]
        assert booking_put["TableName"] == "moviemagic_bookings"
        assert booking_put["ConditionExpression"] == "attribute_not_exists(booking_id)"
        assert booking_put["Item"]["user_id"] == {"S": "usr-123"}

        # Item 1: Seat A1 in moviemagic_show_seats
        seat1_put = items[1]["Put"]
        assert seat1_put["TableName"] == "moviemagic_show_seats"
        assert seat1_put["ConditionExpression"] == "attribute_not_exists(show_key) AND attribute_not_exists(seat_code)"
        assert seat1_put["Item"]["seat_code"] == {"S": "A1"}
        assert seat1_put["Item"]["show_key"] == {"S": "mov-south-1#th-pvr-dyp#10:30 AM"}

        # Item 2: Seat A2 in moviemagic_show_seats
        seat2_put = items[2]["Put"]
        assert seat2_put["TableName"] == "moviemagic_show_seats"
        assert seat2_put["Item"]["seat_code"] == {"S": "A2"}

    def test_duplicate_seat_raises_duplicate_seat_error(self, repo, mock_dynamo_client):
        """When seat conditional check fails, raises DuplicateSeatError identifying the seat."""
        error_response = {
            "Error": {"Code": "TransactionCanceledException"},
            "CancellationReasons": [
                {"Code": "None"},                     # Booking Put
                {"Code": "ConditionalCheckFailed"},   # Seat B1 Put
            ],
        }
        mock_dynamo_client.transact_write_items.side_effect = ClientError(
            error_response, "TransactWriteItems"
        )

        with pytest.raises(DuplicateSeatError) as exc_info:
            repo.create_booking(
                user_id="usr-1",
                user_email="test@test.com",
                movie_id="mov-1",
                movie_title="Title",
                theater_id="th-1",
                theater_name="Venue",
                showtime="10:30 AM",
                show_date="Today",
                seats=["B1"],
                tier="VIP",
                total_price=320.00,
            )
        assert "Seat B1 has already been reserved" in str(exc_info.value)

    def test_transaction_conflict_raises_persistence_error(self, repo, mock_dynamo_client):
        """When a non-seat conflict occurs, raises BookingPersistenceError, not DuplicateSeatError."""
        error_response = {
            "Error": {"Code": "TransactionConflict"},
        }
        mock_dynamo_client.transact_write_items.side_effect = ClientError(
            error_response, "TransactWriteItems"
        )

        with pytest.raises(BookingPersistenceError):
            repo.create_booking(
                user_id="usr-1",
                user_email="test@test.com",
                movie_id="mov-1",
                movie_title="Title",
                theater_id="th-1",
                theater_name="Venue",
                showtime="10:30 AM",
                show_date="Today",
                seats=["B1"],
                tier="VIP",
                total_price=320.00,
            )

    def test_get_booked_seats_queries_show_seats_table(self, repo, mock_dynamo_client):
        """get_booked_seats queries moviemagic_show_seats with show_key."""
        mock_dynamo_client.query.return_value = {
            "Items": [
                {"seat_code": {"S": "A1"}},
                {"seat_code": {"S": "A2"}},
                {"seat_code": {"S": "C4"}},
            ]
        }
        seats = repo.get_booked_seats("mov-1", "th-1", "10:30 AM")
        assert seats == ["A1", "A2", "C4"]

        mock_dynamo_client.query.assert_called_once_with(
            TableName="moviemagic_show_seats",
            KeyConditionExpression="show_key = :sk",
            ExpressionAttributeValues={":sk": {"S": "mov-1#th-1#10:30 AM"}},
            ProjectionExpression="seat_code",
        )

    def test_get_by_user_id_queries_user_bookings_index(self, repo, mock_dynamo_client):
        """get_by_user_id queries UserBookingsIndex GSI with user_id."""
        mock_dynamo_client.query.return_value = {
            "Items": [
                {
                    "booking_id": {"S": "MM-2026-001"},
                    "user_id": {"S": "usr-123"},
                    "movie_title": {"S": "Pushpa 2"},
                    "total_price": {"N": "640"},
                }
            ]
        }
        bookings = repo.get_by_user_id("usr-123")
        assert len(bookings) == 1
        assert bookings[0]["id"] == "MM-2026-001"
        assert bookings[0]["total_price"] == 640.0

        mock_dynamo_client.query.assert_called_once_with(
            TableName="moviemagic_bookings",
            IndexName="UserBookingsIndex",
            KeyConditionExpression="user_id = :uid",
            ExpressionAttributeValues={":uid": {"S": "usr-123"}},
            ScanIndexForward=False,
        )


class TestBookingServiceValidationAndPricing:
    """Test server-side validation and pricing guards in BookingService."""

    def test_max_seat_limit_rejected(self):
        service = BookingService()
        seats_11 = [f"A{i}" for i in range(1, 11)] + ["B1"]
        success, msg, _ = service.create_booking(
            user_id="usr-1",
            user_email="test@test.com",
            movie_id="mov-south-1",
            theater_id="th-pvr-dyp",
            showtime="10:30 AM",
            show_date="Today",
            seats=seats_11,
        )
        assert success is False
        assert "maximum of 10 seats" in msg

    def test_duplicate_seats_in_request_rejected(self):
        service = BookingService()
        success, msg, _ = service.create_booking(
            user_id="usr-1",
            user_email="test@test.com",
            movie_id="mov-south-1",
            theater_id="th-pvr-dyp",
            showtime="10:30 AM",
            show_date="Today",
            seats=["A1", "A1"],
        )
        assert success is False
        assert "Duplicate seat" in msg

    def test_invalid_seat_code_syntax_rejected(self):
        service = BookingService()
        success, msg, _ = service.create_booking(
            user_id="usr-1",
            user_email="test@test.com",
            movie_id="mov-south-1",
            theater_id="th-pvr-dyp",
            showtime="10:30 AM",
            show_date="Today",
            seats=["Z99"],
        )
        assert success is False
        assert "Invalid seat identifier" in msg

    def test_server_calculates_price_strictly(self):
        """Server-side calculate_total returns exact tiered pricing."""
        service = BookingService()
        # Row A (VIP: 320) + Row C (Gold: 220) + Row F (Silver: 160) = 700.00
        total, tier_summary = service.calculate_total(["A1", "C1", "F1"])
        assert total == 700.00
        assert "Gold" in tier_summary
        assert "Silver" in tier_summary
        assert "VIP" in tier_summary


class TestBookingAuthorizationOwnership:
    """Verify ownership access control on booking confirmation."""

    def test_owner_can_view_own_confirmation(self, auth_client):
        """Logged-in user usr-demo-1 can view their own pre-seeded demo booking."""
        response = auth_client.get("/book/confirmation/MM-2026-DEMO-001")
        assert response.status_code == 200
        assert b"RESERVATION CONFIRMED" in response.data

    def test_other_user_cannot_view_foreign_confirmation(self, client):
        """User A cannot view User B's booking (403 Forbidden)."""
        with client.session_transaction() as sess:
            sess["user_id"] = "usr-intruder-99"
            sess["user_email"] = "intruder@bad.com"
            sess["user_name"] = "Intruder"
            sess["user_role"] = "user"

        response = client.get("/book/confirmation/MM-2026-DEMO-001")
        assert response.status_code == 403

    def test_admin_can_view_any_confirmation(self, admin_client):
        """Admin user can view any user's booking confirmation."""
        response = admin_client.get("/book/confirmation/MM-2026-DEMO-001")
        assert response.status_code == 200
        assert b"RESERVATION CONFIRMED" in response.data


class TestConfigurationAndAntiDegradation:
    """Verify repository selection and strict anti-degradation rule."""

    def test_mock_mode_active_returns_in_memory_repository(self, monkeypatch):
        monkeypatch.setenv("USE_AWS_MOCK", "True")
        repo = get_booking_repository()
        assert isinstance(repo, InMemoryBookingRepository)
        assert repo.get_by_id("MM-2026-DEMO-001") is not None

    def test_live_mode_misconfiguration_raises_runtime_error(self, monkeypatch):
        """When USE_AWS_MOCK=False but client cannot be initialized, raise RuntimeError."""
        monkeypatch.setenv("USE_AWS_MOCK", "False")
        with patch("app.repositories.booking_repository.get_boto3_client", return_value=None):
            with pytest.raises(RuntimeError) as exc_info:
                get_booking_repository()
            assert "Silent fallback to in-memory mock is prohibited" in str(exc_info.value)

    def test_booking_repository_proxy_delegation(self):
        proxy = BookingRepositoryProxy()
        # In default mock mode, delegates to InMemoryBookingRepository
        sample = proxy.get_by_id("MM-2026-DEMO-001")
        assert sample is not None
        assert sample["user_id"] == "usr-demo-1"
