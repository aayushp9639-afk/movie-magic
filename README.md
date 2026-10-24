# 🎬 Movie Magic

A modern, cloud-ready movie discovery and ticket reservation web application. Movie Magic allows moviegoers to browse a curated catalogue of films, check local theatre venue schedules, save titles to a personal watchlist, and simulate tiered seat reservations with instant confirmation.

---

## ✨ Key Features

- **Curated Movie Catalogue:** 28 titles spanning Anime, Marvel, and South Indian cinema with verified TMDB poster artwork, ratings, runtime, and crew metadata.
- **Multifaceted Search & Filtering:** Filter titles by category, language, and genre, combined with full-text search and sorting (by IMDb score, release year, runtime, and title).
- **Personal Watchlist:** Client-side bookmarking with persistent `localStorage` storage, live badge counter, empty-state guidance, and one-click print/PDF support.
- **Quick View & Rich Details:** Instant modal preview on hover/click, plus comprehensive detail pages featuring starring cast, director, and related film recommendations.
- **Venue Schedules & Seat Selection:** Verified Kolhapur cinema venues, scheduled showtimes, and an interactive tiered seat map (VIP, Gold, Silver) with booking collision prevention.
- **Dark & Light Mode:** Accessible cinematic dark theme with an instant light theme toggle persisted across browser sessions.
- **Authentication & Admin Portal:** User registration, password hashing (`pbkdf2:sha256`), session management, CSRF protection, and role-based administrative dashboard for catalogue and schedule management.
- **API & Health Probes:** Public `/api/movies` JSON discovery endpoint and `/health` readiness check for local verification and monitoring.

---

## 🛠️ Technologies Used

- **Language & Framework:** Python 3.11+, Flask 3.1
- **Forms & Security:** WTForms, Flask-WTF (CSRF protection), Werkzeug security
- **Cloud SDK:** AWS Boto3 (Amazon DynamoDB, Amazon SNS)
- **Frontend:** Bootstrap 5, Bootstrap Icons, Vanilla JavaScript, Custom CSS with CSS variables
- **Testing:** Pytest (167 automated unit and integration tests)
- **WSGI / Server:** Werkzeug dev server (`run.py`), Gunicorn support for Linux deployment

---

## 🚀 Local Setup and Run

### 1. Prerequisites
- Python 3.11+ installed
- Git installed

### 2. Clone and Setup Environment
```bash
git clone https://github.com/aayushp9639-afk/movie-magic.git
cd movie-magic

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run Application
```bash
python run.py
```
Open [http://127.0.0.1:5000/](http://127.0.0.1:5000/) in your browser.

- **Demo User Account:** `demo@moviemagic.com` / `Demo@123`
- **Admin Portal Account:** `admin@moviemagic.com` / `Admin@123`
- **Health Check Endpoint:** [http://127.0.0.1:5000/health](http://127.0.0.1:5000/health)
- **JSON API Endpoint:** [http://127.0.0.1:5000/api/movies](http://127.0.0.1:5000/api/movies)

### 4. Run Automated Tests
```bash
pytest -v
```

---

## ☁️ AWS Course Project Note

Movie Magic is architected as a cloud-native project with a dual-mode persistence layer:

- **Local Development / Mock Mode (`USE_AWS_MOCK=True`):** The application runs out of the box with zero external dependencies, using in-memory thread-safe mock repositories pre-seeded with real metadata and venues. No AWS account or API credentials are required to evaluate the application.
- **AWS Cloud Production Mode (`USE_AWS_MOCK=False`):** Built to connect seamlessly with **Amazon DynamoDB** in `ap-south-1` (Mumbai) across 6 tables using Global Secondary Indexes (`CategoryIndex`, `CityStatusIndex`, `MovieShowtimeIndex`, `TheaterShowtimeIndex`, `UserBookingsIndex`) and atomic double-booking protection (`TransactWriteItems`), alongside **Amazon SNS** for asynchronous booking confirmation notifications. Infrastructure setup scripts and IAM policies are located in `scripts/` and `deploy/`.
