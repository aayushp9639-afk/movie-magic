"""Movie, Theater & Showtime Repository layer supporting both In-Memory (Mock) and DynamoDB implementations.

Features:
- Full support for 28 movies, 5 Kolhapur cinema venues, and separated demo showtimes.
- Query optimization leveraging GSIs:
    * CategoryIndex on moviemagic_movies (category + release_year)
    * CityStatusIndex on moviemagic_theaters (city + operational_status)
    * MovieShowtimeIndex on moviemagic_showtimes (movie_id + date_time)
    * TheaterShowtimeIndex on moviemagic_showtimes (theater_id + date_time)
- Safe pagination across scans and queries.
- Decimal type conversion to float/int for template & JSON rendering.
- Strict anti-degradation rule: USE_AWS_MOCK=False never silently falls back to mock.
- Transparent MovieRepositoryProxy preserving backward-compatible movie_repository imports.
"""

import logging
import os
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

from app.aws.client_factory import get_boto3_client, is_mock_mode_active
from app.data.sample_movies import (
    SAMPLE_MOVIES,
    SAMPLE_THEATERS,
    SAMPLE_SHOWTIMES,
    SAMPLE_CITIES,
    SAMPLE_CATEGORIES,
    SAMPLE_LANGUAGES,
    SAMPLE_GENRES,
    SEAT_TIERS,
)
from .base import BaseRepository

logger = logging.getLogger(__name__)
_deserializer = TypeDeserializer()
_serializer = TypeSerializer()


class CataloguePersistenceError(RuntimeError):
    """Raised when movie, theatre, or showtime operations fail due to a database/service error."""
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


def execute_paginated_query(client, table_name: str, **kwargs) -> List[Dict[str, Any]]:
    """Query a table/GSI handling DynamoDB pagination safely."""
    items = []
    query_kwargs = dict(kwargs)
    query_kwargs["TableName"] = table_name

    while True:
        resp = client.query(**query_kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
        query_kwargs["ExclusiveStartKey"] = last_key
    return items


class InMemoryMovieRepository(BaseRepository):
    """Movie catalog, cinema venue, and showtime in-memory repository for local development/testing."""

    def __init__(self):
        self._movies: Dict[str, Dict[str, Any]] = {}
        self._theaters: Dict[str, Dict[str, Any]] = {}
        self._showtimes: Dict[str, Dict[str, Any]] = {}
        self._cities: List[str] = list(SAMPLE_CITIES)
        self._categories: List[str] = list(SAMPLE_CATEGORIES)
        self._languages: List[str] = list(SAMPLE_LANGUAGES)
        self._genres: List[str] = list(SAMPLE_GENRES)
        self._seed_data()

    def _seed_data(self):
        for movie in SAMPLE_MOVIES:
            self._movies[movie["id"]] = dict(movie)
        for theater in SAMPLE_THEATERS:
            self._theaters[theater["id"]] = dict(theater)
        for show in SAMPLE_SHOWTIMES:
            self._showtimes[show["id"]] = dict(show)

    def get_by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self._movies.get(str(item_id).strip() if item_id else "")

    def get_all(
        self,
        city: Optional[str] = None,
        genre: Optional[str] = None,
        category: Optional[str] = None,
        language: Optional[str] = None,
        search_query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        results = list(self._movies.values())

        if category and category != "All":
            results = [m for m in results if m.get("category", "").lower() == category.lower()]

        if genre and genre != "All":
            results = [m for m in results if genre.lower() in m.get("genre", "").lower()]

        if language and language != "All":
            results = [
                m for m in results
                if m.get("language", "").lower() == language.lower()
                or any(language.lower() in d.lower() for d in m.get("dubbed_languages", []))
            ]

        if search_query:
            query = search_query.strip().lower()
            results = [
                m for m in results
                if query in m.get("title", "").lower()
                or query in m.get("original_title", "").lower()
                or query in m.get("synopsis", "").lower()
                or query in m.get("director", "").lower()
                or query in m.get("genre", "").lower()
                or query in m.get("category", "").lower()
                or query in m.get("language", "").lower()
                or any(query in actor.lower() for actor in m.get("cast", []))
            ]

        return results

    def add_movie(self, movie_data: Dict[str, Any]) -> Dict[str, Any]:
        movie_id = movie_data.get("id") or movie_data.get("movie_id") or f"mov-{uuid.uuid4().hex[:8]}"
        new_movie = dict(movie_data)
        new_movie["id"] = movie_id
        new_movie["movie_id"] = movie_id
        new_movie.setdefault("badge", "New Release")
        new_movie.setdefault("category", "General")
        new_movie.setdefault("language", "English")
        new_movie.setdefault("poster_color", "#1e293b")
        new_movie.setdefault("accent_color", "#6366f1")
        new_movie.setdefault("bg_gradient", "linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%)")
        self._movies[movie_id] = new_movie
        return new_movie

    def update_movie(self, movie_id: str, movie_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if movie_id not in self._movies:
            return None
        self._movies[movie_id].update(movie_data)
        return self._movies[movie_id]

    def delete_movie(self, movie_id: str) -> bool:
        if movie_id in self._movies:
            del self._movies[movie_id]
            self._showtimes = {
                s_id: s for s_id, s in self._showtimes.items() if s.get("movie_id") != movie_id
            }
            return True
        return False

    def get_theaters(self, city: Optional[str] = None, operational_only: bool = False) -> List[Dict[str, Any]]:
        theaters = list(self._theaters.values())
        if city and city != "All":
            theaters = [t for t in theaters if t.get("city", "").lower() == city.lower()]
        if operational_only:
            theaters = [
                t for t in theaters
                if t.get("operational_status") == "Operational" and t.get("is_verified") is True
            ]
        return theaters

    def get_theater_by_id(self, theater_id: str) -> Optional[Dict[str, Any]]:
        return self._theaters.get(str(theater_id).strip() if theater_id else "")

    def add_theater(self, theater_data: Dict[str, Any]) -> Dict[str, Any]:
        theater_id = theater_data.get("id") or theater_data.get("theater_id") or f"th-{uuid.uuid4().hex[:8]}"
        new_th = dict(theater_data)
        new_th["id"] = theater_id
        new_th["theater_id"] = theater_id
        self._theaters[theater_id] = new_th
        return new_th

    def update_theater(self, theater_id: str, theater_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if theater_id not in self._theaters:
            return None
        self._theaters[theater_id].update(theater_data)
        return self._theaters[theater_id]

    def get_showtimes(
        self,
        movie_id: Optional[str] = None,
        theater_id: Optional[str] = None,
        date: Optional[str] = None,
        verified_only: bool = False,
    ) -> List[Dict[str, Any]]:
        shows = list(self._showtimes.values())

        if movie_id:
            shows = [s for s in shows if s.get("movie_id") == movie_id]

        if theater_id:
            shows = [s for s in shows if s.get("theater_id") == theater_id]

        if date and date != "All":
            shows = [s for s in shows if s.get("date", "").lower() == date.lower()]

        if verified_only:
            shows = [s for s in shows if s.get("is_verified") is True]

        enriched = []
        for s in shows:
            item = dict(s)
            th = self.get_theater_by_id(s.get("theater_id", ""))
            mov = self.get_by_id(s.get("movie_id", ""))
            item["theater_name"] = th.get("name") if th else "Unknown Venue"
            item["theater_city"] = th.get("city") if th else "Kolhapur"
            item["theater_verified"] = th.get("is_verified") if th else False
            item["movie_title"] = mov.get("title") if mov else "Unknown Movie"
            enriched.append(item)

        return enriched

    def get_showtime_by_id(self, show_id: str) -> Optional[Dict[str, Any]]:
        show = self._showtimes.get(str(show_id).strip() if show_id else "")
        if not show:
            return None
        item = dict(show)
        th = self.get_theater_by_id(show.get("theater_id", ""))
        mov = self.get_by_id(show.get("movie_id", ""))
        item["theater_name"] = th.get("name") if th else "Unknown Venue"
        item["theater_city"] = th.get("city") if th else "Kolhapur"
        item["theater_verified"] = th.get("is_verified") if th else False
        item["movie_title"] = mov.get("title") if mov else "Unknown Movie"
        return item

    def add_showtime(self, show_data: Dict[str, Any]) -> Dict[str, Any]:
        show_id = show_data.get("id") or show_data.get("showtime_id") or f"show-{uuid.uuid4().hex[:8]}"
        new_show = dict(show_data)
        new_show["id"] = show_id
        new_show["showtime_id"] = show_id
        new_show.setdefault("is_verified", False)
        new_show.setdefault("status", "Verified" if new_show["is_verified"] else "Demo / Sample")
        self._showtimes[show_id] = new_show
        return new_show

    def update_showtime(self, show_id: str, show_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if show_id not in self._showtimes:
            return None
        self._showtimes[show_id].update(show_data)
        return self._showtimes[show_id]

    def delete_showtime(self, show_id: str) -> bool:
        if show_id in self._showtimes:
            del self._showtimes[show_id]
            return True
        return False

    def get_cities(self) -> List[str]:
        return list(self._cities)

    def get_categories(self) -> List[str]:
        return list(self._categories)

    def get_languages(self) -> List[str]:
        return list(self._languages)

    def get_genres(self) -> List[str]:
        return list(self._genres)

    def get_seat_tiers(self) -> Dict[str, Any]:
        return dict(SEAT_TIERS)


class DynamoDBMovieRepository(BaseRepository):
    """DynamoDB repository for movie catalogue, cinema venues, and showtime schedules."""

    def __init__(
        self,
        client: Optional[Any] = None,
        table_prefix: Optional[str] = None,
    ):
        self.client = client
        prefix = table_prefix or os.environ.get("DYNAMODB_TABLE_PREFIX", "moviemagic_")
        self.movies_table = f"{prefix}movies"
        self.theaters_table = f"{prefix}theaters"
        self.showtimes_table = f"{prefix}showtimes"

        self._cities: List[str] = list(SAMPLE_CITIES)
        self._categories: List[str] = list(SAMPLE_CATEGORIES)
        self._languages: List[str] = list(SAMPLE_LANGUAGES)
        self._genres: List[str] = list(SAMPLE_GENRES)

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

    # -------------------------------------------------------------------------
    # Movie Catalog Queries
    # -------------------------------------------------------------------------
    def get_by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        self._ensure_client()
        if not item_id:
            return None
        clean_id = str(item_id).strip()
        try:
            resp = self.client.get_item(
                TableName=self.movies_table,
                Key={"movie_id": {"S": clean_id}},
            )
            raw = resp.get("Item")
            if not raw:
                return None
            return deserialize_dynamodb_item(raw, id_key="movie_id")
        except ClientError as e:
            logger.error("DynamoDB get_by_id error for movie %s: %s", clean_id, e)
            raise CataloguePersistenceError(f"Database error retrieving movie by ID: {e}")

    def get_all(
        self,
        city: Optional[str] = None,
        genre: Optional[str] = None,
        category: Optional[str] = None,
        language: Optional[str] = None,
        search_query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        self._ensure_client()
        try:
            # Query CategoryIndex GSI when category is filtered; otherwise scan with pagination
            if category and category != "All":
                raw_items = execute_paginated_query(
                    self.client,
                    self.movies_table,
                    IndexName="CategoryIndex",
                    KeyConditionExpression="#cat = :cat",
                    ExpressionAttributeNames={"#cat": "category"},
                    ExpressionAttributeValues={":cat": {"S": category}},
                )
            else:
                raw_items = execute_paginated_scan(self.client, self.movies_table)

            results = [deserialize_dynamodb_item(r, id_key="movie_id") for r in raw_items]

            if genre and genre != "All":
                results = [m for m in results if genre.lower() in m.get("genre", "").lower()]

            if language and language != "All":
                results = [
                    m for m in results
                    if m.get("language", "").lower() == language.lower()
                    or any(language.lower() in d.lower() for d in m.get("dubbed_languages", []))
                ]

            if search_query:
                query = search_query.strip().lower()
                results = [
                    m for m in results
                    if query in m.get("title", "").lower()
                    or query in m.get("original_title", "").lower()
                    or query in m.get("synopsis", "").lower()
                    or query in m.get("director", "").lower()
                    or query in m.get("genre", "").lower()
                    or query in m.get("category", "").lower()
                    or query in m.get("language", "").lower()
                    or any(query in actor.lower() for actor in m.get("cast", []))
                ]

            return results
        except ClientError as e:
            logger.error("DynamoDB get_all movies error: %s", e)
            raise CataloguePersistenceError(f"Database error listing movies: {e}")

    def add_movie(self, movie_data: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_client()
        movie_id = movie_data.get("id") or movie_data.get("movie_id") or f"mov-{uuid.uuid4().hex[:8]}"
        new_movie = dict(movie_data)
        new_movie["movie_id"] = movie_id
        new_movie["id"] = movie_id
        new_movie.setdefault("badge", "New Release")
        new_movie.setdefault("category", "General")
        new_movie.setdefault("language", "English")
        new_movie.setdefault("poster_color", "#1e293b")
        new_movie.setdefault("accent_color", "#6366f1")
        new_movie.setdefault("bg_gradient", "linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%)")
        new_movie.setdefault("release_year", 2026)

        serialized = serialize_dynamodb_item(new_movie)
        try:
            self.client.put_item(TableName=self.movies_table, Item=serialized)
            return new_movie
        except ClientError as e:
            logger.error("DynamoDB add_movie error: %s", e)
            raise CataloguePersistenceError(f"Database error adding movie: {e}")

    def update_movie(self, movie_id: str, movie_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self._ensure_client()
        clean_id = str(movie_id).strip()
        existing = self.get_by_id(clean_id)
        if not existing:
            return None
        existing.update(movie_data)
        existing["movie_id"] = clean_id
        existing["id"] = clean_id
        serialized = serialize_dynamodb_item(existing)
        try:
            self.client.put_item(TableName=self.movies_table, Item=serialized)
            return existing
        except ClientError as e:
            logger.error("DynamoDB update_movie error: %s", e)
            raise CataloguePersistenceError(f"Database error updating movie: {e}")

    def delete_movie(self, movie_id: str) -> bool:
        self._ensure_client()
        clean_id = str(movie_id).strip()
        try:
            self.client.delete_item(
                TableName=self.movies_table,
                Key={"movie_id": {"S": clean_id}},
            )
            # Clean up associated showtimes via MovieShowtimeIndex
            associated_shows = self.get_showtimes(movie_id=clean_id)
            for show in associated_shows:
                show_id = show.get("id") or show.get("showtime_id")
                if show_id:
                    self.delete_showtime(show_id)
            return True
        except ClientError as e:
            logger.error("DynamoDB delete_movie error: %s", e)
            raise CataloguePersistenceError(f"Database error deleting movie: {e}")

    # -------------------------------------------------------------------------
    # Theater Venue Queries
    # -------------------------------------------------------------------------
    def get_theater_by_id(self, theater_id: str) -> Optional[Dict[str, Any]]:
        self._ensure_client()
        if not theater_id:
            return None
        clean_id = str(theater_id).strip()
        try:
            resp = self.client.get_item(
                TableName=self.theaters_table,
                Key={"theater_id": {"S": clean_id}},
            )
            raw = resp.get("Item")
            if not raw:
                return None
            return deserialize_dynamodb_item(raw, id_key="theater_id")
        except ClientError as e:
            logger.error("DynamoDB get_theater_by_id error for theater %s: %s", clean_id, e)
            raise CataloguePersistenceError(f"Database error retrieving theater by ID: {e}")

    def get_theaters(self, city: Optional[str] = None, operational_only: bool = False) -> List[Dict[str, Any]]:
        self._ensure_client()
        try:
            # Query CityStatusIndex GSI when city is specified
            if city and city != "All":
                if operational_only:
                    raw_items = execute_paginated_query(
                        self.client,
                        self.theaters_table,
                        IndexName="CityStatusIndex",
                        KeyConditionExpression="#city = :city AND #status = :status",
                        ExpressionAttributeNames={"#city": "city", "#status": "operational_status"},
                        ExpressionAttributeValues={":city": {"S": city}, ":status": {"S": "Operational"}},
                    )
                else:
                    raw_items = execute_paginated_query(
                        self.client,
                        self.theaters_table,
                        IndexName="CityStatusIndex",
                        KeyConditionExpression="#city = :city",
                        ExpressionAttributeNames={"#city": "city"},
                        ExpressionAttributeValues={":city": {"S": city}},
                    )
            else:
                raw_items = execute_paginated_scan(self.client, self.theaters_table)

            theaters = [deserialize_dynamodb_item(r, id_key="theater_id") for r in raw_items]

            if operational_only:
                theaters = [
                    t for t in theaters
                    if t.get("operational_status") == "Operational" and t.get("is_verified") is True
                ]
            return theaters
        except ClientError as e:
            logger.error("DynamoDB get_theaters error: %s", e)
            raise CataloguePersistenceError(f"Database error retrieving theaters: {e}")

    def add_theater(self, theater_data: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_client()
        theater_id = theater_data.get("id") or theater_data.get("theater_id") or f"th-{uuid.uuid4().hex[:8]}"
        new_th = dict(theater_data)
        new_th["theater_id"] = theater_id
        new_th["id"] = theater_id
        serialized = serialize_dynamodb_item(new_th)
        try:
            self.client.put_item(TableName=self.theaters_table, Item=serialized)
            return new_th
        except ClientError as e:
            logger.error("DynamoDB add_theater error: %s", e)
            raise CataloguePersistenceError(f"Database error adding theater: {e}")

    def update_theater(self, theater_id: str, theater_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self._ensure_client()
        clean_id = str(theater_id).strip()
        existing = self.get_theater_by_id(clean_id)
        if not existing:
            return None
        existing.update(theater_data)
        existing["theater_id"] = clean_id
        existing["id"] = clean_id
        serialized = serialize_dynamodb_item(existing)
        try:
            self.client.put_item(TableName=self.theaters_table, Item=serialized)
            return existing
        except ClientError as e:
            logger.error("DynamoDB update_theater error: %s", e)
            raise CataloguePersistenceError(f"Database error updating theater: {e}")

    # -------------------------------------------------------------------------
    # Showtime Queries (Separated from Movies)
    # -------------------------------------------------------------------------
    def get_showtime_by_id(self, show_id: str) -> Optional[Dict[str, Any]]:
        self._ensure_client()
        if not show_id:
            return None
        clean_id = str(show_id).strip()
        try:
            resp = self.client.get_item(
                TableName=self.showtimes_table,
                Key={"showtime_id": {"S": clean_id}},
            )
            raw = resp.get("Item")
            if not raw:
                return None
            item = deserialize_dynamodb_item(raw, id_key="showtime_id")
            # Enrich with theater & movie details for UI display
            th = self.get_theater_by_id(item.get("theater_id", ""))
            mov = self.get_by_id(item.get("movie_id", ""))
            item["theater_name"] = th.get("name") if th else "Unknown Venue"
            item["theater_city"] = th.get("city") if th else "Kolhapur"
            item["theater_verified"] = th.get("is_verified") if th else False
            item["movie_title"] = mov.get("title") if mov else "Unknown Movie"
            return item
        except ClientError as e:
            logger.error("DynamoDB get_showtime_by_id error for show %s: %s", clean_id, e)
            raise CataloguePersistenceError(f"Database error retrieving showtime by ID: {e}")

    def get_showtimes(
        self,
        movie_id: Optional[str] = None,
        theater_id: Optional[str] = None,
        date: Optional[str] = None,
        verified_only: bool = False,
    ) -> List[Dict[str, Any]]:
        self._ensure_client()
        try:
            # Query MovieShowtimeIndex or TheaterShowtimeIndex when available
            if movie_id:
                raw_items = execute_paginated_query(
                    self.client,
                    self.showtimes_table,
                    IndexName="MovieShowtimeIndex",
                    KeyConditionExpression="movie_id = :mid",
                    ExpressionAttributeValues={":mid": {"S": movie_id}},
                )
            elif theater_id:
                raw_items = execute_paginated_query(
                    self.client,
                    self.showtimes_table,
                    IndexName="TheaterShowtimeIndex",
                    KeyConditionExpression="theater_id = :tid",
                    ExpressionAttributeValues={":tid": {"S": theater_id}},
                )
            else:
                raw_items = execute_paginated_scan(self.client, self.showtimes_table)

            shows = [deserialize_dynamodb_item(r, id_key="showtime_id") for r in raw_items]

            if movie_id and theater_id:
                shows = [s for s in shows if s.get("theater_id") == theater_id]

            if date and date != "All":
                shows = [s for s in shows if s.get("date", "").lower() == date.lower()]

            if verified_only:
                shows = [s for s in shows if s.get("is_verified") is True]

            # Enrich each showtime with theater & movie metadata
            enriched = []
            for s in shows:
                item = dict(s)
                th = self.get_theater_by_id(s.get("theater_id", ""))
                mov = self.get_by_id(s.get("movie_id", ""))
                item["theater_name"] = th.get("name") if th else "Unknown Venue"
                item["theater_city"] = th.get("city") if th else "Kolhapur"
                item["theater_verified"] = th.get("is_verified") if th else False
                item["movie_title"] = mov.get("title") if mov else "Unknown Movie"
                enriched.append(item)

            return enriched
        except ClientError as e:
            logger.error("DynamoDB get_showtimes error: %s", e)
            raise CataloguePersistenceError(f"Database error retrieving showtimes: {e}")

    def add_showtime(self, show_data: Dict[str, Any]) -> Dict[str, Any]:
        self._ensure_client()
        show_id = show_data.get("id") or show_data.get("showtime_id") or f"show-{uuid.uuid4().hex[:8]}"
        new_show = dict(show_data)
        new_show["showtime_id"] = show_id
        new_show["id"] = show_id
        new_show.setdefault("is_verified", False)
        new_show.setdefault("status", "Verified" if new_show["is_verified"] else "Demo / Sample")
        if "date_time" not in new_show:
            new_show["date_time"] = f"{new_show.get('date', '')} {new_show.get('time', '')}".strip()

        serialized = serialize_dynamodb_item(new_show)
        try:
            self.client.put_item(TableName=self.showtimes_table, Item=serialized)
            return new_show
        except ClientError as e:
            logger.error("DynamoDB add_showtime error: %s", e)
            raise CataloguePersistenceError(f"Database error adding showtime: {e}")

    def update_showtime(self, show_id: str, show_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self._ensure_client()
        clean_id = str(show_id).strip()
        existing = self.get_showtime_by_id(clean_id)
        if not existing:
            return None
        existing.update(show_data)
        existing["showtime_id"] = clean_id
        existing["id"] = clean_id
        if "date_time" not in existing:
            existing["date_time"] = f"{existing.get('date', '')} {existing.get('time', '')}".strip()
        serialized = serialize_dynamodb_item(existing)
        try:
            self.client.put_item(TableName=self.showtimes_table, Item=serialized)
            return existing
        except ClientError as e:
            logger.error("DynamoDB update_showtime error: %s", e)
            raise CataloguePersistenceError(f"Database error updating showtime: {e}")

    def delete_showtime(self, show_id: str) -> bool:
        self._ensure_client()
        clean_id = str(show_id).strip()
        try:
            self.client.delete_item(
                TableName=self.showtimes_table,
                Key={"showtime_id": {"S": clean_id}},
            )
            return True
        except ClientError as e:
            logger.error("DynamoDB delete_showtime error: %s", e)
            raise CataloguePersistenceError(f"Database error deleting showtime: {e}")

    # -------------------------------------------------------------------------
    # Metadata Lookups
    # -------------------------------------------------------------------------
    def get_cities(self) -> List[str]:
        return list(self._cities)

    def get_categories(self) -> List[str]:
        return list(self._categories)

    def get_languages(self) -> List[str]:
        return list(self._languages)

    def get_genres(self) -> List[str]:
        return list(self._genres)

    def get_seat_tiers(self) -> Dict[str, Any]:
        return dict(SEAT_TIERS)


_in_memory_instance: Optional[InMemoryMovieRepository] = None
_dynamo_instance: Optional[DynamoDBMovieRepository] = None


def get_movie_repository() -> BaseRepository:
    """Resolve movie repository according to active configuration.

    Guarantees:
    - If USE_AWS_MOCK is True, returns InMemoryMovieRepository singleton.
    - If USE_AWS_MOCK is False, returns DynamoDBMovieRepository.
    - NEVER silently degrades to mock mode if live mode is misconfigured.
    """
    global _in_memory_instance, _dynamo_instance

    if is_mock_mode_active():
        if _in_memory_instance is None:
            _in_memory_instance = InMemoryMovieRepository()
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
        _dynamo_instance = DynamoDBMovieRepository(client=client)
    return _dynamo_instance


class MovieRepositoryProxy(BaseRepository):
    """Transparent proxy delegating calls to the active MovieRepository."""

    @property
    def active_repo(self) -> BaseRepository:
        return get_movie_repository()

    def get_by_id(self, item_id: str) -> Optional[Dict[str, Any]]:
        return self.active_repo.get_by_id(item_id)

    def get_all(
        self,
        city: Optional[str] = None,
        genre: Optional[str] = None,
        category: Optional[str] = None,
        language: Optional[str] = None,
        search_query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return self.active_repo.get_all(
            city=city,
            genre=genre,
            category=category,
            language=language,
            search_query=search_query,
        )

    def add_movie(self, movie_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.active_repo.add_movie(movie_data)

    def update_movie(self, movie_id: str, movie_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.active_repo.update_movie(movie_id, movie_data)

    def delete_movie(self, movie_id: str) -> bool:
        return self.active_repo.delete_movie(movie_id)

    def get_theaters(self, city: Optional[str] = None, operational_only: bool = False) -> List[Dict[str, Any]]:
        return self.active_repo.get_theaters(city=city, operational_only=operational_only)

    def get_theater_by_id(self, theater_id: str) -> Optional[Dict[str, Any]]:
        return self.active_repo.get_theater_by_id(theater_id)

    def add_theater(self, theater_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.active_repo.add_theater(theater_data)

    def update_theater(self, theater_id: str, theater_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.active_repo.update_theater(theater_id, theater_data)

    def get_showtimes(
        self,
        movie_id: Optional[str] = None,
        theater_id: Optional[str] = None,
        date: Optional[str] = None,
        verified_only: bool = False,
    ) -> List[Dict[str, Any]]:
        return self.active_repo.get_showtimes(
            movie_id=movie_id,
            theater_id=theater_id,
            date=date,
            verified_only=verified_only,
        )

    def get_showtime_by_id(self, show_id: str) -> Optional[Dict[str, Any]]:
        return self.active_repo.get_showtime_by_id(show_id)

    def add_showtime(self, show_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.active_repo.add_showtime(show_data)

    def update_showtime(self, show_id: str, show_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.active_repo.update_showtime(show_id, show_data)

    def delete_showtime(self, show_id: str) -> bool:
        return self.active_repo.delete_showtime(show_id)

    def get_cities(self) -> List[str]:
        return self.active_repo.get_cities()

    def get_categories(self) -> List[str]:
        return self.active_repo.get_categories()

    def get_languages(self) -> List[str]:
        return self.active_repo.get_languages()

    def get_genres(self) -> List[str]:
        return self.active_repo.get_genres()

    def get_seat_tiers(self) -> Dict[str, Any]:
        return self.active_repo.get_seat_tiers()


movie_repository = MovieRepositoryProxy()
MovieRepository = InMemoryMovieRepository  # Backward compatibility alias
