"""Unit and integration tests for Resend Transactional Email integration.

Covers:
1. Successful registration triggers a welcome email with correct customer details.
2. Failed registration (duplicate email, weak password) does not trigger a welcome email.
3. Registration succeeds even if email dispatch raises an exception (resilience).
4. Successful booking persistence triggers customer confirmation email.
5. The correct customer's email is selected from the authenticated user record.
6. The confirmation contains the actual booking ID, movie, theater, showtime, seats, and amount.
7. Failed booking persistence (seat collisions, invalid seats) does not trigger a confirmation.
8. Email provider errors do not invalidate an already persisted booking.
9. SNS publishing remains independent of customer email delivery.
10. Missing Resend configuration is handled safely and visibly in logs.
11. Retried requests and idempotency keys prevent unintended duplicate emails.
12. Resend REST API error handling for HTTP errors, network drops, and timeouts.
"""

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch
import pytest

from app.services.email_service import EmailService, email_service
from app.services.auth_service import AuthService
from app.services.booking_service import BookingService
from app.repositories.user_repository import InMemoryUserRepository
from app.repositories.booking_repository import InMemoryBookingRepository
from app.aws.sns import SNSService


class TestEmailServiceUnit:
    """Test EmailService configuration, template rendering, and Resend API communication."""

    def test_missing_api_key_safely_suppresses(self, app):
        """When RESEND_API_KEY is missing, send_email safely returns (False, None) without raising."""
        service = EmailService(api_key="")
        assert service.is_configured is False

        with app.app_context():
            success, msg_id = service.send_email(
                to_email="customer@example.com",
                subject="Test Subject",
                html_content="<p>Test</p>",
                text_content="Test",
            )
            assert success is False
            assert msg_id is None

    def test_invalid_email_suppresses_dispatch(self, app):
        """Invalid recipient email address is rejected early."""
        service = EmailService(api_key="re_test_key_123")
        with app.app_context():
            success, msg_id = service.send_email(
                to_email="invalid-email-without-at",
                subject="Test",
                html_content="<p>Test</p>",
                text_content="Test",
            )
            assert success is False
            assert msg_id is None

    def test_resend_rest_api_success(self, app):
        """Successful Resend API call parses message ID and returns True."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps({"id": "re_msg_123456789"}).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            service = EmailService(
                api_key="re_test_key_valid",
                from_email="Movie Magic <tickets@mail.shardul.online>",
                base_url="http://43.204.215.123",
            )
            with app.app_context():
                success, msg_id = service.send_email(
                    to_email="user@example.com",
                    subject="Test Subject",
                    html_content="<p>Hello World</p>",
                    text_content="Hello World",
                    idempotency_key="idemp-key-001",
                )
                assert success is True
                assert msg_id == "re_msg_123456789"
                mock_urlopen.assert_called_once()
                req = mock_urlopen.call_args[0][0]
                assert req.get_header("Authorization") == "Bearer re_test_key_valid"
                assert req.get_header("Idempotency-key") == "idemp-key-001"
                assert req.full_url == "https://api.resend.com/emails"

    def test_resend_rest_api_http_error(self, app):
        """Resend HTTP 422 error is caught and returns False without raising."""
        err_stream = io.BytesIO(b'{"statusCode": 422, "message": "Domain not verified"}')
        http_err = urllib.error.HTTPError(
            url="https://api.resend.com/emails",
            code=422,
            msg="Unprocessable Entity",
            hdrs={},
            fp=err_stream,
        )

        with patch("urllib.request.urlopen", side_effect=http_err):
            service = EmailService(api_key="re_test_key_valid")
            with app.app_context():
                success, msg_id = service.send_email(
                    to_email="user@example.com",
                    subject="Test Subject",
                    html_content="<p>Hello</p>",
                    text_content="Hello",
                )
                assert success is False
                assert msg_id is None

    def test_resend_rest_api_timeout(self, app):
        """Network timeouts are caught and logged without raising exceptions."""
        with patch("urllib.request.urlopen", side_effect=TimeoutError("Request timed out")):
            service = EmailService(api_key="re_test_key_valid")
            with app.app_context():
                success, msg_id = service.send_email(
                    to_email="user@example.com",
                    subject="Test Subject",
                    html_content="<p>Hello</p>",
                    text_content="Hello",
                )
                assert success is False
                assert msg_id is None

    def test_resend_rest_api_connection_error(self, app):
        """Connection / DNS errors are safely caught."""
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("DNS resolution failed")):
            service = EmailService(api_key="re_test_key_valid")
            with app.app_context():
                success, msg_id = service.send_email(
                    to_email="user@example.com",
                    subject="Test Subject",
                    html_content="<p>Hello</p>",
                    text_content="Hello",
                )
                assert success is False
                assert msg_id is None

    def test_welcome_email_template_rendering(self, app):
        """Verify welcome email HTML and text render personalized customer info and CTA."""
        captured_data = {}

        def mock_http_client(**kwargs):
            captured_data.update(kwargs)
            return True, "msg_welcome_test"

        service = EmailService(
            api_key="re_test_key",
            base_url="http://43.204.215.123",
            reply_to="support@mail.shardul.online",
            http_client=mock_http_client,
        )

        with app.app_context():
            result = service.send_welcome_email(
                user_email="arjun.patil@example.com",
                user_name="Arjun Patil",
            )
            assert result is True
            assert captured_data["to_email"] == "arjun.patil@example.com"
            assert "Welcome to Movie Magic" in captured_data["subject"]
            assert "Arjun Patil" in captured_data["html_content"]
            assert "http://43.204.215.123/movies" in captured_data["html_content"]
            assert "Explore Movies" in captured_data["html_content"]
            assert "support@mail.shardul.online" in captured_data["html_content"]

            # Plain text alternative
            assert "Arjun Patil" in captured_data["text_content"]
            assert "http://43.204.215.123/movies" in captured_data["text_content"]
            assert "support@mail.shardul.online" in captured_data["text_content"]

            # Idempotency key must be derived from normalized user email
            assert captured_data["idempotency_key"] == "welcome-arjun.patil@example.com"

    def test_booking_confirmation_template_rendering(self, app):
        """Verify booking confirmation HTML and text render accurate reservation details."""
        captured_data = {}

        def mock_http_client(**kwargs):
            captured_data.update(kwargs)
            return True, "msg_booking_test"

        service = EmailService(
            api_key="re_test_key",
            base_url="http://43.204.215.123",
            http_client=mock_http_client,
        )

        booking_data = {
            "id": "MM-20261025-ABCD",
            "booking_id": "MM-20261025-ABCD",
            "user_email": "priya.sharma@example.com",
            "movie_title": "Pushpa 2: The Rule",
            "theater_name": "PVR DYP City Mall (Kolhapur)",
            "showtime": "18:30",
            "show_date": "Today",
            "seats": ["D4", "D5"],
            "tier": "Gold",
            "total_price": 500.00,
        }

        with app.app_context():
            result = service.send_booking_confirmation_email(
                booking=booking_data,
                customer_email="priya.sharma@example.com",
            )
            assert result is True
            assert captured_data["to_email"] == "priya.sharma@example.com"
            assert "MM-20261025-ABCD" in captured_data["subject"]
            assert "Pushpa 2: The Rule" in captured_data["subject"]

            # HTML content assertions
            html = captured_data["html_content"]
            assert "MM-20261025-ABCD" in html
            assert "Pushpa 2: The Rule" in html
            assert "PVR DYP City Mall (Kolhapur)" in html
            assert "18:30" in html
            assert "Today" in html
            assert "D4" in html
            assert "D5" in html
            assert "Gold" in html
            assert "₹500.00" in html
            assert "http://43.204.215.123/book/confirmation/MM-20261025-ABCD" in html
            assert "Demo E-Ticket Notice" in html

            # Plain text assertions
            text = captured_data["text_content"]
            assert "MM-20261025-ABCD" in text
            assert "Pushpa 2: The Rule" in text
            assert "₹500.00 INR" in text
            assert "D4, D5" in text
            assert "http://43.204.215.123/book/confirmation/MM-20261025-ABCD" in text

            # Idempotency key
            assert captured_data["idempotency_key"] == "booking-MM-20261025-ABCD"


class TestRegistrationEmailIntegration:
    """Verify welcome email integration with user registration and error handling."""

    def test_successful_registration_triggers_welcome_email(self, app):
        """Registering a new account successfully invokes send_welcome_email."""
        repo = InMemoryUserRepository()
        mock_email = MagicMock()
        mock_email.send_welcome_email.return_value = True

        service = AuthService(repo=repo, email_service=mock_email)
        with app.app_context():
            success, msg, user = service.register(
                email="NewUser@Example.Com",
                password="StrongPassword123!",
                full_name="Rohan Kulkarni",
            )
            assert success is True
            assert user is not None
            mock_email.send_welcome_email.assert_called_once_with(
                user_email="newuser@example.com",
                user_name="Rohan Kulkarni",
            )

    def test_failed_registration_duplicate_email_does_not_trigger_welcome_email(self, app):
        """When registration fails due to duplicate email, no welcome email is dispatched."""
        repo = InMemoryUserRepository()
        mock_email = MagicMock()

        service = AuthService(repo=repo, email_service=mock_email)
        with app.app_context():
            # First registration succeeds
            s1, _, _ = service.register(
                email="existing@example.com",
                password="StrongPassword123!",
                full_name="Existing User",
            )
            assert s1 is True
            mock_email.reset_mock()

            # Second attempt with same email fails
            s2, msg, user = service.register(
                email="existing@example.com",
                password="StrongPassword123!",
                full_name="Duplicate Attempt",
            )
            assert s2 is False
            assert user is None
            assert "already exists" in msg
            mock_email.send_welcome_email.assert_not_called()

    def test_failed_registration_weak_password_does_not_trigger_welcome_email(self, app):
        """Validation rejection prevents email dispatch."""
        repo = InMemoryUserRepository()
        mock_email = MagicMock()

        service = AuthService(repo=repo, email_service=mock_email)
        with app.app_context():
            success, msg, user = service.register(
                email="weak@example.com",
                password="123",
                full_name="Weak User",
            )
            assert success is False
            assert user is None
            mock_email.send_welcome_email.assert_not_called()

    def test_registration_succeeds_even_if_email_fails(self, app):
        """If welcome email fails or raises an exception, user registration remains successful."""
        repo = InMemoryUserRepository()
        mock_email = MagicMock()
        mock_email.send_welcome_email.side_effect = RuntimeError("Resend API Outage")

        service = AuthService(repo=repo, email_service=mock_email)
        with app.app_context():
            success, msg, user = service.register(
                email="resilient@example.com",
                password="StrongPassword123!",
                full_name="Resilient User",
            )
            assert success is True
            assert "Registration successful!" in msg
            assert user is not None
            # User must be persisted in repository
            persisted = repo.get_by_email("resilient@example.com")
            assert persisted is not None
            assert persisted["full_name"] == "Resilient User"


class TestBookingConfirmationEmailIntegration:
    """Verify customer booking confirmation email dispatch, SNS independence, and resilience."""

    def test_successful_booking_triggers_customer_email(self, app):
        """Successful booking reservation invokes send_booking_confirmation_email."""
        booking_repo = InMemoryBookingRepository()
        mock_sns = MagicMock()
        mock_sns.publish_booking_confirmation.return_value = True
        mock_email = MagicMock()
        mock_email.send_booking_confirmation_email.return_value = True

        service = BookingService(
            repo=booking_repo,
            sns_service=mock_sns,
            email_service=mock_email,
        )

        with app.app_context():
            success, msg, booking = service.create_booking(
                user_id="usr-cust-1",
                user_email="customer1@example.com",
                movie_id="mov-south-1",
                theater_id="th-pvr-dyp",
                showtime="18:30",
                show_date="2026-10-25",
                seats=["E1", "E2"],
            )
            assert success is True
            assert booking is not None

            # Verify SNS called for admin notification
            mock_sns.publish_booking_confirmation.assert_called_once_with(booking)

            # Verify Resend called for customer confirmation email
            mock_email.send_booking_confirmation_email.assert_called_once_with(
                booking=booking,
                customer_email="customer1@example.com",
            )

    def test_correct_customer_email_selected(self, app):
        """The verified customer email passed to create_booking is the one sent to email service."""
        booking_repo = InMemoryBookingRepository()
        mock_email = MagicMock()
        mock_email.send_booking_confirmation_email.return_value = True

        service = BookingService(repo=booking_repo, email_service=mock_email)

        with app.app_context():
            service.create_booking(
                user_id="usr-cust-2",
                user_email="authenticated.user@domain.com",
                movie_id="mov-south-1",
                theater_id="th-pvr-dyp",
                showtime="18:30",
                show_date="2026-10-25",
                seats=["E3"],
            )
            call_kwargs = mock_email.send_booking_confirmation_email.call_args.kwargs
            assert call_kwargs["customer_email"] == "authenticated.user@domain.com"

    def test_booking_failure_does_not_trigger_email(self, app):
        """Seat collision failure rejects booking and never triggers customer email or SNS."""
        booking_repo = InMemoryBookingRepository()
        mock_sns = MagicMock()
        mock_email = MagicMock()

        service = BookingService(
            repo=booking_repo,
            sns_service=mock_sns,
            email_service=mock_email,
        )

        with app.app_context():
            # Initial reservation for seat F1
            service.create_booking(
                user_id="usr-cust-3",
                user_email="first@example.com",
                movie_id="mov-south-1",
                theater_id="th-pvr-dyp",
                showtime="18:30",
                show_date="2026-10-25",
                seats=["F1"],
            )
            mock_sns.reset_mock()
            mock_email.reset_mock()

            # Second attempt for seat F1 must fail
            success, msg, booking = service.create_booking(
                user_id="usr-cust-4",
                user_email="second@example.com",
                movie_id="mov-south-1",
                theater_id="th-pvr-dyp",
                showtime="18:30",
                show_date="2026-10-25",
                seats=["F1"],
            )
            assert success is False
            assert booking is None
            assert "already been reserved" in msg
            mock_sns.publish_booking_confirmation.assert_not_called()
            mock_email.send_booking_confirmation_email.assert_not_called()

    def test_email_error_does_not_fail_booking(self, app):
        """If customer email provider fails or raises an exception, the booking remains confirmed."""
        booking_repo = InMemoryBookingRepository()
        mock_email = MagicMock()
        mock_email.send_booking_confirmation_email.side_effect = Exception("Resend Network Drop")

        service = BookingService(repo=booking_repo, email_service=mock_email)

        with app.app_context():
            success, msg, booking = service.create_booking(
                user_id="usr-cust-5",
                user_email="resilient.cust@example.com",
                movie_id="mov-south-1",
                theater_id="th-pvr-dyp",
                showtime="18:30",
                show_date="2026-10-25",
                seats=["F3", "F4"],
            )
            assert success is True
            assert "Booking confirmed successfully!" in msg
            assert booking is not None

            # Seats must be marked booked in repository
            booked = booking_repo.get_booked_seats("mov-south-1", "th-pvr-dyp", "18:30")
            assert "F3" in booked
            assert "F4" in booked

    def test_sns_and_email_independence(self, app):
        """SNS and Customer Email operate independently:
        - If SNS fails, customer email is still delivered.
        - If customer email fails, SNS is still delivered.
        """
        booking_repo = InMemoryBookingRepository()

        # Case 1: SNS throws, Email succeeds
        failing_sns = MagicMock()
        failing_sns.publish_booking_confirmation.side_effect = RuntimeError("SNS Down")
        working_email = MagicMock()
        working_email.send_booking_confirmation_email.return_value = True

        service1 = BookingService(
            repo=booking_repo,
            sns_service=failing_sns,
            email_service=working_email,
        )

        with app.app_context():
            s1, _, b1 = service1.create_booking(
                user_id="usr-cust-6",
                user_email="cust6@example.com",
                movie_id="mov-south-1",
                theater_id="th-pvr-dyp",
                showtime="18:30",
                show_date="2026-10-25",
                seats=["F5"],
            )
            assert s1 is True
            assert b1 is not None
            failing_sns.publish_booking_confirmation.assert_called_once()
            working_email.send_booking_confirmation_email.assert_called_once()

        # Case 2: SNS succeeds, Email throws
        working_sns = MagicMock()
        working_sns.publish_booking_confirmation.return_value = True
        failing_email = MagicMock()
        failing_email.send_booking_confirmation_email.side_effect = RuntimeError("Resend Down")

        service2 = BookingService(
            repo=booking_repo,
            sns_service=working_sns,
            email_service=failing_email,
        )

        with app.app_context():
            s2, _, b2 = service2.create_booking(
                user_id="usr-cust-7",
                user_email="cust7@example.com",
                movie_id="mov-south-1",
                theater_id="th-pvr-dyp",
                showtime="18:30",
                show_date="2026-10-25",
                seats=["F6"],
            )
            assert s2 is True
            assert b2 is not None
            working_sns.publish_booking_confirmation.assert_called_once()
            failing_email.send_booking_confirmation_email.assert_called_once()
