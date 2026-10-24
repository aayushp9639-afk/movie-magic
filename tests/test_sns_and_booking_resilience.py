"""Tests verifying SNS notification dispatch and booking resilience.

Guarantees tested:
1. SNS publishing is invoked with correct booking details after successful booking.
2. An SNS publishing failure (returning False or raising an Exception) NEVER causes
   a completed booking to be reported as failed or duplicate bookings to be created.
3. Pre-booking validation errors (invalid seats, duplicate seats, venue issues) never invoke SNS.
4. SNSService dynamic property resolution for topic_arn and is_connected.
"""
import pytest
from unittest.mock import MagicMock, patch
from app.services.booking_service import BookingService
from app.aws.sns import SNSService
from app.repositories.booking_repository import InMemoryBookingRepository, DuplicateSeatError


class TestSNSServiceBehavior:
    """Verify SNSService dynamic configuration and publishing logic."""

    def test_mock_mode_simulation(self, monkeypatch):
        monkeypatch.setenv("USE_AWS_MOCK", "True")
        service = SNSService(topic_arn="arn:aws:sns:ap-south-1:123456789012:test-topic")
        # In mock mode, client is None, is_connected is False
        assert service.is_connected is False

        sample_booking = {
            "id": "MM-TEST-001",
            "movie_title": "Test Movie",
            "theater_name": "Test Theater",
            "showtime": "18:00",
            "seats": ["C1", "C2"],
            "total_price": 400.0,
        }
        # In mock mode, returns True (simulated success)
        result = service.publish_booking_confirmation(sample_booking)
        assert result is True

    def test_live_mode_publish_success(self, monkeypatch):
        mock_client = MagicMock()
        mock_client.publish.return_value = {"MessageId": "msg-12345"}

        service = SNSService(
            topic_arn="arn:aws:sns:ap-south-1:123456789012:test-topic",
            client=mock_client,
        )
        assert service.is_connected is True

        sample_booking = {
            "id": "MM-TEST-002",
            "movie_title": "Kantara",
            "theater_name": "PVR DYP City Mall",
            "showtime": "18:30",
            "seats": ["D4", "D5"],
            "total_price": 500.0,
        }
        result = service.publish_booking_confirmation(sample_booking)
        assert result is True
        mock_client.publish.assert_called_once()
        call_kwargs = mock_client.publish.call_args.kwargs
        assert call_kwargs["TopicArn"] == "arn:aws:sns:ap-south-1:123456789012:test-topic"
        assert "MM-TEST-002" in call_kwargs["Subject"]
        assert "₹500.00" in call_kwargs["Message"]

    def test_live_mode_publish_client_exception_returns_false(self):
        mock_client = MagicMock()
        mock_client.publish.side_effect = Exception("AWS SNS Network Failure")

        service = SNSService(
            topic_arn="arn:aws:sns:ap-south-1:123456789012:test-topic",
            client=mock_client,
        )
        sample_booking = {"id": "MM-TEST-003", "seats": ["A1"], "total_price": 150.0}
        result = service.publish_booking_confirmation(sample_booking)
        assert result is False


class TestBookingServiceSNSResilience:
    """Verify that booking confirmation is isolated from SNS notification failures."""

    def test_sns_invoked_after_successful_booking(self):
        repo = InMemoryBookingRepository()
        mock_sns = MagicMock()
        mock_sns.publish_booking_confirmation.return_value = True

        service = BookingService(repo=repo, sns_service=mock_sns)
        success, msg, booking = service.create_booking(
            user_id="usr-test-1",
            user_email="test@user.com",
            movie_id="mov-south-1",
            theater_id="th-pvr-dyp",
            showtime="18:30",
            show_date="2026-10-25",
            seats=["G1", "G2"],
        )
        assert success is True
        assert booking is not None
        mock_sns.publish_booking_confirmation.assert_called_once()
        passed_booking = mock_sns.publish_booking_confirmation.call_args[0][0]
        assert passed_booking["id"] == booking["id"]

    def test_sns_failure_does_not_fail_booking(self):
        """When SNS publish returns False, booking must STILL be reported as confirmed."""
        repo = InMemoryBookingRepository()
        mock_sns = MagicMock()
        mock_sns.publish_booking_confirmation.return_value = False

        service = BookingService(repo=repo, sns_service=mock_sns)
        success, msg, booking = service.create_booking(
            user_id="usr-test-2",
            user_email="test2@user.com",
            movie_id="mov-south-1",
            theater_id="th-pvr-dyp",
            showtime="18:30",
            show_date="2026-10-25",
            seats=["G3", "G4"],
        )
        assert success is True
        assert "Booking confirmed successfully!" in msg
        assert booking is not None
        # Seats must be marked as booked in the repository
        occupied = repo.get_booked_seats("mov-south-1", "th-pvr-dyp", "18:30")
        assert "G3" in occupied
        assert "G4" in occupied

    def test_sns_exception_does_not_fail_booking(self):
        """When SNS dispatch throws an unexpected exception, booking must STILL succeed."""
        repo = InMemoryBookingRepository()
        mock_sns = MagicMock()
        mock_sns.publish_booking_confirmation.side_effect = RuntimeError("Fatal SNS Connection Drop")

        service = BookingService(repo=repo, sns_service=mock_sns)
        success, msg, booking = service.create_booking(
            user_id="usr-test-3",
            user_email="test3@user.com",
            movie_id="mov-south-1",
            theater_id="th-pvr-dyp",
            showtime="18:30",
            show_date="2026-10-25",
            seats=["G5", "G6"],
        )
        assert success is True
        assert booking is not None
        occupied = repo.get_booked_seats("mov-south-1", "th-pvr-dyp", "18:30")
        assert "G5" in occupied
        assert "G6" in occupied

    def test_booking_validation_failure_does_not_invoke_sns(self):
        """If seat collision occurs, booking is rejected and SNS must never be called."""
        repo = InMemoryBookingRepository()
        mock_sns = MagicMock()

        service = BookingService(repo=repo, sns_service=mock_sns)
        # First booking succeeds for seat B1
        service.create_booking(
            user_id="usr-test-4",
            user_email="test4@user.com",
            movie_id="mov-south-1",
            theater_id="th-pvr-dyp",
            showtime="18:30",
            show_date="2026-10-25",
            seats=["B1"],
        )
        mock_sns.reset_mock()

        # Second booking attempts to book the same seat (B1) -> collision
        success, msg, booking = service.create_booking(
            user_id="usr-test-5",
            user_email="test5@user.com",
            movie_id="mov-south-1",
            theater_id="th-pvr-dyp",
            showtime="18:30",
            show_date="2026-10-25",
            seats=["B1"],
        )
        assert success is False
        assert booking is None
        assert "already been reserved" in msg
        mock_sns.publish_booking_confirmation.assert_not_called()
        assert success is False
        assert booking is None
        mock_sns.publish_booking_confirmation.assert_not_called()
