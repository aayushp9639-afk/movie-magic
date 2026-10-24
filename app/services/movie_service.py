"""Movie Service.
Coordinates movie browsing, filtering, search, theater queries, and showtime schedules.
"""
from typing import List, Dict, Any, Optional
from app.repositories import movie_repository


class MovieService:
    """Business logic for movie catalog and cinema theater schedules."""

    def __init__(self, repo=None):
        self._repo = repo

    @property
    def repo(self):
        """Active movie repository."""
        if self._repo is not None:
            return self._repo
        return movie_repository

    def get_featured_movies(self) -> List[Dict[str, Any]]:
        all_movies = self.repo.get_all()
        featured = [m for m in all_movies if m.get("is_featured")]
        return featured if featured else all_movies[:3]

    def get_top_rated_movies(self, limit: int = 8) -> List[Dict[str, Any]]:
        """Return highest-rated titles sorted by IMDb score descending."""
        all_movies = self.repo.get_all()
        sorted_movies = sorted(
            all_movies,
            key=lambda m: (float(m.get("imdb_score") or 0), int(m.get("release_year") or 0)),
            reverse=True,
        )
        return sorted_movies[:limit]

    def get_recent_and_upcoming_movies(self, limit: int = 8) -> List[Dict[str, Any]]:
        """Return newest and upcoming releases sorted by release year descending."""
        all_movies = self.repo.get_all()
        sorted_movies = sorted(
            all_movies,
            key=lambda m: (int(m.get("release_year") or 0), float(m.get("imdb_score") or 0)),
            reverse=True,
        )
        return sorted_movies[:limit]

    def get_similar_movies(self, movie: Dict[str, Any], limit: int = 4) -> List[Dict[str, Any]]:
        """Return related movies from the same category or overlapping genres, excluding the current movie."""
        if not movie:
            return []
        movie_id = movie.get("id")
        category = movie.get("category")
        candidates = [m for m in self.repo.get_all(category=category) if m.get("id") != movie_id]
        if len(candidates) < limit:
            extra = [
                m for m in self.repo.get_all()
                if m.get("id") != movie_id and m.get("id") not in {c.get("id") for c in candidates}
            ]
            candidates.extend(extra)
        candidates.sort(key=lambda m: float(m.get("imdb_score") or 0), reverse=True)
        return candidates[:limit]

    def get_movies_by_category(self, category: str) -> List[Dict[str, Any]]:
        return self.repo.get_all(category=category)

    def list_movies(
        self,
        city: Optional[str] = None,
        genre: Optional[str] = None,
        category: Optional[str] = None,
        language: Optional[str] = None,
        search_query: Optional[str] = None,
        sort_by: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        results = list(
            self.repo.get_all(
                city=city,
                genre=genre,
                category=category,
                language=language,
                search_query=search_query,
            )
        )
        if sort_by == "rating_desc":
            results.sort(key=lambda m: float(m.get("imdb_score") or 0), reverse=True)
        elif sort_by == "year_desc":
            results.sort(key=lambda m: int(m.get("release_year") or 0), reverse=True)
        elif sort_by == "year_asc":
            results.sort(key=lambda m: int(m.get("release_year") or 0))
        elif sort_by == "title_asc":
            results.sort(key=lambda m: (m.get("title") or "").lower())
        elif sort_by == "duration_desc":
            results.sort(key=lambda m: int(m.get("duration_minutes") or 0), reverse=True)
        return results

    def get_movie_by_id(self, movie_id: str) -> Optional[Dict[str, Any]]:
        return self.repo.get_by_id(movie_id)

    def add_movie(self, movie_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.repo.add_movie(movie_data)

    def update_movie(self, movie_id: str, movie_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.repo.update_movie(movie_id, movie_data)

    def delete_movie(self, movie_id: str) -> bool:
        return self.repo.delete_movie(movie_id)

    # -------------------------------------------------------------------------
    # Theater Management
    # -------------------------------------------------------------------------
    def get_theaters(self, city: Optional[str] = None, operational_only: bool = False) -> List[Dict[str, Any]]:
        return self.repo.get_theaters(city=city, operational_only=operational_only)

    def get_theater_by_id(self, theater_id: str) -> Optional[Dict[str, Any]]:
        return self.repo.get_theater_by_id(theater_id)

    def add_theater(self, theater_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.repo.add_theater(theater_data)

    def update_theater(self, theater_id: str, theater_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.repo.update_theater(theater_id, theater_data)

    # -------------------------------------------------------------------------
    # Showtime Management
    # -------------------------------------------------------------------------
    def get_showtimes(
        self,
        movie_id: Optional[str] = None,
        theater_id: Optional[str] = None,
        date: Optional[str] = None,
        verified_only: bool = False,
    ) -> List[Dict[str, Any]]:
        return self.repo.get_showtimes(
            movie_id=movie_id,
            theater_id=theater_id,
            date=date,
            verified_only=verified_only,
        )

    def get_showtime_by_id(self, show_id: str) -> Optional[Dict[str, Any]]:
        return self.repo.get_showtime_by_id(show_id)

    def add_showtime(self, show_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.repo.add_showtime(show_data)

    def update_showtime(self, show_id: str, show_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return self.repo.update_showtime(show_id, show_data)

    def delete_showtime(self, show_id: str) -> bool:
        return self.repo.delete_showtime(show_id)

    # -------------------------------------------------------------------------
    # Filter Metadata
    # -------------------------------------------------------------------------
    def get_available_cities(self) -> List[str]:
        return self.repo.get_cities()

    def get_available_categories(self) -> List[str]:
        return self.repo.get_categories()

    def get_available_languages(self) -> List[str]:
        return self.repo.get_languages()

    def get_available_genres(self) -> List[str]:
        return self.repo.get_genres()


movie_service = MovieService()
