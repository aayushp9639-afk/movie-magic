"""Web forms using Flask-WTF and WTForms for validation and CSRF protection."""
from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    PasswordField,
    BooleanField,
    SubmitField,
    TextAreaField,
    FloatField,
    IntegerField,
    SelectField,
    HiddenField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    Length,
    EqualTo,
    NumberRange,
    Optional as OptionalValidator,
)
from app.data.sample_movies import (
    SAMPLE_GENRES,
    SAMPLE_CATEGORIES,
    SAMPLE_LANGUAGES,
    SAMPLE_CITIES,
)


class LoginForm(FlaskForm):
    """User Sign In Form."""
    email = StringField(
        "Email Address",
        validators=[DataRequired(message="Please enter your email."), Email(message="Invalid email address.")],
        render_kw={"placeholder": "you@example.com", "autocomplete": "email"},
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(message="Please enter your password.")],
        render_kw={"placeholder": "••••••••", "autocomplete": "current-password"},
    )
    remember_me = BooleanField("Remember me for 30 days")
    submit = SubmitField("Sign In")


class RegisterForm(FlaskForm):
    """User Registration Form."""
    full_name = StringField(
        "Full Name",
        validators=[
            DataRequired(message="Full name is required."),
            Length(min=2, max=80, message="Name must be between 2 and 80 characters."),
        ],
        render_kw={"placeholder": "Alex Morgan", "autocomplete": "name"},
    )
    email = StringField(
        "Email Address",
        validators=[
            DataRequired(message="Email address is required."),
            Email(message="Invalid email address."),
        ],
        render_kw={"placeholder": "you@example.com", "autocomplete": "email"},
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(message="Password is required."),
            Length(min=8, message="Password must be at least 8 characters long."),
        ],
        render_kw={"placeholder": "At least 8 characters, letters & digits", "autocomplete": "new-password"},
    )
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[
            DataRequired(message="Please confirm your password."),
            EqualTo("password", message="Passwords must match."),
        ],
        render_kw={"placeholder": "Re-enter your password", "autocomplete": "new-password"},
    )
    submit = SubmitField("Create Account")


class BookingSubmissionForm(FlaskForm):
    """Form for processing seat booking with CSRF protection."""
    movie_id = HiddenField("Movie ID", validators=[DataRequired()])
    theater_id = HiddenField("Theater ID", validators=[DataRequired()])
    showtime = HiddenField("Showtime", validators=[DataRequired()])
    show_date = HiddenField("Show Date", validators=[DataRequired()])
    selected_seats = HiddenField("Selected Seats", validators=[DataRequired(message="Please select at least one seat.")])
    submit = SubmitField("Confirm Booking")


class MovieForm(FlaskForm):
    """Admin form to add or edit a movie in the catalogue."""
    title = StringField("Movie Title", validators=[DataRequired(), Length(max=150)])
    original_title = StringField("Original Title (Native Script)", validators=[OptionalValidator(), Length(max=150)])
    category = SelectField(
        "Category",
        choices=[(c, c) for c in SAMPLE_CATEGORIES if c != "All"],
        validators=[DataRequired()],
    )
    language = SelectField(
        "Original Language",
        choices=[(l, l) for l in SAMPLE_LANGUAGES if l != "All"],
        validators=[DataRequired()],
    )
    genre = SelectField("Primary Genre", choices=[(g, g) for g in SAMPLE_GENRES if g != "All"], validators=[DataRequired()])
    duration = StringField("Duration (e.g. 2h 15m)", validators=[DataRequired(), Length(max=30)])
    rating = SelectField("Content Rating", choices=[("U", "U"), ("U/A", "U/A"), ("A", "A"), ("PG", "PG"), ("PG-13", "PG-13"), ("R", "R")])
    imdb_score = FloatField("IMDb / Verified Rating", validators=[DataRequired(), NumberRange(min=1.0, max=10.0)])
    release_year = IntegerField("Release Year", validators=[DataRequired(), NumberRange(min=1900, max=2100)])
    director = StringField("Director", validators=[DataRequired(), Length(max=100)])
    poster_url = StringField("Poster Image URL (TMDB / Official)", validators=[OptionalValidator(), Length(max=500)])
    synopsis = TextAreaField("Synopsis", validators=[DataRequired(), Length(max=1500)])
    badge = StringField("Badge Tag (e.g. Blockbuster, Masterpiece)", validators=[OptionalValidator(), Length(max=40)])
    submit = SubmitField("Save Movie Record")


# Backward compatibility alias
AddMovieForm = MovieForm


class TheaterForm(FlaskForm):
    """Admin form to add or update cinema venues."""
    name = StringField("Theatre Name", validators=[DataRequired(), Length(max=120)])
    address = StringField("Street Address & Landmark", validators=[DataRequired(), Length(max=250)])
    city = SelectField("City", choices=[(c, c) for c in SAMPLE_CITIES], validators=[DataRequired()])
    state = StringField("State", default="Maharashtra", validators=[DataRequired(), Length(max=60)])
    postal_code = StringField("Postal PIN Code", validators=[OptionalValidator(), Length(max=10)])
    operational_status = SelectField(
        "Operational Status",
        choices=[
            ("Operational", "Operational (Active for Showtimes)"),
            ("Unverified", "Unverified (Online Booking Disabled)"),
            ("Temporarily Closed", "Temporarily Closed"),
        ],
        validators=[DataRequired()],
    )
    is_verified = BooleanField("Verified Venue (Source-Confirmed)")
    source_url = StringField("Public Source / Listing URL", validators=[OptionalValidator(), Length(max=500)])
    screens_list = StringField("Screen Names (comma-separated)", validators=[OptionalValidator(), Length(max=200)])
    venue_type = StringField("Venue Classification (e.g. Multiplex, Single Screen)", validators=[OptionalValidator(), Length(max=60)])
    submit = SubmitField("Save Theatre Record")


class ShowtimeForm(FlaskForm):
    """Admin form to schedule showtimes."""
    movie_id = SelectField("Movie", validators=[DataRequired()])
    theater_id = SelectField("Theatre Venue", validators=[DataRequired()])
    date = StringField("Date / Day (e.g. Today, Tomorrow, YYYY-MM-DD)", default="Today", validators=[DataRequired()])
    time = StringField("Showtime (e.g. 10:30 AM, 06:15 PM)", validators=[DataRequired()])
    language_version = StringField("Audio / Subtitle Version (e.g. Telugu (Eng Sub), Hindi)", validators=[DataRequired()])
    format = SelectField("Projection Format", choices=[("2D", "2D"), ("3D", "3D"), ("IMAX 2D", "IMAX 2D"), ("IMAX 3D", "IMAX 3D"), ("4DX", "4DX")])
    screen = StringField("Auditorium / Screen Name", default="Audi 1", validators=[DataRequired()])
    price = FloatField("Base Ticket Price (₹ INR)", default=200.00, validators=[DataRequired(), NumberRange(min=50.0, max=2000.0)])
    is_verified = BooleanField("Mark as Verified Schedule (Leave unchecked for Demo / Sample)")
    submit = SubmitField("Schedule Showtime")
