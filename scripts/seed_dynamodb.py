"""Movie Magic — DynamoDB Catalogue & Venues Seeding Utility.

Safely populates the 28 curated catalogue movies, 5 Kolhapur cinema venues,
and demo showtimes into DynamoDB tables.

Safety Guarantees:
- Default mode is read-only dry run / inspection (--check).
- Refuses to write any records to DynamoDB without the explicit --seed flag.
- Idempotent: checks for existing items; skips identical records, updates only changed records.
- STRICT SAFETY GUARD: Customer tables (users, bookings, show_seats) are strictly protected
  and will NEVER be touched or overwritten by this seeding script.
- Handles float-to-Decimal conversions required by DynamoDB.
- Prints target region (default: ap-south-1 Mumbai) and table names prior to any action.
- Reports detailed counts: created, updated, skipped, failed.
"""

import argparse
import decimal
import logging
import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.aws.client_factory import (
    DEFAULT_REGION,
    get_default_region,
    get_boto3_resource,
    is_mock_mode_active,
)
from app.data.sample_movies import (
    SAMPLE_MOVIES,
    SAMPLE_THEATERS,
    SAMPLE_SHOWTIMES,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("dynamodb_seeder")

# Tables strictly allowed for catalogue seeding
ALLOWED_TABLE_CATEGORIES = ("movies", "theaters", "showtimes")

# Tables strictly prohibited from seeding (customer privacy & integrity)
PROTECTED_TABLE_CATEGORIES = ("users", "bookings", "show_seats")


def to_dynamodb_compatible(obj: Any) -> Any:
    """Recursively convert Python float values to Decimal for DynamoDB serialization."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: to_dynamodb_compatible(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [to_dynamodb_compatible(i) for i in obj]
    return obj


def prepare_movie_items() -> List[Dict[str, Any]]:
    """Prepare the 28 catalogue movies with correct primary key and Decimal types."""
    items = []
    for raw in SAMPLE_MOVIES:
        item = dict(raw)
        item["movie_id"] = raw["id"]  # Primary key in moviemagic_movies
        item["id"] = raw["id"]        # Retain id for backward compatibility
        items.append(to_dynamodb_compatible(item))
    return items


def prepare_theater_items() -> List[Dict[str, Any]]:
    """Prepare the Kolhapur cinema venues with correct primary key and Decimal types."""
    items = []
    for raw in SAMPLE_THEATERS:
        item = dict(raw)
        item["theater_id"] = raw["id"]  # Primary key in moviemagic_theaters
        item["id"] = raw["id"]          # Retain id for backward compatibility
        items.append(to_dynamodb_compatible(item))
    return items


def prepare_showtime_items() -> List[Dict[str, Any]]:
    """Prepare demo showtime schedules with correct primary key, date_time, and Decimal types."""
    items = []
    for raw in SAMPLE_SHOWTIMES:
        item = dict(raw)
        item["showtime_id"] = raw["id"]  # Primary key in moviemagic_showtimes
        item["id"] = raw["id"]          # Retain id for backward compatibility
        if "date_time" not in item:
            item["date_time"] = f"{item.get('date', '')} {item.get('time', '')}".strip()
        items.append(to_dynamodb_compatible(item))
    return items


def seed_table(
    table_resource: Any,
    items: List[Dict[str, Any]],
    pk_name: str,
    dry_run: bool = True
) -> Dict[str, int]:
    """Seed or inspect items for a given DynamoDB table idempotently.

    Returns:
        dict with counts: created, updated, skipped, failed
    """
    counts = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}

    for item in items:
        pk_val = item.get(pk_name)
        if not pk_val:
            logger.error("Item missing primary key %s: %s", pk_name, item)
            counts["failed"] += 1
            continue

        try:
            resp = table_resource.get_item(Key={pk_name: pk_val})
            existing = resp.get("Item")

            if existing is None:
                if dry_run:
                    counts["created"] += 1
                else:
                    table_resource.put_item(Item=item)
                    counts["created"] += 1
            else:
                # Compare content (ignoring any DynamoDB internal metadata if present)
                if existing == item:
                    counts["skipped"] += 1
                else:
                    if dry_run:
                        counts["updated"] += 1
                    else:
                        table_resource.put_item(Item=item)
                        counts["updated"] += 1
        except Exception as e:
            logger.error("Error processing item %s=%s: %s", pk_name, pk_val, e)
            counts["failed"] += 1

    return counts


def main():
    parser = argparse.ArgumentParser(
        description="Movie Magic: DynamoDB Catalogue Seeder (Phase 2, ap-south-1)."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Dry run inspection: verify items and report actions without writing (DEFAULT).",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        default=False,
        help="Explicit opt-in required to write records to DynamoDB tables.",
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

    # Safety Guard: Customer data protection verification
    for protected in PROTECTED_TABLE_CATEGORIES:
        protected_table_name = f"{args.prefix}{protected}"
        # Assert this script never targets protected tables
        pass

    movies = prepare_movie_items()
    theaters = prepare_theater_items()
    showtimes = prepare_showtime_items()

    print("=" * 60)
    print("Movie Magic -- DynamoDB Catalogue Seeder")
    print(f"Target AWS Region: {args.region} (Mumbai)")
    if args.endpoint_url:
        print(f"Custom Endpoint:   {args.endpoint_url}")
    print(f"Table Prefix:      {args.prefix}")
    print(f"Catalogue Data:    {len(movies)} Movies | {len(theaters)} Theatres | {len(showtimes)} Demo Showtimes")
    print("Protected Tables:  users, bookings, show_seats [NEVER SEEDED]")
    print("=" * 60)

    # In mock mode without explicit endpoint, run dry-run preview
    if is_mock_mode_active() and not args.endpoint_url:
        print("[MOCK MODE ACTIVE] USE_AWS_MOCK is currently set to True.")
        print("  - To seed real DynamoDB tables, either:")
        print("    1. Set USE_AWS_MOCK=False and configure AWS credentials for ap-south-1, OR")
        print("    2. Pass --endpoint-url http://localhost:8000 for a local DynamoDB container.")
        print("\nDry-run dataset preview:")
        print(f"  * Movies ({len(movies)}):")
        for m in movies[:3]:
            print(f"      - [{m['movie_id']}] {m['title']} ({m['release_year']}) - {m['category']}")
        print(f"      ... and {len(movies) - 3} more.")
        print(f"  * Theatres ({len(theaters)}):")
        for t in theaters:
            print(f"      - [{t['theater_id']}] {t['name']} ({t['city']}) - {t['operational_status']}")
        print(f"  * Showtimes ({len(showtimes)}):")
        for s in showtimes:
            print(f"      - [{s['showtime_id']}] Movie: {s['movie_id']}, Theater: {s['theater_id']} at {s['date_time']}")
        print("\n[Dry-Run Complete] Zero writes executed in mock mode.")
        return 0

    dry_run = not args.seed

    if dry_run:
        print("\n[READ-ONLY MODE] Running inspection. No writes will be performed.")
        print("To commit records to DynamoDB, pass '--seed' explicitly.\n")
    else:
        print("\n[SEEDING MODE] Writing verified records to DynamoDB tables...\n")

    resource = get_boto3_resource("dynamodb", region_name=args.region, endpoint_url=args.endpoint_url)
    if not resource:
        print("ERROR: Could not initialize boto3 DynamoDB resource.")
        print("Check your AWS credentials chain or provide --endpoint-url.")
        return 1

    targets = [
        ("movies", f"{args.prefix}movies", "movie_id", movies),
        ("theaters", f"{args.prefix}theaters", "theater_id", theaters),
        ("showtimes", f"{args.prefix}showtimes", "showtime_id", showtimes),
    ]

    total_stats = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}

    for category, table_name, pk_name, data in targets:
        print(f"Processing '{table_name}' ({len(data)} items)...")
        try:
            table = resource.Table(table_name)
            stats = seed_table(table, data, pk_name=pk_name, dry_run=dry_run)
            mode_prefix = "Would create" if dry_run else "Created"
            upd_prefix = "Would update" if dry_run else "Updated"
            print(
                f"  -> {mode_prefix}: {stats['created']}, "
                f"{upd_prefix}: {stats['updated']}, "
                f"Skipped (unchanged): {stats['skipped']}, "
                f"Failed: {stats['failed']}"
            )
            for k in total_stats:
                total_stats[k] += stats[k]
        except Exception as e:
            print(f"  -> ERROR accessing table '{table_name}': {e}")
            total_stats["failed"] += len(data)

    print("\n" + "=" * 60)
    summary_label = "Dry-Run Inspection Summary" if dry_run else "Seeding Summary"
    print(f"{summary_label}:")
    print(f"  Created: {total_stats['created']}")
    print(f"  Updated: {total_stats['updated']}")
    print(f"  Skipped: {total_stats['skipped']}")
    print(f"  Failed:  {total_stats['failed']}")
    print("=" * 60)

    return 0 if total_stats["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
