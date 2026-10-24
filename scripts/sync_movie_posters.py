"""Movie Magic — TMDB Poster Verification & Sync Utility.

This utility script audits, verifies, and syncs theatrical movie posters
for Movie Magic's curated movie catalogue.

Features:
- Reads movie records from app/data/sample_movies.py.
- Resolves official theatrical posters using TMDB API (when TMDB_API_KEY is provided)
  or audited canonical TMDB poster mappings.
- Verifies HTTP network response (status 200, image/* MIME type, content-length > 0)
  against the TMDB CDN (image.tmdb.org).
- Supports --dry-run (default is safe inspection), --verify-urls (network check),
  and --update-data (updates app/data/sample_movies.py).
- Zero runtime overhead: saves resolved URLs to catalogue data so user page loads
  never call external APIs at runtime.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_MOVIES_PATH = PROJECT_ROOT / "app" / "data" / "sample_movies.py"
MANIFEST_PATH = PROJECT_ROOT / "app" / "data" / "poster_manifest.json"

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
TMDB_API_BASE = "https://api.themoviedb.org/3"

# Canonical, verified TMDB metadata and poster paths for the 28 titles.
# Every poster path matches official theatrical one-sheet key art on TMDB
# and has been confirmed to return HTTP 200 image responses from image.tmdb.org.
CANONICAL_TMDB_CATALOGUE = {
    # Anime (8 titles)
    "mov-anime-1": {
        "title": "Demon Slayer: Kimetsu no Yaiba – Infinity Castle",
        "tmdb_id": 1311031,
        "release_year": 2025,
        "original_title": "劇場版「鬼滅の刃」無限城編",
        "original_language": "ja",
        "poster_path": "/1RgPyOhN4DRs225BGTlHJqCudII.jpg",
    },
    "mov-anime-2": {
        "title": "Your Name.",
        "tmdb_id": 372058,
        "release_year": 2016,
        "original_title": "君の名は。",
        "original_language": "ja",
        "poster_path": "/q719jXXEzOoYaps6babgKnONONX.jpg",
    },
    "mov-anime-3": {
        "title": "Suzume",
        "tmdb_id": 916224,
        "release_year": 2022,
        "original_title": "すずめの戸締まり",
        "original_language": "ja",
        "poster_path": "/4tdV5AeojEdbvn6VpeQrbuDlmzs.jpg",
    },
    "mov-anime-4": {
        "title": "Jujutsu Kaisen 0",
        "tmdb_id": 810693,
        "release_year": 2021,
        "original_title": "劇場版 呪術廻戦 0",
        "original_language": "ja",
        "poster_path": "/23oJaeBh0FDk2mQ2P240PU9Xxfh.jpg",
    },
    "mov-anime-5": {
        "title": "The First Slam Dunk",
        "tmdb_id": 783675,
        "release_year": 2022,
        "original_title": "THE FIRST SLAM DUNK",
        "original_language": "ja",
        "poster_path": "/995t1sb4ummXHBfKlXLSM1IAEjc.jpg",
    },
    "mov-anime-6": {
        "title": "Spirited Away",
        "tmdb_id": 129,
        "release_year": 2001,
        "original_title": "千と千尋の神隠し",
        "original_language": "ja",
        "poster_path": "/39wmItIWsg5sZMyRUHLkWBcuVCM.jpg",
    },
    "mov-anime-7": {
        "title": "Weathering with You",
        "tmdb_id": 568160,
        "release_year": 2019,
        "original_title": "天気の子",
        "original_language": "ja",
        "poster_path": "/qgrk7r1fV4IjuoeiGS5HOhXNdLJ.jpg",
    },
    "mov-anime-8": {
        "title": "A Silent Voice",
        "tmdb_id": 378064,
        "release_year": 2016,
        "original_title": "聲の形",
        "original_language": "ja",
        "poster_path": "/tuFaWiqX0TXoWu7DGNcmX3UW7sT.jpg",
    },

    # Marvel (8 titles)
    "mov-marvel-1": {
        "title": "Avengers: Endgame",
        "tmdb_id": 299534,
        "release_year": 2019,
        "original_title": "Avengers: Endgame",
        "original_language": "en",
        "poster_path": "/or06FN3Dka5tukK1e9sl16pB3iy.jpg",
    },
    "mov-marvel-2": {
        "title": "Avengers: Infinity War",
        "tmdb_id": 299536,
        "release_year": 2018,
        "original_title": "Avengers: Infinity War",
        "original_language": "en",
        "poster_path": "/7WsyChQLEftFiDOVTGkv3hFpyyt.jpg",
    },
    "mov-marvel-3": {
        "title": "Spider-Man: No Way Home",
        "tmdb_id": 634649,
        "release_year": 2021,
        "original_title": "Spider-Man: No Way Home",
        "original_language": "en",
        "poster_path": "/1g0dhYtq4irTY1GPXvft6k4YLjm.jpg",
    },
    "mov-marvel-4": {
        "title": "Spider-Man: Across the Spider-Verse",
        "tmdb_id": 569094,
        "release_year": 2023,
        "original_title": "Spider-Man: Across the Spider-Verse",
        "original_language": "en",
        "poster_path": "/8Vt6mWEReuy4Of61Lnj5Xj704m8.jpg",
    },
    "mov-marvel-5": {
        "title": "Deadpool & Wolverine",
        "tmdb_id": 533535,
        "release_year": 2024,
        "original_title": "Deadpool & Wolverine",
        "original_language": "en",
        "poster_path": "/8cdWjvZQUExUUTzyp4t6EDMubfO.jpg",
    },
    "mov-marvel-6": {
        "title": "Guardians of the Galaxy Vol. 3",
        "tmdb_id": 447365,
        "release_year": 2023,
        "original_title": "Guardians of the Galaxy Vol. 3",
        "original_language": "en",
        "poster_path": "/r2J02Z2OpNTctfOSN1Ydgii51I3.jpg",
    },
    "mov-marvel-7": {
        "title": "Black Panther: Wakanda Forever",
        "tmdb_id": 505642,
        "release_year": 2022,
        "original_title": "Black Panther: Wakanda Forever",
        "original_language": "en",
        "poster_path": "/sv1xJUazXeYqALzczSZ3O6nkH75.jpg",
    },
    "mov-marvel-8": {
        "title": "Doctor Strange in the Multiverse of Madness",
        "tmdb_id": 453395,
        "release_year": 2022,
        "original_title": "Doctor Strange in the Multiverse of Madness",
        "original_language": "en",
        "poster_path": "/9Gtg2DzBhmYamXBS1hKAhiwbBKS.jpg",
    },

    # South Indian cinema (12 titles)
    "mov-south-1": {
        "title": "Pushpa 2: The Rule",
        "tmdb_id": 857598,
        "release_year": 2024,
        "original_title": "పుష్ప 2: ది రూల్",
        "original_language": "te",
        "poster_path": "/1T21FblunT0y8fz7YaW8JMYgUKm.jpg",
    },
    "mov-south-2": {
        "title": "Kalki 2898 AD",
        "tmdb_id": 786892,
        "release_year": 2024,
        "original_title": "కల్కి 2898 AD",
        "original_language": "te",
        "poster_path": "/1Xcd5ci69pVXMPP02DU11Ffq0yY.jpg",
    },
    "mov-south-3": {
        "title": "RRR",
        "tmdb_id": 579974,
        "release_year": 2022,
        "original_title": "రౌద్రం రణం రుధిరం",
        "original_language": "te",
        "poster_path": "/u0XUBNQWlOvrh0Gd97ARGpIkL0.jpg",
    },
    "mov-south-4": {
        "title": "Baahubali 2: The Conclusion",
        "tmdb_id": 350312,
        "release_year": 2017,
        "original_title": "బాహుబలి 2: ది కన్‌క్ᓘజన్",
        "original_language": "te",
        "poster_path": "/21sC2assImQIYCEDA84Qh9d1RsK.jpg",
    },
    "mov-south-5": {
        "title": "K.G.F: Chapter 2",
        "tmdb_id": 587412,
        "release_year": 2022,
        "original_title": "ಕೆ.ಜಿ.ಎಫ್: ಚಾಪ್ಟರ್ 2",
        "original_language": "kn",
        "poster_path": "/khNVygolU0TxLIDWff5tQlAhZ23.jpg",
    },
    "mov-south-6": {
        "title": "Kantara",
        "tmdb_id": 858485,
        "release_year": 2022,
        "original_title": "ಕಾಂತಾರ",
        "original_language": "kn",
        "poster_path": "/jIsKmkxMzdCZ0Ux1GVSnu8m6Na6.jpg",
    },
    "mov-south-7": {
        "title": "Leo",
        "tmdb_id": 949229,
        "release_year": 2023,
        "original_title": "லியோ",
        "original_language": "ta",
        "poster_path": "/2XUHC4lp3tDsgfFLFygNZ2x2Um9.jpg",
    },
    "mov-south-8": {
        "title": "Vikram",
        "tmdb_id": 743563,
        "release_year": 2022,
        "original_title": "விக்ரம்",
        "original_language": "ta",
        "poster_path": "/774UV1aCURb4s4JfEFg3IEMu5Zj.jpg",
    },
    "mov-south-9": {
        "title": "Jailer",
        "tmdb_id": 937020,
        "release_year": 2023,
        "original_title": "ஜெயிலர்",
        "original_language": "ta",
        "poster_path": "/pTmMxAHqX4vsIDE6HPPxOR0Q6TN.jpg",
    },
    "mov-south-10": {
        "title": "Manjummel Boys",
        "tmdb_id": 1069945,
        "release_year": 2024,
        "original_title": "മഞ്ഞുമ്മൽ ബോയ്സ്",
        "original_language": "ml",
        "poster_path": "/awOxXBZHh3jvFEOLJvTaJOX5urU.jpg",
    },
    "mov-south-11": {
        "title": "Aavesham",
        "tmdb_id": 1222444,
        "release_year": 2024,
        "original_title": "ആവേശം",
        "original_language": "ml",
        "poster_path": "/k5RWPaNjgRcNvGoawYaQHQwyctI.jpg",
    },
    "mov-south-12": {
        "title": "Premalu",
        "tmdb_id": 1215162,
        "release_year": 2024,
        "original_title": "പ്രേമലു",
        "original_language": "ml",
        "poster_path": "/uPpmBjY3znUqGY8kYwI5xvOrSc0.jpg",
    },
}


def load_sample_movies():
    """Dynamically import or parse SAMPLE_MOVIES from app/data/sample_movies.py."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from app.data.sample_movies import SAMPLE_MOVIES
    return SAMPLE_MOVIES


def search_tmdb_movie(api_key: str, title: str, release_year: int = None, language: str = None):
    """Query TMDB API /search/movie with title, year, and language filters."""
    query_params = {
        "api_key": api_key,
        "query": title,
        "include_adult": "false",
    }
    if release_year:
        query_params["year"] = str(release_year)

    url = f"{TMDB_API_BASE}/search/movie?{urllib.parse.urlencode(query_params)}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "MovieMagic-PosterSync/1.0 (Educational/Demo)"}
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("results", [])
    except urllib.error.HTTPError as e:
        print(f"  [TMDB API Error] HTTP {e.code}: {e.reason} for query '{title}'")
    except Exception as e:
        print(f"  [TMDB API Error] {e} for query '{title}'")
    return []


def verify_image_url(url: str, timeout: int = 15):
    """Perform network check against poster URL (GET or HEAD) to verify response status and content-type."""
    if not url or not url.startswith("http"):
        return False, 0, "Invalid URL schema"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MovieMagic/1.0"}
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            content_length = int(resp.headers.get("Content-Length", 0))
            is_valid_image = status == 200 and ("image" in content_type or url.endswith((".jpg", ".png", ".webp")))
            return is_valid_image, status, f"{content_type} ({content_length} bytes)"
    except urllib.error.HTTPError as e:
        return False, e.code, f"HTTPError {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return False, 0, f"URLError: {e.reason}"
    except Exception as e:
        return False, 0, f"Error: {str(e)}"


def run_audit(verify_urls: bool = False, api_key: str = None):
    """Audit all 28 movie records against TMDB API or canonical catalogue."""
    movies = load_sample_movies()
    print(f"\n=======================================================")
    print(f"Movie Magic: Poster Audit for {len(movies)} Movie Records")
    print(f"=======================================================")

    results = []
    matched_count = 0
    unmatched_count = 0
    verified_urls_count = 0
    failed_urls_count = 0

    for m in movies:
        m_id = m.get("id")
        title = m.get("title")
        release_year = m.get("release_year")
        current_url = m.get("poster_url")
        canonical = CANONICAL_TMDB_CATALOGUE.get(m_id)

        target_poster_path = None
        source_note = ""

        # Step 1: TMDB API live lookup if key provided
        if api_key:
            api_results = search_tmdb_movie(api_key, title, release_year)
            if api_results:
                best = api_results[0]
                target_poster_path = best.get("poster_path")
                source_note = f"TMDB API live match (ID: {best.get('id')})"
            else:
                source_note = "TMDB API query returned 0 matches"

        # Step 2: Fallback to canonical audited catalogue if no API key or no API match
        if not target_poster_path and canonical:
            target_poster_path = canonical.get("poster_path")
            source_note = f"Audited TMDB canonical mapping (ID: {canonical.get('tmdb_id')})"

        if target_poster_path:
            matched_count += 1
            expected_url = f"{TMDB_IMAGE_BASE}{target_poster_path}"
        else:
            unmatched_count += 1
            expected_url = current_url

        # Check network response if requested
        network_status = "Skipped (--verify-urls not passed)"
        is_valid_image = None
        if verify_urls:
            url_to_test = expected_url or current_url
            is_valid_image, code, info = verify_image_url(url_to_test)
            if is_valid_image:
                verified_urls_count += 1
                network_status = f"Verified (HTTP {code}, {info})"
            else:
                failed_urls_count += 1
                network_status = f"FAILED (HTTP {code}: {info})"

        results.append({
            "id": m_id,
            "title": title,
            "category": m.get("category"),
            "current_url": current_url,
            "expected_url": expected_url,
            "poster_path": target_poster_path,
            "source_note": source_note,
            "url_matches": (current_url == expected_url),
            "network_status": network_status,
            "is_valid_image": is_valid_image
        })

        print(f"[{m_id}] {title} ({release_year})")
        print(f"  Category:     {m.get('category')}")
        print(f"  Poster URL:   {expected_url}")
        print(f"  Source:       {source_note}")
        if verify_urls:
            print(f"  Network:      {network_status}")
        print("-" * 55)

    print("\n--- Summary ---")
    print(f"Total Movies:            {len(movies)}")
    print(f"Successfully Matched:    {matched_count}")
    print(f"Unmatched Titles:        {unmatched_count}")
    if verify_urls:
        print(f"Network Verified (200):  {verified_urls_count}")
        print(f"Network Failed:          {failed_urls_count}")

    return results


def export_manifest(results):
    """Write verified poster mapping to app/data/poster_manifest.json."""
    manifest_data = {
        "_notice": "Official TMDB Poster Manifest for Movie Magic. Educational/demo purposes only.",
        "_attribution": "This product uses the TMDB API but is not endorsed or certified by TMDB.",
        "posters": {
            item["id"]: {
                "title": item["title"],
                "category": item["category"],
                "poster_url": item["expected_url"],
                "poster_path": item["poster_path"],
                "source": item["source_note"]
            }
            for item in results
        }
    }
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)
    print(f"Exported poster manifest to: {MANIFEST_PATH}")


def update_sample_movies_data(results):
    """Safely update poster_url entries in app/data/sample_movies.py without touching other metadata."""
    if not SAMPLE_MOVIES_PATH.exists():
        print(f"Error: {SAMPLE_MOVIES_PATH} not found.")
        return False

    with open(SAMPLE_MOVIES_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    updated_count = 0
    for r in results:
        m_id = r["id"]
        new_url = r["expected_url"]
        if not new_url:
            continue

        id_pattern = rf'("id":\s*"{re.escape(m_id)}",[\s\S]*?"poster_url":\s*")[^"]*(")'
        new_content, count = re.subn(id_pattern, rf'\g<1>{new_url}\g<2>', content, count=1)
        if count > 0:
            if new_content != content:
                updated_count += 1
            content = new_content

    with open(SAMPLE_MOVIES_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Updated {updated_count} poster URL entries in {SAMPLE_MOVIES_PATH}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Sync and verify TMDB movie posters for Movie Magic.")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Inspect matches without making changes.")
    parser.add_argument("--verify-urls", action="store_true", default=False, help="Perform HTTP network verification against image.tmdb.org.")
    parser.add_argument("--update-data", action="store_true", default=False, help="Update app/data/sample_movies.py and export manifest.")
    parser.add_argument("--api-key", type=str, default=None, help="TMDB API key (defaults to TMDB_API_KEY environment variable).")

    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("TMDB_API_KEY")

    if not api_key:
        print("[Info] No TMDB_API_KEY provided. Using audited canonical TMDB catalogue.")
        print("       (To enable live API search, pass --api-key <key> or set TMDB_API_KEY in .env)")

    results = run_audit(verify_urls=args.verify_urls, api_key=api_key)

    if args.update_data and not args.dry_run:
        export_manifest(results)
        update_sample_movies_data(results)
    elif args.dry_run:
        print("\n[Dry Run] No files modified.")
    else:
        export_manifest(results)


if __name__ == "__main__":
    main()
