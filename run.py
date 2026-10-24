#!/usr/bin/env python3
"""Movie Magic — Application Entry Point.
Starts the Flask development server or provides the WSGI callable for production servers (Gunicorn).
"""
import os
from dotenv import load_dotenv
from app import create_app

# Load environment variables from .env file if present
load_dotenv()

app = create_app(os.environ.get("FLASK_ENV", "development"))

if __name__ == "__main__":
    host = os.environ.get("APP_HOST", "127.0.0.1")
    port = int(os.environ.get("APP_PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1").lower() in ("1", "true", "yes")

    print("=" * 65)
    print("🎬 Movie Magic — Cloud-Ready Movie Booking Application")
    print(f"📡 Server URL: http://{host}:{port}/")
    print(f"🩺 Health Check: http://{host}:{port}/health")
    print(f"🛠️  Environment: {os.environ.get('FLASK_ENV', 'development')}")
    print("=" * 65)

    app.run(host=host, port=port, debug=debug)
