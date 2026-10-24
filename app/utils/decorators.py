"""Route protection decorators for authentication and authorization."""
from functools import wraps
from flask import session, flash, redirect, url_for, request, abort


def login_required(f):
    """Decorator to restrict access to authenticated users only."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in to access this page.", "warning")
            return redirect(url_for("auth.login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    """Decorator to restrict access to administrators only.
    Non-admin users will receive a 403 Forbidden response or redirect.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please sign in with administrator credentials.", "warning")
            return redirect(url_for("auth.login", next=request.url))
        if session.get("user_role") != "admin":
            flash("Access denied: Administrator privileges required.", "danger")
            abort(403)
        return f(*args, **kwargs)
    return decorated_function
