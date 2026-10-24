"""Booking Service.
Coordinates seat reservation, server-side validation, price calculation,
atomic persistence, and notification dispatch.
"""
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from app.repositories import (
    booking_repository,
    movie_repository,
    DuplicateSeatError,
    BookingPersistenceError,
)
from app.aws.sns import SNSService
from app.data.sample_movies import TOTAL_ROWS, SEATS_PER_ROW, SEAT_TIERS

logger = logging.getLogger(__name__)
SEAT_CODE_REGEX = re.compile(r"^[A-H](?:[1-9]|10)$")


class BookingService:
    """Business logic for reservations, seat map generation, and booking receipts."""

    def __init__(self, repo=None, movie_repo=None, sns_service=None, email_service=None):
        self._repo = repo
        self._movie_repo = movie_repo
        self._sns_service = sns_service
        self._email_service = email_service

    @property
    def email_service(self):
        """Active customer transactional email service adapter."""
        if self._email_service is not None:
            return self._email_service
        from app.services.email_service import email_service
        return email_service

    @property
    def sns_service(self):
        """Active SNS notification service adapter."""
        if self._sns_service is not None:
            return self._sns_service
        return SNSService()

    @property
    def repo(self):
        """Active booking repository."""
        if self._repo is not None:
            return self._repo
        return booking_repository

    @property
    def movie_repo(self):
        """Active movie repository."""
        if self._movie_repo is not None:
            return self._movie_repo
        return movie_repository

    def get_seat_layout(self, movie_id: str, theater_id: str, showtime: str) -> Dict[str, Any]:
        """Generate interactive seat grid with current reserved states and tiers."""
        booked_seats = set(self.repo.get_booked_seats(movie_id, theater_id, showtime))

        rows_data = []
        for row_letter in TOTAL_ROWS:
            # Determine tier for this row
            row_tier = "Silver"
            price = SEAT_TIERS.get("Silver", {}).get("price", 160.00)
            for tier_name, tier_info in SEAT_TIERS.items():
                if row_letter in tier_info["rows"]:
                    row_tier = tier_name
                    price = tier_info["price"]
                    break

            seats_in_row = []
            for num in range(1, SEATS_PER_ROW + 1):
                seat_id = f"{row_letter}{num}"
                is_booked = seat_id in booked_seats
                seats_in_row.append({
                    "id": seat_id,
                    "row": row_letter,
                    "number": num,
                    "tier": row_tier,
                    "price": price,
                    "is_booked": is_booked,
                })

            rows_data.append({
                "row_letter": row_letter,
                "tier": row_tier,
                "price": price,
                "seats": seats_in_row,
            })

        return {
            "rows": rows_data,
            "tiers": SEAT_TIERS,
            "total_rows": TOTAL_ROWS,
            "seats_per_row": SEATS_PER_ROW,
            "booked_count": len(booked_seats),
        }

    def calculate_total(self, seats: List[str]) -> Tuple[float, str]:
        """Calculate total price strictly on the server based on seat tiers (INR)."""
        if not seats:
            return 0.0, "None"

        total = 0.0
        tiers_used = set()
        for seat in seats:
            row_letter = seat[0].upper()
            seat_price = SEAT_TIERS.get("Silver", {}).get("price", 160.00)
            for tier_name, tier_info in SEAT_TIERS.items():
                if row_letter in tier_info["rows"]:
                    seat_price = tier_info["price"]
                    tiers_used.add(tier_name)
                    break
            total += seat_price

        tier_summary = ", ".join(sorted(tiers_used)) if tiers_used else "Standard"
        return round(total, 2), tier_summary

    def create_booking(
        self,
        user_id: str,
        user_email: str,
        movie_id: str,
        theater_id: str,
        showtime: str,
        show_date: str,
        seats: List[str],
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Validate and create a movie ticket booking with atomic concurrency protection."""
        if not seats:
            return False, "Please select at least one seat to proceed.", None

        if len(seats) > 10:
            return False, "You may book a maximum of 10 seats per transaction.", None

        # Normalize seat codes (e.g. 'a1' -> 'A1')
        normalized_seats = [s.strip().upper() for s in seats if s and s.strip()]

        if len(normalized_seats) != len(set(normalized_seats)):
            return False, "Duplicate seat selection detected in your request.", None

        # Validate seat code syntax against theater grid (A1 through H10)
        for s in normalized_seats:
            if not SEAT_CODE_REGEX.match(s):
                return False, f"Invalid seat identifier '{s}'.", None

        # Server-side validation of movie existence
        movie = self.movie_repo.get_by_id(movie_id)
        if not movie:
            return False, "Selected movie not found.", None

        # Server-side validation of theater venue and operational status
        theater = self.movie_repo.get_theater_by_id(theater_id)
        if not theater:
            return False, "Selected cinema venue not found.", None

        if theater.get("operational_status") != "Operational" or not theater.get("is_verified", True):
            return False, f"Venue '{theater.get('name')}' is currently not available for bookings.", None

        theater_name = theater.get("name", "Premier Cinema")

        # Server-side calculation of price breakdown (client-supplied price is never trusted)
        total_price, tier = self.calculate_total(normalized_seats)

        try:
            booking = self.repo.create_booking(
                user_id=user_id,
                user_email=user_email,
                movie_id=movie_id,
                movie_title=movie["title"],
                theater_id=theater_id,
                theater_name=theater_name,
                showtime=showtime,
                show_date=show_date,
                seats=normalized_seats,
                tier=tier,
                total_price=total_price,
            )
        except DuplicateSeatError as e:
            logger.warning("Seat collision detected: %s", e)
            return False, str(e), None
        except ValueError as e:
            return False, str(e), None
        except BookingPersistenceError as e:
            logger.error("Booking persistence failure: %s", type(e).__name__)
            return False, "Unable to complete reservation at this time. Please try again.", None
        except Exception as e:
            logger.error("Unexpected error during booking creation: %s", type(e).__name__)
            return False, "Unable to complete reservation at this time. Please try again.", None

        # Isolated SNS dispatch: notification failures must NEVER invalidate a completed reservation
        try:
            notification_sent = self.sns_service.publish_booking_confirmation(booking)
            if not notification_sent:
                logger.warning(
                    "SNS notification not delivered for booking %s. Reservation remains confirmed.",
                    booking.get("id") or booking.get("booking_id"),
                )
        except Exception as sns_err:
            logger.error(
                "Unexpected exception in SNS notification dispatch for booking %s: %s",
                booking.get("id") or booking.get("booking_id"),
                sns_err,
            )

        # Isolated Customer Email dispatch: email failures must NEVER invalidate a completed reservation
        try:
            email_sent = self.email_service.send_booking_confirmation_email(
                booking=booking,
                customer_email=user_email,
            )
            if not email_sent:
                logger.warning(
                    "Customer confirmation email not delivered for booking %s to %s. Reservation remains confirmed.",
                    booking.get("id") or booking.get("booking_id"),
                    user_email,
                )
        except Exception as email_err:
            logger.error(
                "Unexpected exception in customer email dispatch for booking %s: %s",
                booking.get("id") or booking.get("booking_id"),
                email_err,
            )

        return True, "Booking confirmed successfully!", booking

    def get_booking(self, booking_id: str) -> Optional[Dict[str, Any]]:
        return self.repo.get_by_id(booking_id)

    def get_user_bookings(self, user_id: str) -> List[Dict[str, Any]]:
        return self.repo.get_by_user_id(user_id)

    def get_all_bookings(self) -> List[Dict[str, Any]]:
        return self.repo.get_all()


booking_service = BookingService()
