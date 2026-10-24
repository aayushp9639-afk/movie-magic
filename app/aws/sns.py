"""Amazon Simple Notification Service (SNS) adapter for Movie Magic.
Handles booking email notifications and alerts.
"""
import logging
import os
from typing import Dict, Any, Optional
from .client_factory import get_boto3_client

logger = logging.getLogger(__name__)


class SNSService:
    """SNS Service adapter for dispatching booking confirmation notifications."""

    def __init__(self, topic_arn: Optional[str] = None, client: Optional[Any] = None):
        self._topic_arn = topic_arn
        self._client = client

    @property
    def topic_arn(self) -> str:
        if self._topic_arn is not None:
            return self._topic_arn
        return os.environ.get("SNS_BOOKING_TOPIC_ARN", "").strip()

    @topic_arn.setter
    def topic_arn(self, value: str):
        self._topic_arn = value

    @property
    def client(self):
        if self._client is not None:
            return self._client
        return get_boto3_client("sns")

    @property
    def is_connected(self) -> bool:
        return self.client is not None and bool(self.topic_arn)

    def publish_booking_confirmation(self, booking_details: Dict[str, Any]) -> bool:
        """Publish booking confirmation message to SNS topic."""
        booking_id = booking_details.get("booking_id") or booking_details.get("id") or "UNKNOWN"
        message = (
            f"🎬 Movie Magic Booking Confirmation\n"
            f"Booking ID: {booking_id}\n"
            f"Movie: {booking_details.get('movie_title')}\n"
            f"Theater: {booking_details.get('theater_name')}\n"
            f"Showtime: {booking_details.get('showtime')}\n"
            f"Seats: {', '.join(booking_details.get('seats', []))}\n"
            f"Total Amount: ₹{booking_details.get('total_price', 0):.2f}\n"
            f"Status: Confirmed (Demo)\n"
            f"Enjoy your movie!"
        )

        if not self.is_connected:
            logger.info(f"[Mock Mode] SNS notification simulated for booking: {booking_id}")
            return True

        try:
            self.client.publish(
                TopicArn=self.topic_arn,
                Subject=f"Movie Magic Booking Confirmed #{booking_id}",
                Message=message
            )
            return True
        except Exception as e:
            logger.error(f"Failed to publish to SNS: {e}")
            return False
