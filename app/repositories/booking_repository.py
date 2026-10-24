"""Booking & Seat Reservation Repository layer supporting In-Memory (Mock) and DynamoDB.

Features:
- Atomic seat reservation and booking persistence via DynamoDB TransactWriteItems.
- Strict concurrency protection: prevents two users from reserving the same seat.
- GSI UserBookingsIndex on moviemagic_bookings (user_id + created_at) for efficient user history.
- Direct partition key queries on moviemagic_show_seats (show_key + seat_code).
- Safe Decimal conversion for price and ticket count fields.
- Strict anti-degradation rule: USE_AWS_MOCK=False never silently falls back to mock.
- Transparent BookingRepositoryProxy preserving backward-compatible booking_repository imports.
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

from app.aws.client_factory import get_boto3_client, is_mock_mode_active
from .base import BaseRepository

logger = logging.getLogger(__name__)
_deserializer = TypeDeserializer()
_serializer = TypeSerializer()


class DuplicateSeatError(ValueError):
    """Raised when one or more requested seats have already been reserved."""
    pass


class BookingPersistenceError(RuntimeError):
    """Raised when booking or seat reservation fails due to a database/service error."""
    pass


def clean_dynamodb_value(val: Any) -> Any:
    """Recursively convert DynamoDB Decimal types to native int or float."""
    if isinstance(val, Decimal):
        if val % 1 == 0:
            return int(val)
        return float(val)
    elif isinstance(val, list):
        return [clean_dynamodb_value(x) for x in val]
    elif isinstance(val, dict):
        return {k: clean_dynamodb_value(v) for k, v in val.items()}
    return val


def deserialize_dynamodb_item(raw_item: Dict[str, Any], id_key: str = "id") -> Dict[str, Any]:
    """Convert low-level DynamoDB typed item into standard Python dictionary."""
    if not raw_item:
        return {}
    item = {k: clean_dynamodb_value(_deserializer.deserialize(v)) for k, v in raw_item.items()}
    if id_key in item and "id" not in item:
        item["id"] = item[id_key]
    elif "id" in item and id_key not in item:
        item[id_key] = item["id"]
    return item


def to_dynamodb_compatible(obj: Any) -> Any:
    """Recursively convert Python float values to Decimal for DynamoDB serialization."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: to_dynamodb_compatible(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [to_dynamodb_compatible(i) for i in obj]
    return obj


def serialize_dynamodb_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Convert standard Python dictionary into low-level DynamoDB typed item."""
    compat_item = to_dynamodb_compatible(item)
    return {k: _serializer.serialize(v) for k, v in compat_item.items()}


def execute_paginated_scan(client, table_name: str, **kwargs) -> List[Dict[str, Any]]:
    """Scan a table handling DynamoDB pagination safely."""
    items = []
    scan_kwargs = dict(kwargs)
    scan_kwargs["TableName"] = table_name

    while True:
        resp = client.scan(**scan_kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key
    return items


class InMemoryBookingRepository(BaseRepository):
    """Booking and seat reservation in-memory repository for local development and testing."""

    def __init__(self):
        self._bookings: Dict[str, Dict[str, Any]] = {}
        self._occupied_seats: Dict[str, Set[str]] = {}
        self._seed_sample_bookings()

    def _get_show_key(self, movie_id: str, theater_id: str, showtime: str) -> str:
        return f"{movie_id}#{theater_id}#{showtime}"

    def _seed_sample_bookings(self):
        """Seed initial realistic booked seats and demo booking record."""
        # Pre-reserve seats for Pushpa 2 at PVR DYP City Mall, Kolhapur
        key1 = self._get_show_key("mov-south-1", "th-pvr-dyp", "10:30 AM")
        self._occupied_seats[key1] = {"A4", "A5", "C6", "C7", "D3"}

        # Legacy demo key support for test fixtures
        key_legacy = self._get_show_key("mov-1", "th-1", "10:30 AM")
        self._occupied_seats[key_legacy] = {"A4", "A5", "C6", "C7", "D3"}

        sample_booking = {
            "id": "MM-2026-DEMO-001",
            "booking_id": "MM-2026-DEMO-001",
            "user_id": "usr-demo-1",
            "user_email": "demo@moviemagic.com",
            "movie_id": "mov-south-1",
            "movie_title": "Pushpa 2: The Rule",
            "theater_id": "th-pvr-dyp",
            "theater_name": "PVR DYP City Mall (Kolhapur)",
            "showtime": "10:30 AM",
            "show_date": "Today",
            "seats": ["A4", "A5"],
            "tier": "VIP",
            "ticket_count": 2,
            "total_price": 640.00,
            "status": "CONFIRMED (DEMO)",
            "is_demo": True,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }
        self._bookings[sample_booking["id"]] = sample_booking

    def get_by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self._bookings.get(str(item_id).strip() if item_id else "")

    def get_all(self) -> List[Dict[str, Any]]:
        return sorted(
            list(self._bookings.values()),
            key=lambda x: x.get("created_at", ""),
            reverse=True,
        )

    def get_by_user_id(self, user_id: str) -> List[Dict[str, Any]]:
        clean_uid = str(user_id).strip() if user_id else ""
        return sorted(
            [b for b in self._bookings.values() if b.get("user_id") == clean_uid],
            key=lambda x: x.get("created_at", ""),
            reverse=True,
        )

    def get_booked_seats(self, movie_id: str, theater_id: str, showtime: str) -> List[str]:
        key = self._get_show_key(movie_id, theater_id, showtime)
        return sorted(list(self._occupied_seats.get(key, set())))

    def create_booking(
        self,
        user_id: str,
        user_email: str,
        movie_id: str,
        movie_title: str,
        theater_id: str,
        theater_name: str,
        showtime: str,
        show_date: str,
        seats: List[str],
        tier: str,
        total_price: float,
    ) -> Dict[str, Any]:
        """Create and record a booking in memory."""
        show_key = self._get_show_key(movie_id, theater_id, showtime)
        if show_key not in self._occupied_seats:
            self._occupied_seats[show_key] = set()

        # Check for seat collision
        for seat in seats:
            if seat in self._occupied_seats[show_key]:
                raise DuplicateSeatError(f"Seat {seat} has already been reserved. Please choose another seat.")

        # Mark seats as reserved
        for seat in seats:
            self._occupied_seats[show_key].add(seat)

        booking_id = f"MM-2026-{uuid.uuid4().hex[:6].upper()}"
        booking = {
            "id": booking_id,
            "booking_id": booking_id,
            "user_id": user_id,
            "user_email": user_email,
            "movie_id": movie_id,
            "movie_title": movie_title,
            "theater_id": theater_id,
            "theater_name": theater_name,
            "showtime": showtime,
            "show_date": show_date,
            "seats": seats,
            "tier": tier,
            "ticket_count": len(seats),
            "total_price": total_price,
            "status": "CONFIRMED (DEMO)",
            "is_demo": True,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }
        self._bookings[booking_id] = booking
        return booking


class DynamoDBBookingRepository(BaseRepository):
    """DynamoDB repository for bookings and atomic seat reservation concurrency."""

    def __init__(
        self,
        client: Optional[Any] = None,
        table_prefix: Optional[str] = None,
    ):
        self.client = client
        prefix = table_prefix or os.environ.get("DYNAMODB_TABLE_PREFIX", "moviemagic_")
        self.bookings_table = f"{prefix}bookings"
        self.show_seats_table = f"{prefix}show_seats"

    def _get_show_key(self, movie_id: str, theater_id: str, showtime: str) -> str:
        return f"{movie_id}#{theater_id}#{showtime}"

    def _ensure_client(self):
        """Ensure client is present or initialize via factory."""
        if not self.client:
            self.client = get_boto3_client("dynamodb")
            if not self.client:
                raise RuntimeError(
                    "Configuration Error: USE_AWS_MOCK is set to False, but AWS DynamoDB client "
                    "could not be initialized. Check AWS credentials (AWS_PROFILE, IAM role, or env vars) "
                    "and AWS_REGION. Silent fallback to in-memory mock is prohibited."
                )

    def get_by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        self._ensure_client()
        if not item_id:
            return None
        clean_id = str(item_id).strip()
        try:
            resp = self.client.get_item(
                TableName=self.bookings_table,
                Key={"booking_id": {"S": clean_id}},
            )
            raw = resp.get("Item")
            if not raw:
                return None
            return deserialize_dynamodb_item(raw, id_key="booking_id")
        except ClientError as e:
            logger.error("DynamoDB get_by_id error for booking %s: %s", clean_id, e)
            raise BookingPersistenceError(f"Database error retrieving booking: {e}")

    def get_all(self) -> List[Dict[str, Any]]:
        self._ensure_client()
        try:
            raw_items = execute_paginated_scan(self.client, self.bookings_table)
            bookings = [deserialize_dynamodb_item(i, id_key="booking_id") for i in raw_items]
            return sorted(
                bookings,
                key=lambda x: x.get("created_at", ""),
                reverse=True,
            )
        except ClientError as e:
            logger.error("DynamoDB get_all bookings error: %s", e)
            raise BookingPersistenceError(f"Database error retrieving all bookings: {e}")

    def get_by_user_id(self, user_id: str) -> List[Dict[str, Any]]:
        self._ensure_client()
        if not user_id:
            return []
        clean_uid = str(user_id).strip()
        try:
            resp = self.client.query(
                TableName=self.bookings_table,
                IndexName="UserBookingsIndex",
                KeyConditionExpression="user_id = :uid",
                ExpressionAttributeValues={":uid": {"S": clean_uid}},
                ScanIndexForward=False,  # Reverse chronological order (latest bookings first)
            )
            items = resp.get("Items", [])
            return [deserialize_dynamodb_item(i, id_key="booking_id") for i in items]
        except ClientError as e:
            logger.error("DynamoDB get_by_user_id error for user %s: %s", clean_uid, e)
            raise BookingPersistenceError(f"Database error retrieving user bookings: {e}")

    def get_booked_seats(self, movie_id: str, theater_id: str, showtime: str) -> List[str]:
        self._ensure_client()
        show_key = self._get_show_key(movie_id, theater_id, showtime)
        try:
            resp = self.client.query(
                TableName=self.show_seats_table,
                KeyConditionExpression="show_key = :sk",
                ExpressionAttributeValues={":sk": {"S": show_key}},
                ProjectionExpression="seat_code",
            )
            items = resp.get("Items", [])
            deserialized = [deserialize_dynamodb_item(i, id_key="seat_code") for i in items]
            return sorted([i.get("seat_code") for i in deserialized if i.get("seat_code")])
        except ClientError as e:
            logger.error("DynamoDB get_booked_seats error for %s: %s", show_key, e)
            raise BookingPersistenceError(f"Database error retrieving booked seats: {e}")

    def create_booking(
        self,
        user_id: str,
        user_email: str,
        movie_id: str,
        movie_title: str,
        theater_id: str,
        theater_name: str,
        showtime: str,
        show_date: str,
        seats: List[str],
        tier: str,
        total_price: float,
    ) -> Dict[str, Any]:
        """Atomically persist booking and reserve seats via DynamoDB TransactWriteItems."""
        self._ensure_client()

        if not seats:
            raise ValueError("Please select at least one seat to proceed.")
        if len(seats) > 10:
            raise ValueError("Maximum 10 seats allowed per booking.")
        if len(seats) != len(set(seats)):
            raise ValueError("Duplicate seat selection detected in request.")

        show_key = self._get_show_key(movie_id, theater_id, showtime)
        booking_id = f"MM-2026-{uuid.uuid4().hex[:6].upper()}"
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        booking = {
            "id": booking_id,
            "booking_id": booking_id,
            "user_id": user_id,
            "user_email": user_email,
            "movie_id": movie_id,
            "movie_title": movie_title,
            "theater_id": theater_id,
            "theater_name": theater_name,
            "showtime": showtime,
            "show_date": show_date,
            "seats": seats,
            "tier": tier,
            "ticket_count": len(seats),
            "total_price": total_price,
            "status": "CONFIRMED (DEMO)",
            "is_demo": True,
            "created_at": created_at,
        }

        # TransactItems:
        # Item 0: Booking Record in moviemagic_bookings
        transact_items = [
            {
                "Put": {
                    "TableName": self.bookings_table,
                    "Item": serialize_dynamodb_item(booking),
                    "ConditionExpression": "attribute_not_exists(booking_id)",
                }
            }
        ]

        # Items 1..N: Seat Reservation Locks in moviemagic_show_seats
        for seat in seats:
            seat_item = {
                "show_key": show_key,
                "seat_code": seat,
                "booking_id": booking_id,
                "user_id": user_id,
                "reserved_at": created_at,
            }
            transact_items.append({
                "Put": {
                    "TableName": self.show_seats_table,
                    "Item": serialize_dynamodb_item(seat_item),
                    "ConditionExpression": "attribute_not_exists(show_key) AND attribute_not_exists(seat_code)",
                }
            })

        try:
            self.client.transact_write_items(TransactItems=transact_items)
            return booking
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code == "TransactionCanceledException":
                reasons = e.response.get("CancellationReasons", [])
                # Inspect seat items (index 1..N)
                for idx, r in enumerate(reasons[1:], start=1):
                    if r.get("Code") == "ConditionalCheckFailed":
                        colliding_seat = seats[idx - 1]
                        raise DuplicateSeatError(
                            f"Seat {colliding_seat} has already been reserved. Please choose another seat."
                        )
                if not reasons and "ConditionalCheckFailed" in str(e):
                    raise DuplicateSeatError(
                        "One or more selected seats have already been reserved. Please choose another seat."
                    )
            logger.error("DynamoDB create_booking transaction failed with code %s: %s", error_code, e)
            raise BookingPersistenceError(f"Failed to complete booking reservation: {error_code}")


_in_memory_instance: Optional[InMemoryBookingRepository] = None
_dynamo_instance: Optional[DynamoDBBookingRepository] = None


def get_booking_repository() -> BaseRepository:
    """Resolve booking repository according to active configuration.

    Guarantees:
    - If USE_AWS_MOCK is True, returns InMemoryBookingRepository singleton.
    - If USE_AWS_MOCK is False, returns DynamoDBBookingRepository.
    - NEVER silently degrades to mock mode if live mode is misconfigured.
    """
    global _in_memory_instance, _dynamo_instance

    if is_mock_mode_active():
        if _in_memory_instance is None:
            _in_memory_instance = InMemoryBookingRepository()
        return _in_memory_instance

    # Live DynamoDB requested: ensure client is initializable
    client = get_boto3_client("dynamodb")
    if not client:
        raise RuntimeError(
            "Configuration Error: USE_AWS_MOCK is set to False, but AWS DynamoDB client "
            "could not be initialized. Check AWS credentials (AWS_PROFILE, IAM role, or env vars) "
            "and AWS_REGION. Silent fallback to in-memory mock is prohibited."
        )

    if _dynamo_instance is None or _dynamo_instance.client is not client:
        _dynamo_instance = DynamoDBBookingRepository(client=client)
    return _dynamo_instance


class BookingRepositoryProxy(BaseRepository):
    """Transparent proxy delegating calls to the active BookingRepository."""

    @property
    def active_repo(self) -> BaseRepository:
        return get_booking_repository()

    def get_by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self.active_repo.get_by_id(item_id)

    def get_all(self) -> List[Dict[str, Any]]:
        return self.active_repo.get_all()

    def get_by_user_id(self, user_id: str) -> List[Dict[str, Any]]:
        return self.active_repo.get_by_user_id(user_id)

    def get_booked_seats(self, movie_id: str, theater_id: str, showtime: str) -> List[str]:
        return self.active_repo.get_booked_seats(movie_id, theater_id, showtime)

    def create_booking(
        self,
        user_id: str,
        user_email: str,
        movie_id: str,
        movie_title: str,
        theater_id: str,
        theater_name: str,
        showtime: str,
        show_date: str,
        seats: List[str],
        tier: str,
        total_price: float,
    ) -> Dict[str, Any]:
        return self.active_repo.create_booking(
            user_id=user_id,
            user_email=user_email,
            movie_id=movie_id,
            movie_title=movie_title,
            theater_id=theater_id,
            theater_name=theater_name,
            showtime=showtime,
            show_date=show_date,
            seats=seats,
            tier=tier,
            total_price=total_price,
        )


booking_repository = BookingRepositoryProxy()
BookingRepository = InMemoryBookingRepository  # Backward compatibility alias
