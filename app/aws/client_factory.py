"""Centralized AWS Client Factory for Movie Magic.

Provides safe, centralized boto3 client and resource creation supporting:
- Target region: ap-south-1 (Mumbai, India) by default.
- Standard AWS credential chain resolution (IAM role, ~/.aws/credentials, environment).
- Optional custom endpoint URL (e.g., DYNAMODB_ENDPOINT_URL for local testing).
- Strict mock mode guarantee: when USE_AWS_MOCK is True, no real AWS clients are
  created and zero AWS network requests are executed.
- Never hardcodes or logs AWS credentials.
"""

import logging
import os
from typing import Any, Optional
import boto3
from botocore.exceptions import BotoCoreError, NoCredentialsError, ClientError

logger = logging.getLogger(__name__)

DEFAULT_REGION = "ap-south-1"


def get_default_region() -> str:
    """Return configured AWS region from environment, defaulting to ap-south-1 (Mumbai)."""
    return os.environ.get("AWS_REGION", DEFAULT_REGION).strip() or DEFAULT_REGION


def is_mock_mode_active() -> bool:
    """Check whether application is running in mock/offline demo mode."""
    return os.environ.get("USE_AWS_MOCK", "True").lower() in ("true", "1", "yes")


def is_aws_configured() -> bool:
    """Check if AWS credentials or a local endpoint are available for real execution.

    Returns False if USE_AWS_MOCK is active. When USE_AWS_MOCK is False, checks if
    boto3 can resolve valid credentials via the standard AWS credential chain or
    if a local endpoint URL is configured.
    """
    if is_mock_mode_active():
        return False

    # If a local DynamoDB endpoint is specified, consider it configured
    if os.environ.get("DYNAMODB_ENDPOINT_URL"):
        return True

    try:
        session = boto3.Session(region_name=get_default_region())
        credentials = session.get_credentials()
        return credentials is not None
    except Exception as e:
        logger.debug(f"AWS credential resolution check returned: {e}")
        return False


def _build_kwargs(
    service_name: str,
    region_name: Optional[str] = None,
    endpoint_url: Optional[str] = None
) -> dict:
    """Construct kwargs for boto3 client/resource creation."""
    region = region_name or get_default_region()
    kwargs: dict[str, Any] = {"region_name": region}

    # Resolve endpoint URL (explicit arg, service-specific env, or general env)
    endpoint = endpoint_url
    if not endpoint and service_name == "dynamodb":
        endpoint = os.environ.get("DYNAMODB_ENDPOINT_URL")

    if endpoint:
        kwargs["endpoint_url"] = endpoint.strip()

    # If explicit credentials are provided in env, use them;
    # otherwise let boto3 resolve via standard AWS credential chain (IAM roles, etc.)
    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    session_token = os.environ.get("AWS_SESSION_TOKEN")

    if access_key and secret_key:
        kwargs["aws_access_key_id"] = access_key.strip()
        kwargs["aws_secret_access_key"] = secret_key.strip()
        if session_token:
            kwargs["aws_session_token"] = session_token.strip()

    return kwargs


def get_boto3_client(
    service_name: str,
    region_name: Optional[str] = None,
    endpoint_url: Optional[str] = None
):
    """Safely obtain a boto3 client.

    Guarantees:
    - If USE_AWS_MOCK is True, returns None immediately without network calls.
    - Uses standard AWS credential chain when live.
    - Respects region_name and endpoint_url overrides.

    Returns:
        boto3.client instance or None if in mock mode or initialization fails.
    """
    if is_mock_mode_active():
        logger.debug(f"[AWS Mock] USE_AWS_MOCK is True. Skipping real {service_name} client.")
        return None

    kwargs = _build_kwargs(service_name, region_name, endpoint_url)

    try:
        client = boto3.client(service_name, **kwargs)
        return client
    except (BotoCoreError, NoCredentialsError) as e:
        logger.warning(
            f"Could not initialize AWS {service_name} client in {kwargs.get('region_name')}: {e}. "
            "Please configure AWS credentials or set USE_AWS_MOCK=True."
        )
        return None
    except Exception as e:
        logger.error(f"Unexpected error initializing AWS {service_name} client: {e}")
        return None


def get_boto3_resource(
    service_name: str,
    region_name: Optional[str] = None,
    endpoint_url: Optional[str] = None
):
    """Safely obtain a boto3 resource (e.g. boto3.resource('dynamodb')).

    Guarantees:
    - If USE_AWS_MOCK is True, returns None immediately without network calls.
    - Uses standard AWS credential chain when live.
    - Respects region_name and endpoint_url overrides.

    Returns:
        boto3.resource instance or None if in mock mode or initialization fails.
    """
    if is_mock_mode_active():
        logger.debug(f"[AWS Mock] USE_AWS_MOCK is True. Skipping real {service_name} resource.")
        return None

    kwargs = _build_kwargs(service_name, region_name, endpoint_url)

    try:
        resource = boto3.resource(service_name, **kwargs)
        return resource
    except (BotoCoreError, NoCredentialsError) as e:
        logger.warning(
            f"Could not initialize AWS {service_name} resource in {kwargs.get('region_name')}: {e}. "
            "Please configure AWS credentials or set USE_AWS_MOCK=True."
        )
        return None
    except Exception as e:
        logger.error(f"Unexpected error initializing AWS {service_name} resource: {e}")
        return None
