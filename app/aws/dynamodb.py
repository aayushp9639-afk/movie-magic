"""DynamoDB service interface and adapter for Movie Magic.

Encapsulates AWS DynamoDB client and resource operations, providing:
- High-level Table resource access and low-level client operations.
- Dynamic table naming with configurable prefix (default: moviemagic_).
- Support for target region ap-south-1 (Mumbai).
- Transparent fallback and no-op stubs when mock mode (USE_AWS_MOCK=True) is active.
"""

import logging
import os
from typing import Any, Dict, List, Optional
from .client_factory import get_boto3_client, get_boto3_resource, get_default_region, is_mock_mode_active

logger = logging.getLogger(__name__)


class DynamoDBService:
    """DynamoDB service adapter for Movie Magic.

    Encapsulates table operations, query execution, transactions, and safe mock fallbacks.
    """

    def __init__(
        self,
        table_prefix: Optional[str] = None,
        region_name: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        use_mock: Optional[bool] = None,
    ):
        self.table_prefix = table_prefix or os.environ.get("DYNAMODB_TABLE_PREFIX", "moviemagic_")
        self.region = region_name or get_default_region()
        self.endpoint_url = endpoint_url or os.environ.get("DYNAMODB_ENDPOINT_URL")
        self.use_mock = is_mock_mode_active() if use_mock is None else use_mock

        if self.use_mock:
            self._client = None
            self._resource = None
        else:
            self._client = get_boto3_client("dynamodb", region_name=self.region, endpoint_url=self.endpoint_url)
            self._resource = get_boto3_resource("dynamodb", region_name=self.region, endpoint_url=self.endpoint_url)
        self.is_connected = self._client is not None and self._resource is not None

    @property
    def client(self):
        """Access underlying boto3 client (None in mock mode)."""
        return self._client

    @property
    def resource(self):
        """Access underlying boto3 DynamoDB resource (None in mock mode)."""
        return self._resource

    @property
    def is_mock(self) -> bool:
        """Report whether this service adapter is in mock mode."""
        return self.use_mock or not self.is_connected

    def get_table_name(self, base_name: str) -> str:
        """Resolve full DynamoDB table name using configured prefix."""
        return f"{self.table_prefix}{base_name}"

    def get_table(self, base_name: str):
        """Obtain a boto3 DynamoDB Table resource for the given base table name."""
        if not self.is_connected or not self._resource:
            return None
        return self._resource.Table(self.get_table_name(base_name))

    def put_item(self, table_name: str, item: Dict[str, Any]) -> bool:
        """Put an item into DynamoDB table."""
        full_table_name = self.get_table_name(table_name)
        if not self.is_connected:
            logger.info(f"[Mock Mode] DynamoDB.put_item stub called for {full_table_name} with {len(item)} attributes.")
            return True

        try:
            table = self.get_table(table_name)
            if table:
                table.put_item(Item=item)
            else:
                self._client.put_item(TableName=full_table_name, Item=item)
            return True
        except Exception as e:
            logger.error(f"Error putting item into {full_table_name}: {e}")
            return False

    def get_item(self, table_name: str, key: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Retrieve an item by primary key."""
        full_table_name = self.get_table_name(table_name)
        if not self.is_connected:
            logger.info(f"[Mock Mode] DynamoDB.get_item stub called for {full_table_name} with key {key}.")
            return None

        try:
            table = self.get_table(table_name)
            if table:
                response = table.get_item(Key=key)
                return response.get("Item")
            else:
                response = self._client.get_item(TableName=full_table_name, Key=key)
                return response.get("Item")
        except Exception as e:
            logger.error(f"Error getting item from {full_table_name}: {e}")
            return None
