"""Movie Magic — DynamoDB Table Definition, Schema Inspector & Creation Utility.

Manages the 6 core tables for Phase 2 DynamoDB Integration:
1. {prefix}users        (PK: user_id, GSI: EmailIndex)
2. {prefix}movies       (PK: movie_id, GSI: CategoryIndex)
3. {prefix}theaters     (PK: theater_id, GSI: CityStatusIndex)
4. {prefix}showtimes    (PK: showtime_id, GSI: MovieShowtimeIndex, TheaterShowtimeIndex)
5. {prefix}bookings     (PK: booking_id, GSI: UserBookingsIndex)
6. {prefix}show_seats   (PK: show_key, SK: seat_code - Atomic Concurrency Table)

Safety Guarantees:
- Default mode is read-only inspection (--check).
- Refuses to create any AWS resource without the explicit --create flag.
- Never deletes or overwrites existing tables or data.
- If a table exists, thoroughly inspects its KeySchema and GSIs and reports any mismatches.
- Always uses on-demand billing (PAY_PER_REQUEST) to eliminate baseline idle costs.
- Displays target region (default: ap-south-1 Mumbai) and table names prior to any action.
"""

import argparse
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

# Add project root to sys.path for importing application modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.aws.client_factory import (
    DEFAULT_REGION,
    get_default_region,
    get_boto3_client,
    is_mock_mode_active,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("dynamodb_manager")


def get_table_definitions(prefix: str = "moviemagic_") -> Dict[str, Dict[str, Any]]:
    """Return dictionary of table schemas and configurations for the 6 Movie Magic tables."""
    return {
        f"{prefix}users": {
            "TableName": f"{prefix}users",
            "KeySchema": [
                {"AttributeName": "user_id", "KeyType": "HASH"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "email", "AttributeType": "S"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "EmailIndex",
                    "KeySchema": [
                        {"AttributeName": "email", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            "BillingMode": "PAY_PER_REQUEST",
            "Description": "User credentials, profiles, and role management",
        },
        f"{prefix}movies": {
            "TableName": f"{prefix}movies",
            "KeySchema": [
                {"AttributeName": "movie_id", "KeyType": "HASH"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "movie_id", "AttributeType": "S"},
                {"AttributeName": "category", "AttributeType": "S"},
                {"AttributeName": "release_year", "AttributeType": "N"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "CategoryIndex",
                    "KeySchema": [
                        {"AttributeName": "category", "KeyType": "HASH"},
                        {"AttributeName": "release_year", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            "BillingMode": "PAY_PER_REQUEST",
            "Description": "28 curated movies across Anime, Marvel, and South Indian cinema",
        },
        f"{prefix}theaters": {
            "TableName": f"{prefix}theaters",
            "KeySchema": [
                {"AttributeName": "theater_id", "KeyType": "HASH"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "theater_id", "AttributeType": "S"},
                {"AttributeName": "city", "AttributeType": "S"},
                {"AttributeName": "operational_status", "AttributeType": "S"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "CityStatusIndex",
                    "KeySchema": [
                        {"AttributeName": "city", "KeyType": "HASH"},
                        {"AttributeName": "operational_status", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            "BillingMode": "PAY_PER_REQUEST",
            "Description": "Cinema venues in Kolhapur and verification status",
        },
        f"{prefix}showtimes": {
            "TableName": f"{prefix}showtimes",
            "KeySchema": [
                {"AttributeName": "showtime_id", "KeyType": "HASH"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "showtime_id", "AttributeType": "S"},
                {"AttributeName": "movie_id", "AttributeType": "S"},
                {"AttributeName": "theater_id", "AttributeType": "S"},
                {"AttributeName": "date_time", "AttributeType": "S"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "MovieShowtimeIndex",
                    "KeySchema": [
                        {"AttributeName": "movie_id", "KeyType": "HASH"},
                        {"AttributeName": "date_time", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "TheaterShowtimeIndex",
                    "KeySchema": [
                        {"AttributeName": "theater_id", "KeyType": "HASH"},
                        {"AttributeName": "date_time", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            "BillingMode": "PAY_PER_REQUEST",
            "Description": "Screen schedules separated from catalogue movies",
        },
        f"{prefix}bookings": {
            "TableName": f"{prefix}bookings",
            "KeySchema": [
                {"AttributeName": "booking_id", "KeyType": "HASH"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "booking_id", "AttributeType": "S"},
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
            ],
            "GlobalSecondaryIndexes": [
                {
                    "IndexName": "UserBookingsIndex",
                    "KeySchema": [
                        {"AttributeName": "user_id", "KeyType": "HASH"},
                        {"AttributeName": "created_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            "BillingMode": "PAY_PER_REQUEST",
            "Description": "Confirmed ticket reservations and receipts",
        },
        f"{prefix}show_seats": {
            "TableName": f"{prefix}show_seats",
            "KeySchema": [
                {"AttributeName": "show_key", "KeyType": "HASH"},
                {"AttributeName": "seat_code", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "show_key", "AttributeType": "S"},
                {"AttributeName": "seat_code", "AttributeType": "S"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
            "Description": "Atomic seat reservation records preventing double bookings",
        },
    }


def inspect_table_schema(
    expected: Dict[str, Any],
    actual: Dict[str, Any]
) -> Tuple[bool, List[str]]:
    """Compare an existing DynamoDB table's description with the expected definition.

    Returns:
        (is_match, list_of_mismatch_reasons)
    """
    mismatches = []

    # 1. Compare KeySchema
    expected_keys = {k["AttributeName"]: k["KeyType"] for k in expected.get("KeySchema", [])}
    actual_keys = {k["AttributeName"]: k["KeyType"] for k in actual.get("KeySchema", [])}
    if expected_keys != actual_keys:
        mismatches.append(f"KeySchema mismatch: expected {expected_keys}, found {actual_keys}")

    # 2. Compare GlobalSecondaryIndexes
    expected_gsis = {g["IndexName"]: g for g in expected.get("GlobalSecondaryIndexes", [])}
    actual_gsis = {g["IndexName"]: g for g in actual.get("GlobalSecondaryIndexes", [])}

    for idx_name, expected_gsi in expected_gsis.items():
        if idx_name not in actual_gsis:
            mismatches.append(f"Missing GSI: {idx_name}")
        else:
            actual_gsi = actual_gsis[idx_name]
            exp_gsi_keys = {k["AttributeName"]: k["KeyType"] for k in expected_gsi.get("KeySchema", [])}
            act_gsi_keys = {k["AttributeName"]: k["KeyType"] for k in actual_gsi.get("KeySchema", [])}
            if exp_gsi_keys != act_gsi_keys:
                mismatches.append(
                    f"GSI {idx_name} KeySchema mismatch: expected {exp_gsi_keys}, found {act_gsi_keys}"
                )

    # 3. Check BillingMode (PAY_PER_REQUEST / On-Demand)
    expected_billing = expected.get("BillingMode", "PAY_PER_REQUEST")
    billing_summary = actual.get("BillingModeSummary", {})
    actual_billing = billing_summary.get("BillingMode", actual.get("BillingMode", "PROVISIONED"))
    if actual_billing != expected_billing:
        mismatches.append(f"BillingMode mismatch: expected {expected_billing}, found {actual_billing}")

    is_match = len(mismatches) == 0
    return is_match, mismatches


def check_tables(client, tables: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Inspect status of all required tables without making any modifications."""
    report = {}
    for table_name, schema in tables.items():
        try:
            resp = client.describe_table(TableName=table_name)
            table_desc = resp.get("Table", {})
            status = table_desc.get("TableStatus", "UNKNOWN")
            is_match, mismatches = inspect_table_schema(schema, table_desc)
            report[table_name] = {
                "exists": True,
                "status": status,
                "schema_match": is_match,
                "mismatches": mismatches,
                "item_count": table_desc.get("ItemCount", 0),
                "bytes": table_desc.get("TableSizeBytes", 0),
            }
        except client.exceptions.ResourceNotFoundException:
            report[table_name] = {
                "exists": False,
                "status": "NOT_FOUND",
                "schema_match": False,
                "mismatches": ["Table does not exist"],
                "item_count": 0,
                "bytes": 0,
            }
        except Exception as e:
            report[table_name] = {
                "exists": False,
                "status": "ERROR",
                "schema_match": False,
                "mismatches": [str(e)],
                "item_count": 0,
                "bytes": 0,
            }
    return report


def create_tables(client, tables: Dict[str, Dict[str, Any]], wait_for_active: bool = True) -> bool:
    """Create DynamoDB tables that do not yet exist. Never overwrites or deletes."""
    inspection = check_tables(client, tables)
    created_any = False

    for table_name, schema in tables.items():
        status_info = inspection.get(table_name, {})
        if status_info.get("exists"):
            if status_info.get("schema_match"):
                print(f"  [OK - Exists] Table '{table_name}' is ACTIVE with matching schema.")
            else:
                print(f"  [WARNING - Mismatch] Table '{table_name}' exists but has schema differences:")
                for m in status_info.get("mismatches", []):
                    print(f"      - {m}")
            continue

        print(f"  [Creating] Table '{table_name}' (Billing: PAY_PER_REQUEST, Region: {client.meta.region_name})...")
        create_kwargs = {
            "TableName": table_name,
            "KeySchema": schema["KeySchema"],
            "AttributeDefinitions": schema["AttributeDefinitions"],
            "BillingMode": schema["BillingMode"],
        }
        if "GlobalSecondaryIndexes" in schema:
            create_kwargs["GlobalSecondaryIndexes"] = schema["GlobalSecondaryIndexes"]

        try:
            client.create_table(**create_kwargs)
            created_any = True
            print(f"  [Submitted] Creation request for '{table_name}'.")
        except Exception as e:
            print(f"  [ERROR] Failed to create '{table_name}': {e}")
            return False

    if created_any and wait_for_active:
        print("\nWaiting for all created tables to become ACTIVE...")
        for table_name in tables:
            waiter = client.get_waiter("table_exists")
            waiter.wait(TableName=table_name)
            print(f"  [Active] Table '{table_name}' is ready.")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Movie Magic: DynamoDB Infrastructure Manager (Phase 2, ap-south-1)."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Inspect existing tables and verify schema without modifications (DEFAULT).",
    )
    parser.add_argument(
        "--create",
        action="store_true",
        default=False,
        help="Explicit opt-in required to create any missing DynamoDB tables.",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default=os.environ.get("DYNAMODB_TABLE_PREFIX", "moviemagic_"),
        help="Table name prefix (default: moviemagic_).",
    )
    parser.add_argument(
        "--region",
        type=str,
        default=get_default_region(),
        help="AWS region (default: ap-south-1 Mumbai).",
    )
    parser.add_argument(
        "--endpoint-url",
        type=str,
        default=os.environ.get("DYNAMODB_ENDPOINT_URL"),
        help="Optional custom endpoint URL for local DynamoDB.",
    )

    args = parser.parse_args()

    # Safety Guard: In mock mode, prevent real AWS client creation unless endpoint is provided
    if is_mock_mode_active() and not args.endpoint_url:
        print("=" * 60)
        print("Movie Magic -- DynamoDB Infrastructure Utility")
        print("=" * 60)
        print("[MOCK MODE ACTIVE] USE_AWS_MOCK is currently set to True.")
        print("  - To run infrastructure checks or table creation, either:")
        print("    1. Set USE_AWS_MOCK=False and configure AWS credentials for ap-south-1, OR")
        print("    2. Pass --endpoint-url http://localhost:8000 for a local DynamoDB container.")
        print("\nRead-only dry-run schema preview:")
        tables = get_table_definitions(args.prefix)
        for t_name, t_def in tables.items():
            print(f"  * {t_name:25} [{t_def['Description']}]")
            print(f"      Keys: {t_def['KeySchema']}")
            if "GlobalSecondaryIndexes" in t_def:
                print(f"      GSIs: {[g['IndexName'] for g in t_def['GlobalSecondaryIndexes']]}")
        return 0

    print("=" * 60)
    print("Movie Magic -- DynamoDB Infrastructure Utility")
    print(f"Target AWS Region: {args.region} (Mumbai)")
    if args.endpoint_url:
        print(f"Custom Endpoint:   {args.endpoint_url}")
    print(f"Table Prefix:      {args.prefix}")
    print("=" * 60)

    tables = get_table_definitions(args.prefix)

    # Initialize live client (when USE_AWS_MOCK=False or custom endpoint provided)
    client = get_boto3_client("dynamodb", region_name=args.region, endpoint_url=args.endpoint_url)
    if not client:
        print("ERROR: Could not initialize boto3 DynamoDB client.")
        print("Check your AWS credentials chain or provide --endpoint-url.")
        return 1

    # Execute check
    print("\n[Step 1] Inspecting tables in DynamoDB...")
    inspection = check_tables(client, tables)

    all_exist_and_match = True
    for table_name, info in inspection.items():
        print(f"  * {table_name}:")
        print(f"      Status:       {info['status']}")
        print(f"      Schema Match: {info['schema_match']}")
        if not info["schema_match"]:
            all_exist_and_match = False
            for m in info["mismatches"]:
                print(f"      Reason:       {m}")

    if args.create:
        print("\n[Step 2] Processing table creation (--create flag provided)...")
        success = create_tables(client, tables)
        return 0 if success else 1
    else:
        print("\n[Read-Only Mode] No tables were created.")
        print("Pass '--create' explicitly to provision any missing tables.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
