"""Authentication Blueprint: Sign in, Register, Sign out."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from app.forms import LoginForm, RegisterForm
from app.services import auth_service

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Sign In handler with CSRF validation."""
    if session.get("user_id"):
        return redirect(url_for("main.index"))

    form = LoginForm()
    next_url = request.args.get("next") or request.form.get("next")

    if form.validate_on_submit():
        success, message, user = auth_service.authenticate(form.email.data, form.password.data)
        if success and user:
            session.clear()
            session["user_id"] = user["id"]
            session["user_email"] = user["email"]
            session["user_name"] = user["full_name"]
            session["user_role"] = user.get("role", "user")

            if form.remember_me.data:
                session.permanent = True

            flash(f"Welcome back, {user['full_name']}!", "success")
            if next_url and next_url.startswith("/"):
                return redirect(next_url)
            return redirect(url_for("main.index"))
        else:
            flash(message, "danger")

    return render_template(
        "auth/login.html",
        form=form,
        next=next_url,
        show_demo_credentials=current_app.config.get("SHOW_DEMO_CREDENTIALS", False),
    )


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """User Registration handler with CSRF validation and password strength checks."""
    if session.get("user_id"):
        return redirect(url_for("main.index"))

    form = RegisterForm()
    if form.validate_on_submit():
        success, message, user = auth_service.register(
            email=form.email.data,
            password=form.password.data,
            full_name=form.full_name.data,
        )
        if success:
            flash(message, "success")
            return redirect(url_for("auth.login"))
        else:
            flash(message, "danger")

    return render_template("auth/register.html", form=form)


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    """Sign Out handler clearing session data."""
    session.clear()
    flash("You have been signed out successfully.", "info")
    return redirect(url_for("main.index"))
