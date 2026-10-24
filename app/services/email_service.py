"""Email Service for Movie Magic.
Coordinates customer-facing transactional emails using the official Resend REST API
(https://api.resend.com/emails) with HTTPS TLS, structured error handling,
idempotency keys, and plain-text fallback.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class EmailService:
    """Transactional email service dispatching customer communications via Resend."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        from_email: Optional[str] = None,
        reply_to: Optional[str] = None,
        base_url: Optional[str] = None,
        http_client: Optional[Any] = None,
        timeout: int = 8,
    ):
        self._api_key = api_key
        self._from_email = from_email
        self._reply_to = reply_to
        self._base_url = base_url
        self._http_client = http_client
        self._timeout = timeout

    @property
    def api_key(self) -> str:
        """Active Resend API Key resolved from instance override, Flask config, or environment."""
        if self._api_key is not None:
            return self._api_key
        try:
            from flask import current_app
            if current_app:
                return current_app.config.get("RESEND_API_KEY", "").strip()
        except RuntimeError:
            pass
        return os.environ.get("RESEND_API_KEY", "").strip()

    @api_key.setter
    def api_key(self, value: str):
        self._api_key = value

    @property
    def from_email(self) -> str:
        """Configured sender identity (must be verified in Resend domain settings)."""
        if self._from_email is not None:
            return self._from_email
        try:
            from flask import current_app
            if current_app:
                val = current_app.config.get("RESEND_FROM_EMAIL", "").strip()
                if val:
                    return val
        except RuntimeError:
            pass
        val = os.environ.get("RESEND_FROM_EMAIL", "").strip()
        return val if val else "Movie Magic <tickets@mail.shardul.online>"

    @from_email.setter
    def from_email(self, value: str):
        self._from_email = value

    @property
    def reply_to(self) -> Optional[str]:
        """Optional reply-to email address."""
        if self._reply_to is not None:
            return self._reply_to
        try:
            from flask import current_app
            if current_app:
                val = current_app.config.get("RESEND_REPLY_TO", "").strip()
                if val:
                    return val
        except RuntimeError:
            pass
        val = os.environ.get("RESEND_REPLY_TO", "").strip()
        return val if val else None

    @reply_to.setter
    def reply_to(self, value: Optional[str]):
        self._reply_to = value

    @property
    def base_url(self) -> str:
        """Public application base URL used for clickable links in emails."""
        if self._base_url is not None:
            return self._base_url.rstrip("/")
        try:
            from flask import current_app
            if current_app:
                val = current_app.config.get("APP_BASE_URL", "").strip()
                if val:
                    return val.rstrip("/")
        except RuntimeError:
            pass
        val = os.environ.get("APP_BASE_URL", "").strip()
        if val:
            return val.rstrip("/")
        return "http://43.204.215.123"

    @base_url.setter
    def base_url(self, value: str):
        self._base_url = value

    @property
    def is_configured(self) -> bool:
        """True when a non-empty Resend API key is present."""
        return bool(self.api_key)

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: str,
        idempotency_key: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Send an email through Resend REST API (POST https://api.resend.com/emails).
        
        Returns:
            Tuple of (success: bool, message_id_or_error: Optional[str])
        """
        if not to_email or "@" not in to_email:
            logger.warning("[EmailService] Invalid recipient email '%s'. Suppressing dispatch.", to_email)
            return False, None

        if not self.is_configured:
            logger.warning(
                "[EmailService] RESEND_API_KEY is not configured. Email '%s' to '%s' suppressed.",
                subject,
                to_email,
            )
            return False, None

        # Custom HTTP client hook for dependency injection and automated unit testing
        if self._http_client is not None:
            return self._http_client(
                to_email=to_email,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
                idempotency_key=idempotency_key,
                from_email=self.from_email,
                reply_to=self.reply_to,
            )

        payload: Dict[str, Any] = {
            "from": self.from_email,
            "to": [to_email],
            "subject": subject,
            "html": html_content,
            "text": text_content,
        }
        if self.reply_to:
            payload["reply_to"] = self.reply_to

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "MovieMagic-ResendClient/1.0",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = str(idempotency_key).strip()

        try:
            req = urllib.request.Request(
                url="https://api.resend.com/emails",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                resp_body = resp.read().decode("utf-8")
                data = json.loads(resp_body) if resp_body else {}
                msg_id = data.get("id")
                logger.info(
                    "[EmailService] Email dispatched successfully via Resend. Message ID: %s, Recipient: %s",
                    msg_id,
                    to_email,
                )
                return True, msg_id

        except urllib.error.HTTPError as http_err:
            try:
                err_body = http_err.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = "Could not read error body"
            logger.error(
                "[EmailService] Resend API returned HTTP %d for recipient %s: %s",
                http_err.code,
                to_email,
                err_body,
            )
            return False, None

        except urllib.error.URLError as url_err:
            logger.error(
                "[EmailService] Resend connection failed for recipient %s: %s",
                to_email,
                url_err.reason,
            )
            return False, None

        except TimeoutError:
            logger.error(
                "[EmailService] Resend API request timed out after %ds for recipient %s",
                self._timeout,
                to_email,
            )
            return False, None

        except Exception as e:
            logger.error(
                "[EmailService] Unexpected error sending email to %s: %s",
                to_email,
                type(e).__name__,
            )
            return False, None

    def send_welcome_email(self, user_email: str, user_name: str) -> bool:
        """Send a cinematic welcome email to a newly registered user."""
        if not user_email:
            return False

        subject = "Welcome to Movie Magic — Your Next Movie Adventure Starts Here!"
        base_url = self.base_url
        movies_url = f"{base_url}/movies"

        context = {
            "user_name": user_name or "Movie Fan",
            "user_email": user_email,
            "base_url": base_url,
            "movies_url": movies_url,
            "support_email": self.reply_to,
        }

        try:
            from flask import current_app, render_template
            if current_app:
                html_content = current_app.jinja_env.get_template("emails/welcome.html").render(**context)
                text_content = current_app.jinja_env.get_template("emails/welcome.txt").render(**context)
            else:
                html_content = render_template("emails/welcome.html", **context)
                text_content = render_template("emails/welcome.txt", **context)
        except Exception as render_err:
            logger.error("[EmailService] Failed to render welcome email template: %s", render_err)
            return False

        idempotency_key = f"welcome-{user_email.strip().lower()}"
        success, _ = self.send_email(
            to_email=user_email,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            idempotency_key=idempotency_key,
        )
        return success

    def send_booking_confirmation_email(
        self,
        booking: Dict[str, Any],
        customer_email: Optional[str] = None,
    ) -> bool:
        """Send a premium e-ticket confirmation email for a persisted booking."""
        recipient = customer_email or booking.get("user_email")
        if not recipient:
            logger.warning("[EmailService] No recipient email available for booking confirmation.")
            return False

        booking_id = booking.get("id") or booking.get("booking_id") or "UNKNOWN"
        movie_title = booking.get("movie_title", "Movie")
        subject = f"Your Movie Magic Ticket Confirmation — {booking_id} — {movie_title}"

        base_url = self.base_url
        booking_url = f"{base_url}/book/confirmation/{booking_id}"

        context = {
            "booking": booking,
            "booking_id": booking_id,
            "movie_title": movie_title,
            "theater_name": booking.get("theater_name", "Cinema"),
            "showtime": booking.get("showtime", ""),
            "show_date": booking.get("show_date", ""),
            "seats": booking.get("seats", []),
            "tier": booking.get("tier", "Standard"),
            "total_price": booking.get("total_price", 0.0),
            "booking_url": booking_url,
            "base_url": base_url,
            "support_email": self.reply_to,
        }

        try:
            from flask import current_app, render_template
            if current_app:
                html_content = current_app.jinja_env.get_template("emails/booking_confirmation.html").render(**context)
                text_content = current_app.jinja_env.get_template("emails/booking_confirmation.txt").render(**context)
            else:
                html_content = render_template("emails/booking_confirmation.html", **context)
                text_content = render_template("emails/booking_confirmation.txt", **context)
        except Exception as render_err:
            logger.error("[EmailService] Failed to render booking confirmation template: %s", render_err)
            return False

        idempotency_key = f"booking-{booking_id}"
        success, _ = self.send_email(
            to_email=recipient,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            idempotency_key=idempotency_key,
        )
        return success


# Default application-wide email service singleton
email_service = EmailService()
