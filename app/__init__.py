"""Application factory module for Movie Magic."""
import os
from flask import Flask, render_template, session
from flask_wtf.csrf import CSRFProtect
from app.config import config_by_name

csrf = CSRFProtect()


def create_app(config_name: str = None) -> Flask:
    """Create and configure the Flask application instance."""
    if not config_name:
        config_name = os.environ.get("FLASK_ENV", "development").lower()

    app = Flask(__name__)
    config_class = config_by_name.get(config_name, config_by_name["default"])
    app.config.from_object(config_class)

    # Runtime environment override for demo credentials helper
    if "SHOW_DEMO_CREDENTIALS" in os.environ:
        app.config["SHOW_DEMO_CREDENTIALS"] = os.environ["SHOW_DEMO_CREDENTIALS"].lower() in ("true", "1", "yes")

    # Initialize extensions
    csrf.init_app(app)

    # Register blueprints
    from app.routes import main_bp, auth_bp, booking_bp, admin_bp
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(booking_bp)
    app.register_blueprint(admin_bp)

    # Global context processors for Jinja templates
    @app.context_processor
    def inject_global_template_vars():
        try:
            user_id = session.get("user_id")
            user_email = session.get("user_email")
            user_name = session.get("user_name")
            user_role = session.get("user_role")
        except RuntimeError:
            user_id = None
            user_email = None
            user_name = None
            user_role = None

        return {
            "app_name": app.config.get("APP_NAME", "Movie Magic"),
            "current_user_id": user_id,
            "current_user_email": user_email,
            "current_user_name": user_name,
            "current_user_role": user_role,
            "is_admin": user_role == "admin",
            "is_demo_mode": app.config.get("USE_AWS_MOCK", True),
            "show_demo_credentials": app.config.get("SHOW_DEMO_CREDENTIALS", False),
        }

    # Custom Error Handlers
    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(error):
        return render_template("errors/500.html"), 500

    return app
