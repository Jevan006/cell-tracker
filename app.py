import csv
import io
import json
import os
import click
from datetime import datetime, timedelta, date

from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import inspect, text
from werkzeug.security import check_password_hash, generate_password_hash

# Load environment variables
load_dotenv()

app = Flask(__name__, instance_relative_config=True)
os.makedirs(app.instance_path, exist_ok=True)

# Database configuration
_default_sqlite_path = os.path.join(app.instance_path, "cell_tracker.db")
_default_sqlite_uri = "sqlite:///" + _default_sqlite_path.replace("\\", "/")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", _default_sqlite_uri
)
if app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgres://"):
    app.config["SQLALCHEMY_DATABASE_URI"] = app.config[
        "SQLALCHEMY_DATABASE_URI"
    ].replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get(
    "SESSION_SECRET", "dev-secret-key-change-in-production"
)

# File upload configuration
app.config["UPLOAD_FOLDER"] = "static/uploads/profile_pictures"
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2MB max file size
app.config["ALLOWED_EXTENSIONS"] = {"png", "jpg", "jpeg", "gif"}
app.config["STATIC_UPLOAD_FOLDER"] = "uploads/profile_pictures"

# Ensure upload folder exists
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)
migrate = Migrate(app, db)


# File upload helper functions
def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]
    )


def save_profile_picture(file, leader_id):
    """Save profile picture and return the filename"""
    if file and allowed_file(file.filename):
        # Create a secure filename: leader_{id}_timestamp.ext
        timestamp = int(datetime.now().timestamp())
        ext = file.filename.rsplit(".", 1)[1].lower()
        filename = f"leader_{leader_id}_{timestamp}.{ext}"

        # Save file
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        return filename
    return None


def delete_profile_picture(filename):
    """Delete a profile picture file"""
    if filename:
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        if os.path.exists(filepath):
            os.remove(filepath)


# Database Models with profile pictures
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="user", nullable=False)
    leader_id = db.Column(db.Integer, db.ForeignKey("leader.id"))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Branch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    zones = db.relationship("Zone", backref="branch", lazy=True)
    leaders = db.relationship("Leader", backref="branch", lazy=True)


class Zone(db.Model):
    __table_args__ = (
        db.UniqueConstraint("branch_id", "name", name="uq_zone_branch_name"),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    leaders = db.relationship("Leader", backref="zone_ref", lazy=True)


class Leader(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    zone = db.Column(db.String(50), nullable=False)
    zone_id = db.Column(db.Integer, db.ForeignKey("zone.id"))
    branch_id = db.Column(db.Integer, db.ForeignKey("branch.id"))
    cell_day = db.Column(db.String(20), default="Thursday")
    contact_number = db.Column(db.String(20))
    email = db.Column(db.String(100))
    address = db.Column(db.Text)
    profile_picture = db.Column(db.String(255))  # Store filename or URL
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    service_records = db.relationship("ServiceRecord", backref="leader", lazy=True)
    users = db.relationship("User", backref="leader", lazy=True)

    def __init__(
        self,
        name,
        zone,
        cell_day="Thursday",
        contact_number="",
        email="",
        address="",
        profile_picture=None,
        is_active=True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = name
        self.zone = zone
        self.cell_day = cell_day
        self.contact_number = contact_number
        self.email = email
        self.address = address
        self.profile_picture = profile_picture
        self.is_active = is_active

    def get_profile_picture_url(self):
        """Get the profile picture URL or return default"""
        if self.profile_picture:
            return f"/static/uploads/profile_pictures/{self.profile_picture}"
        return None

    def get_initials(self):
        """Get initials for avatar fallback"""
        return "".join(word[0].upper() for word in self.name.split()[:2])


class ServiceRecord(db.Model):
    __table_args__ = (
        db.UniqueConstraint(
            "leader_id",
            "service_type",
            "service_date",
            name="uq_service_record_leader_type_date",
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    leader_id = db.Column(db.Integer, db.ForeignKey("leader.id"), nullable=False)
    service_type = db.Column(db.String(20), nullable=False)
    service_date = db.Column(db.Date, nullable=False)
    is_cancelled = db.Column(db.Boolean, default=False)
    cancel_reason = db.Column(db.Text)

    sunday_attendance = db.Column(db.Integer, default=0)
    sunday_visitors = db.Column(db.Integer, default=0)

    cell_attendance = db.Column(db.Integer, default=0)
    cell_visitors = db.Column(db.Integer, default=0)
    cell_offering = db.Column(db.Float, default=0.0)
    cell_decisions = db.Column(db.Integer, default=0)

    notes = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(
        self,
        leader_id,
        service_type,
        service_date,
        sunday_attendance=0,
        sunday_visitors=0,
        cell_attendance=0,
        cell_visitors=0,
        cell_offering=0.0,
        cell_decisions=0,
        notes="",
        is_cancelled=False,
        cancel_reason=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.leader_id = leader_id
        self.service_type = service_type
        self.service_date = service_date
        self.is_cancelled = is_cancelled
        self.cancel_reason = cancel_reason
        self.sunday_attendance = sunday_attendance
        self.sunday_visitors = sunday_visitors
        self.cell_attendance = cell_attendance
        self.cell_visitors = cell_visitors
        self.cell_offering = cell_offering
        self.cell_decisions = cell_decisions
        self.notes = notes



# Authentication helper functions
def login_required(f):
    """Decorator to protect routes that require authentication"""
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """Decorator to protect routes that require admin role"""
    from functools import wraps

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.url))
        if session.get("role") != "admin":
            return jsonify({"success": False, "message": "Admin access required"}), 403
        return f(*args, **kwargs)

    return decorated_function


def is_authenticated():
    """Check if user is logged in"""
    return session.get("logged_in", False)


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return User.query.get(user_id)


def _parse_list_param(args, primary_key, fallback_key=None):
    values = []
    if primary_key in args:
        values = args.getlist(primary_key)
    elif fallback_key and fallback_key in args:
        values = args.getlist(fallback_key)

    if not values:
        return []

    split_values = []
    for val in values:
        if val is None:
            continue
        for chunk in str(val).split(","):
            chunk = chunk.strip()
            if chunk:
                split_values.append(chunk)
    return split_values


def _coerce_int_list(values):
    ints = []
    for val in values:
        try:
            ints.append(int(val))
        except (TypeError, ValueError):
            continue
    return ints


def _ensure_default_branch_data():
    if Branch.query.first():
        return
    default_branch = Branch(name="Main Branch", is_active=True)
    db.session.add(default_branch)
    db.session.flush()

    zones = []
    for zone_name in sorted(set(SA_ZONES)):
        zones.append(
            Zone(name=zone_name, branch_id=default_branch.id, is_active=True)
        )
    db.session.add_all(zones)
    db.session.flush()

    zone_by_name = {z.name: z for z in zones}
    for leader in Leader.query.all():
        if leader.zone in zone_by_name:
            leader.zone_id = zone_by_name[leader.zone].id
            leader.branch_id = default_branch.id

    db.session.commit()


# Sample South African zones
# Zones for your church
SA_ZONES = ["Chestnut", "KB South", "KB North"]

CELL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


# Public routes (no authentication required)
@app.route("/")
def home():
    return render_template("index.html", datetime=datetime)


@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


# Authentication routes
@app.route("/login", methods=["GET", "POST"])
def login():
    # If already logged in, redirect to intended page or home
    if is_authenticated():
        next_page = request.args.get("next", url_for("home"))
        return redirect(next_page)

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(username=username, is_active=True).first()
        if user and user.check_password(password):
            session["logged_in"] = True
            session["login_time"] = datetime.utcnow().isoformat()
            session["user_id"] = user.id
            session["role"] = user.role

            next_page = request.args.get("next", url_for("enter_totals"))
            return redirect(next_page)
        else:
            return render_template("login.html", error="Invalid username or password")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# Protected routes (require authentication)
@app.route("/enter-totals")
@login_required
def enter_totals():
    return render_template("enter_totals.html")


@app.route("/leaders-management")
@admin_required
def leaders_management():
    return render_template("leaders_management.html")


@app.route("/branches-zones")
@admin_required
def branches_zones():
    return render_template("branches_zones.html")


# API Routes


# Public API endpoints (no authentication required)
@app.route("/api/search-leaders")
def search_leaders():
    query = request.args.get("q", "").lower()
    zone_filter = request.args.get("zone", "")
    branch_filter = request.args.get("branch_id")
    current_user = get_current_user()

    if query:
        leaders_query = Leader.query.filter(
            (Leader.name.ilike(f"%{query}%")) | (Leader.zone.ilike(f"%{query}%"))
        ).filter_by(is_active=True)
    else:
        leaders_query = Leader.query.filter_by(is_active=True)

    if zone_filter:
        leaders_query = leaders_query.filter(Leader.zone == zone_filter)
    if branch_filter:
        leaders_query = leaders_query.filter(Leader.branch_id == branch_filter)

    if current_user and current_user.role != "admin":
        leaders_query = leaders_query.filter(Leader.id == current_user.leader_id)

    leaders = leaders_query.limit(10 if query else 5).all()

    leaders_data = [
        {
            "id": leader.id,
            "name": leader.name,
            "zone": leader.zone_ref.name if leader.zone_ref else leader.zone,
            "zone_id": leader.zone_id,
            "zone_name": leader.zone_ref.name if leader.zone_ref else leader.zone,
            "branch_id": leader.branch_id,
            "branch_name": leader.branch.name if leader.branch else None,
            "cell_day": leader.cell_day,
            "contact_number": leader.contact_number,
            "email": leader.email,
            "profile_picture": leader.profile_picture,
            "profile_picture_url": leader.get_profile_picture_url(),
            "initials": leader.get_initials(),
        }
        for leader in leaders
    ]

    return jsonify(leaders_data)


@app.route("/api/analytics/overview")
def analytics_overview():
    period = request.args.get("period", "week")
    zone_filters = _parse_list_param(request.args, "zones", "zone")
    leader_ids = _coerce_int_list(
        _parse_list_param(request.args, "leader_ids", "leader_id")
    )
    service_type_filter = request.args.get("service_type", "combined")

    # Calculate date range
    end_date = datetime.now().date()
    if period == "week":
        start_date = end_date - timedelta(days=7)
    elif period == "month":
        start_date = end_date - timedelta(days=30)
    else:  # year
        start_date = end_date - timedelta(days=365)

    # Build query
    query = (
        ServiceRecord.query.join(Leader)
        .filter(
            ServiceRecord.service_date >= start_date,
            ServiceRecord.service_date <= end_date,
        )
        .filter(ServiceRecord.is_cancelled == False)
    )

    if zone_filters:
        query = query.filter(Leader.zone.in_(zone_filters))

    if service_type_filter in ("sunday", "cell"):
        query = query.filter(ServiceRecord.service_type == service_type_filter)

    if leader_ids:
        query = query.filter(ServiceRecord.leader_id.in_(leader_ids))

    records = query.all()

    # Calculate statistics
    total_attendance = sum(
        r.sunday_attendance if r.service_type == "sunday" else r.cell_attendance
        for r in records
    )
    total_visitors = sum(
        r.sunday_visitors if r.service_type == "sunday" else r.cell_visitors
        for r in records
    )
    total_offering = sum(r.cell_offering for r in records if r.service_type == "cell")
    total_decisions = sum(r.cell_decisions for r in records if r.service_type == "cell")

    # Service type breakdown
    sunday_services = len([r for r in records if r.service_type == "sunday"])
    cell_meetings = len([r for r in records if r.service_type == "cell"])

    # Zone statistics
    zone_stats = {}
    for record in records:
        zone = record.leader.zone
        if zone not in zone_stats:
            zone_stats[zone] = {
                "attendance": 0,
                "visitors": 0,
                "offering": 0,
                "decisions": 0,
                "services": 0,
            }

        zone_stats[zone]["attendance"] += (
            record.sunday_attendance
            if record.service_type == "sunday"
            else record.cell_attendance
        )
        zone_stats[zone]["visitors"] += (
            record.sunday_visitors
            if record.service_type == "sunday"
            else record.cell_visitors
        )
        zone_stats[zone]["offering"] += (
            record.cell_offering if record.service_type == "cell" else 0
        )
        zone_stats[zone]["decisions"] += (
            record.cell_decisions if record.service_type == "cell" else 0
        )
        zone_stats[zone]["services"] += 1

    # Leader statistics
    leader_stats = {}
    for record in records:
        leader_name = record.leader.name
        if leader_name not in leader_stats:
            leader_stats[leader_name] = {
                "attendance": 0,
                "visitors": 0,
                "offering": 0,
                "decisions": 0,
                "services": 0,
                "zone": record.leader.zone,
            }

        leader_stats[leader_name]["attendance"] += (
            record.sunday_attendance
            if record.service_type == "sunday"
            else record.cell_attendance
        )
        leader_stats[leader_name]["visitors"] += (
            record.sunday_visitors
            if record.service_type == "sunday"
            else record.cell_visitors
        )
        leader_stats[leader_name]["offering"] += (
            record.cell_offering if record.service_type == "cell" else 0
        )
        leader_stats[leader_name]["decisions"] += (
            record.cell_decisions if record.service_type == "cell" else 0
        )
        leader_stats[leader_name]["services"] += 1

    return jsonify(
        {
            "period": period,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "total_attendance": total_attendance,
            "total_visitors": total_visitors,
            "total_offering": total_offering,
            "total_decisions": total_decisions,
            "sunday_services": sunday_services,
            "cell_meetings": cell_meetings,
            "zone_stats": zone_stats,
            "leader_stats": leader_stats,
            "total_records": len(records),
        }
    )


@app.route("/api/analytics/trends")
def analytics_trends():
    period = request.args.get("period", "week")
    zone_filters = _parse_list_param(request.args, "zones", "zone")
    leader_ids = _coerce_int_list(
        _parse_list_param(request.args, "leader_ids", "leader_id")
    )
    service_type_filter = request.args.get("service_type", "combined")

    # Calculate date range and group by
    end_date = datetime.now().date()
    if period == "week":
        start_date = end_date - timedelta(days=7)
        group_format = "%Y-%m-%d"  # Daily
    elif period == "month":
        start_date = end_date - timedelta(days=30)
        group_format = "%Y-%m-%d"  # Daily
    else:  # year
        start_date = end_date - timedelta(days=365)
        group_format = "%Y-%m"  # Monthly

    # This would be more efficient with raw SQL, but for simplicity:
    query = (
        ServiceRecord.query.join(Leader)
        .filter(
            ServiceRecord.service_date >= start_date,
            ServiceRecord.service_date <= end_date,
        )
        .filter(ServiceRecord.is_cancelled == False)
    )

    if zone_filters:
        query = query.filter(Leader.zone.in_(zone_filters))

    if service_type_filter in ("sunday", "cell"):
        query = query.filter(ServiceRecord.service_type == service_type_filter)

    if leader_ids:
        query = query.filter(ServiceRecord.leader_id.in_(leader_ids))
    records = query.all()

    # Group by date
    trends = {}
    for record in records:
        if period == "year":
            date_key = record.service_date.strftime("%Y-%m")
        else:
            date_key = record.service_date.strftime("%Y-%m-%d")

        if date_key not in trends:
            trends[date_key] = {
                "attendance": 0,
                "visitors": 0,
                "offering": 0,
                "decisions": 0,
                "services": 0,
            }

        trends[date_key]["attendance"] += (
            record.sunday_attendance
            if record.service_type == "sunday"
            else record.cell_attendance
        )
        trends[date_key]["visitors"] += (
            record.sunday_visitors
            if record.service_type == "sunday"
            else record.cell_visitors
        )
        trends[date_key]["offering"] += (
            record.cell_offering if record.service_type == "cell" else 0
        )
        trends[date_key]["decisions"] += (
            record.cell_decisions if record.service_type == "cell" else 0
        )
        trends[date_key]["services"] += 1

    # Convert to sorted list
    trends_list = [{"date": date, **data} for date, data in sorted(trends.items())]

    return jsonify(trends_list)


# Profile Picture API endpoints
@app.route("/api/leader/<int:leader_id>/upload-picture", methods=["POST"])
@login_required
def upload_leader_picture(leader_id):
    """Upload a profile picture for a leader"""
    try:
        leader = Leader.query.get_or_404(leader_id)

        if "profile_picture" not in request.files:
            return jsonify({"success": False, "message": "No file provided"}), 400

        file = request.files["profile_picture"]

        if file.filename == "":
            return jsonify({"success": False, "message": "No file selected"}), 400

        # Check file size
        if len(file.read()) > app.config["MAX_CONTENT_LENGTH"]:
            return jsonify(
                {"success": False, "message": "File too large. Maximum 2MB allowed."}
            ), 400

        file.seek(0)  # Reset file pointer

        # Delete old picture if exists
        if leader.profile_picture:
            delete_profile_picture(leader.profile_picture)

        # Save new picture
        filename = save_profile_picture(file, leader_id)

        if filename:
            leader.profile_picture = filename
            leader.updated_at = datetime.utcnow()
            db.session.commit()

            return jsonify(
                {
                    "success": True,
                    "message": "Profile picture uploaded successfully!",
                    "filename": filename,
                    "profile_picture_url": f"/static/uploads/profile_pictures/{filename}",
                }
            )
        else:
            return jsonify(
                {
                    "success": False,
                    "message": "Invalid file type. Allowed: PNG, JPG, JPEG, GIF",
                }
            ), 400

    except Exception as e:
        db.session.rollback()
        return jsonify(
            {"success": False, "message": f"Error uploading picture: {str(e)}"}
        ), 500


@app.route("/api/leader/<int:leader_id>/remove-picture", methods=["POST"])
@login_required
def remove_leader_picture(leader_id):
    """Remove a leader's profile picture"""
    try:
        leader = Leader.query.get_or_404(leader_id)

        if leader.profile_picture:
            delete_profile_picture(leader.profile_picture)
            leader.profile_picture = None
            leader.updated_at = datetime.utcnow()
            db.session.commit()

        return jsonify(
            {"success": True, "message": "Profile picture removed successfully!"}
        )

    except Exception as e:
        db.session.rollback()
        return jsonify(
            {"success": False, "message": f"Error removing picture: {str(e)}"}
        ), 500


# Backup & Restore API endpoints
@app.route("/api/backup-data")
@login_required
def backup_data():
    """Create a JSON backup of all data"""
    try:
        # Backup leaders
        leaders = Leader.query.all()
        leaders_data = [
            {
                "id": leader.id,
                "name": leader.name,
                "zone": leader.zone,
                "cell_day": leader.cell_day,
                "contact_number": leader.contact_number,
                "email": leader.email,
                "address": leader.address,
                "profile_picture": leader.profile_picture,
                "is_active": leader.is_active,
                "created_at": leader.created_at.isoformat()
                if leader.created_at
                else None,
                "updated_at": leader.updated_at.isoformat()
                if leader.updated_at
                else None,
            }
            for leader in leaders
        ]

        # Backup service records
        service_records = ServiceRecord.query.all()
        records_data = [
            {
                "id": record.id,
                "leader_id": record.leader_id,
                "service_type": record.service_type,
                "service_date": record.service_date.isoformat(),
                "sunday_attendance": record.sunday_attendance,
                "sunday_visitors": record.sunday_visitors,
                "cell_attendance": record.cell_attendance,
                "cell_visitors": record.cell_visitors,
                "cell_offering": record.cell_offering,
                "cell_decisions": record.cell_decisions,
                "notes": record.notes,
                "submitted_at": record.submitted_at.isoformat()
                if record.submitted_at
                else None,
            }
            for record in service_records
        ]

        backup = {
            "timestamp": datetime.utcnow().isoformat(),
            "leaders": leaders_data,
            "service_records": records_data,
        }

        return Response(
            json.dumps(backup, indent=2),
            mimetype="application/json",
            headers={"Content-Disposition": "attachment; filename=church_backup.json"},
        )

    except Exception as e:
        return jsonify({"success": False, "message": f"Backup failed: {str(e)}"}), 500


@app.route("/api/restore-data", methods=["POST"])
@login_required
def restore_data():
    """Restore data from JSON backup"""
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "message": "No file provided"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"success": False, "message": "No file selected"}), 400

        if file and file.filename.endswith(".json"):
            data = json.load(file)

            # Clear existing data
            db.session.query(ServiceRecord).delete()
            db.session.query(Leader).delete()

            # Restore leaders
            for leader_data in data.get("leaders", []):
                leader = Leader(
                    name=leader_data["name"],
                    zone=leader_data["zone"],
                    cell_day=leader_data.get("cell_day", "Thursday"),
                    contact_number=leader_data.get("contact_number", ""),
                    email=leader_data.get("email", ""),
                    address=leader_data.get("address", ""),
                    profile_picture=leader_data.get("profile_picture"),
                    is_active=leader_data.get("is_active", True),
                )
                # Set ID directly for restoration
                leader.id = leader_data["id"]
                if leader_data.get("created_at"):
                    leader.created_at = datetime.fromisoformat(
                        leader_data["created_at"]
                    )
                if leader_data.get("updated_at"):
                    leader.updated_at = datetime.fromisoformat(
                        leader_data["updated_at"]
                    )
                db.session.add(leader)

            # Restore service records
            for record_data in data.get("service_records", []):
                record = ServiceRecord(
                    leader_id=record_data["leader_id"],
                    service_type=record_data["service_type"],
                    service_date=datetime.strptime(
                        record_data["service_date"], "%Y-%m-%d"
                    ).date(),
                    sunday_attendance=record_data.get("sunday_attendance", 0),
                    sunday_visitors=record_data.get("sunday_visitors", 0),
                    cell_attendance=record_data.get("cell_attendance", 0),
                    cell_visitors=record_data.get("cell_visitors", 0),
                    cell_offering=record_data.get("cell_offering", 0.0),
                    cell_decisions=record_data.get("cell_decisions", 0),
                    notes=record_data.get("notes", ""),
                )
                # Set ID and submitted_at directly for restoration
                record.id = record_data["id"]
                if record_data.get("submitted_at"):
                    record.submitted_at = datetime.fromisoformat(
                        record_data["submitted_at"]
                    )
                db.session.add(record)

            db.session.commit()
            return jsonify({"success": True, "message": "Data restored successfully!"})

        return jsonify({"success": False, "message": "Invalid file format"}), 400

    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"Restore failed: {str(e)}"}), 500


# Protected API endpoints (require authentication)
@app.route("/api/submit-totals", methods=["POST"])
@login_required
def submit_totals():
    try:
        current_user = get_current_user()
        data = request.json

        leader_id = data["leader_id"]
        service_type = data["service_type"]
        service_date_str = data.get("service_date")
        if not service_date_str:
            return jsonify({"success": False, "message": "Service date is required"}), 400
        service_date = datetime.strptime(service_date_str, "%Y-%m-%d").date()
        if service_date > date.today():
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Service date cannot be in the future",
                    }
                ),
                400,
            )
        is_cancelled = bool(data.get("is_cancelled", False))
        cancel_reason = data.get("cancel_reason")
        if is_cancelled and not cancel_reason:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Reason for cancellation is required",
                    }
                ),
                400,
            )

        if current_user and current_user.role != "admin":
            if current_user.leader_id != leader_id:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "You can only submit totals for your own leader",
                        }
                    ),
                    403,
                )

        record = ServiceRecord.query.filter_by(
            leader_id=leader_id,
            service_type=service_type,
            service_date=service_date,
        ).first()

        if record is None:
            record = ServiceRecord(
                leader_id=leader_id,
                service_type=service_type,
                service_date=service_date,
                notes=data.get("notes", ""),
            )
            db.session.add(record)
        else:
            record.notes = data.get("notes", record.notes)
            record.submitted_at = datetime.utcnow()

        record.is_cancelled = is_cancelled
        record.cancel_reason = cancel_reason if is_cancelled else None

        if is_cancelled:
            record.sunday_attendance = 0
            record.sunday_visitors = 0
            record.cell_attendance = 0
            record.cell_visitors = 0
            record.cell_offering = 0.0
            record.cell_decisions = 0
        elif data["service_type"] == "sunday":
            record.sunday_attendance = data["sunday_attendance"]
            record.sunday_visitors = data.get("sunday_visitors", 0)
            record.cell_attendance = 0
            record.cell_visitors = 0
            record.cell_offering = 0.0
            record.cell_decisions = 0
        else:
            record.cell_attendance = data["cell_attendance"]
            record.cell_visitors = data.get("cell_visitors", 0)
            record.cell_offering = data.get("cell_offering", 0.0)
            record.cell_decisions = data.get("cell_decisions", 0)
            record.sunday_attendance = 0
            record.sunday_visitors = 0

        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": "Totals submitted successfully!",
                "record_id": record.id,
            }
        )

    except Exception as e:
        db.session.rollback()
        return jsonify(
            {"success": False, "message": f"Error submitting totals: {str(e)}"}
        ), 400


@app.route("/api/leaders")
@login_required
def get_leaders():
    zone_filters = _parse_list_param(request.args, "zones", "zone")
    branch_filter = request.args.get("branch_id")
    active_only = request.args.get("active_only", "true") == "true"

    query = Leader.query

    if zone_filters:
        query = query.filter(Leader.zone.in_(zone_filters))
    if branch_filter:
        query = query.filter(Leader.branch_id == branch_filter)

    current_user = get_current_user()
    if current_user and current_user.role != "admin":
        query = query.filter(Leader.id == current_user.leader_id)

    if active_only:
        query = query.filter(Leader.is_active == True)

    leaders = query.order_by(Leader.name).all()

    leaders_data = [
        {
            "id": leader.id,
            "name": leader.name,
            "zone": leader.zone_ref.name if leader.zone_ref else leader.zone,
            "zone_id": leader.zone_id,
            "zone_name": leader.zone_ref.name if leader.zone_ref else leader.zone,
            "branch_id": leader.branch_id,
            "branch_name": leader.branch.name if leader.branch else None,
            "cell_day": leader.cell_day,
            "contact_number": leader.contact_number,
            "email": leader.email,
            "address": leader.address,
            "profile_picture": leader.profile_picture,
            "profile_picture_url": leader.get_profile_picture_url(),
            "initials": leader.get_initials(),
            "is_active": leader.is_active,
            "total_submissions": len(leader.service_records),
            "last_submission": max(
                [r.submitted_at for r in leader.service_records]
            ).strftime("%Y-%m-%d")
            if leader.service_records
            else "Never",
        }
        for leader in leaders
    ]

    return jsonify(leaders_data)


@app.route("/api/leader/<int:leader_id>")
@login_required
def get_leader(leader_id):
    leader = Leader.query.get_or_404(leader_id)
    current_user = get_current_user()
    if current_user and current_user.role != "admin":
        if current_user.leader_id != leader.id:
            return jsonify({"success": False, "message": "Forbidden"}), 403

    leader_data = {
        "id": leader.id,
        "name": leader.name,
        "zone": leader.zone_ref.name if leader.zone_ref else leader.zone,
        "zone_id": leader.zone_id,
        "zone_name": leader.zone_ref.name if leader.zone_ref else leader.zone,
        "branch_id": leader.branch_id,
        "branch_name": leader.branch.name if leader.branch else None,
        "cell_day": leader.cell_day,
        "contact_number": leader.contact_number,
        "email": leader.email,
        "address": leader.address,
        "profile_picture": leader.profile_picture,
        "profile_picture_url": leader.get_profile_picture_url(),
        "initials": leader.get_initials(),
        "is_active": leader.is_active,
    }

    return jsonify(leader_data)


@app.route("/api/leader", methods=["POST"])
@admin_required
def create_leader():
    try:
        data = request.json

        branch_id = data.get("branch_id")
        zone_id = data.get("zone_id")
        if not branch_id or not zone_id:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Branch and zone are required.",
                    }
                ),
                400,
            )

        branch = Branch.query.filter(
            Branch.id == branch_id, Branch.is_active.is_(True)
        ).first()
        if not branch:
            return (
                jsonify({"success": False, "message": "Branch not found."}),
                404,
            )

        zone = Zone.query.filter(
            Zone.id == zone_id,
            Zone.branch_id == branch_id,
            Zone.is_active.is_(True),
        ).first()
        if not zone:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Zone not found for this branch.",
                    }
                ),
                404,
            )

        leader = Leader(
            name=data["name"],
            zone=zone.name,
            branch_id=branch.id,
            zone_id=zone.id,
            cell_day=data.get("cell_day", "Thursday"),
            contact_number=data.get("contact_number", ""),
            email=data.get("email", ""),
            address=data.get("address", ""),
            profile_picture=data.get("profile_picture"),
        )

        db.session.add(leader)
        db.session.commit()

        return jsonify(
            {
                "success": True,
                "message": "Leader created successfully!",
                "leader_id": leader.id,
            }
        )

    except Exception as e:
        db.session.rollback()
        return jsonify(
            {"success": False, "message": f"Error creating leader: {str(e)}"}
        ), 400


@app.route("/api/leader/<int:leader_id>", methods=["PUT"])
@admin_required
def update_leader(leader_id):
    try:
        leader = Leader.query.get_or_404(leader_id)
        data = request.json
        branch_id = data.get("branch_id")
        zone_id = data.get("zone_id")

        if branch_id or zone_id:
            if not branch_id or not zone_id:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "Both branch and zone are required.",
                        }
                    ),
                    400,
                )

            branch = Branch.query.filter(
                Branch.id == branch_id, Branch.is_active.is_(True)
            ).first()
            if not branch:
                return (
                    jsonify({"success": False, "message": "Branch not found."}),
                    404,
                )

            zone = Zone.query.filter(
                Zone.id == zone_id,
                Zone.branch_id == branch_id,
                Zone.is_active.is_(True),
            ).first()
            if not zone:
                return (
                    jsonify(
                        {
                            "success": False,
                            "message": "Zone not found for this branch.",
                        }
                    ),
                    404,
                )
            leader.branch_id = branch.id
            leader.zone_id = zone.id
            leader.zone = zone.name

        leader.name = data["name"]
        leader.cell_day = data.get("cell_day", leader.cell_day)
        leader.contact_number = data.get("contact_number", "")
        leader.email = data.get("email", "")
        leader.address = data.get("address", "")
        leader.is_active = data.get("is_active", True)
        leader.updated_at = datetime.utcnow()

        db.session.commit()

        return jsonify({"success": True, "message": "Leader updated successfully!"})

    except Exception as e:
        db.session.rollback()
        return jsonify(
            {"success": False, "message": f"Error updating leader: {str(e)}"}
        ), 400


@app.route("/api/recent-submissions")
def recent_submissions():
    records = (
        ServiceRecord.query.join(Leader)
        .order_by(ServiceRecord.submitted_at.desc())
        .limit(20)
        .all()
    )

    submissions = [
        {
            "id": record.id,
            "leader_name": record.leader.name,
            "leader_zone": record.leader.zone,
            "service_type": record.service_type,
            "service_date": record.service_date.strftime("%Y-%m-%d"),
            "attendance": record.sunday_attendance
            if record.service_type == "sunday"
            else record.cell_attendance,
            "visitors": record.sunday_visitors
            if record.service_type == "sunday"
            else record.cell_visitors,
            "offering": record.cell_offering if record.service_type == "cell" else 0,
            "decisions": record.cell_decisions if record.service_type == "cell" else 0,
            "notes": record.notes,
            "submitted_at": record.submitted_at.strftime("%Y-%m-%d %H:%M"),
        }
        for record in records
    ]

    return jsonify(submissions)


@app.route("/api/export-csv")
@login_required
def export_csv():
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    zone_filter = request.args.get("zone", "")

    query = ServiceRecord.query.join(Leader).order_by(ServiceRecord.service_date.desc())

    if start_date:
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        query = query.filter(ServiceRecord.service_date >= start_date)

    if end_date:
        end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
        query = query.filter(ServiceRecord.service_date <= end_date)

    if zone_filter:
        query = query.filter(Leader.zone == zone_filter)

    records = query.all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(
        [
            "ID",
            "Leader Name",
            "Zone",
            "Service Type",
            "Service Date",
            "Attendance",
            "Visitors",
            "Offering (ZAR)",
            "Decisions",
            "Notes",
            "Submitted At",
        ]
    )

    for record in records:
        if record.service_type == "sunday":
            attendance = record.sunday_attendance
            visitors = record.sunday_visitors
            offering = 0
            decisions = 0
        else:
            attendance = record.cell_attendance
            visitors = record.cell_visitors
            offering = record.cell_offering
            decisions = record.cell_decisions

        writer.writerow(
            [
                record.id,
                record.leader.name,
                record.leader.zone,
                record.service_type,
                record.service_date.strftime("%Y-%m-%d"),
                attendance,
                visitors,
                offering,
                decisions,
                record.notes or "",
                record.submitted_at.strftime("%Y-%m-%d %H:%M"),
            ]
        )

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=cell_totals_export.csv"},
    )


@app.route("/api/stats/overview")
def stats_overview():
    total_submissions = ServiceRecord.query.filter(
        ServiceRecord.is_cancelled == False
    ).count()
    total_leaders = Leader.query.filter_by(is_active=True).count()

    week_ago = datetime.now().date() - timedelta(days=7)
    recent_submissions = ServiceRecord.query.filter(
        ServiceRecord.service_date >= week_ago,
        ServiceRecord.is_cancelled == False,
    ).count()

    total_offering = (
        db.session.query(db.func.sum(ServiceRecord.cell_offering))
        .filter(ServiceRecord.is_cancelled == False)
        .scalar()
        or 0
    )

    return jsonify(
        {
            "total_submissions": total_submissions,
            "total_leaders": total_leaders,
            "recent_submissions": recent_submissions,
            "total_offering": float(total_offering),
        }
    )


@app.route("/api/zones")
def get_zones():
    """Get all available zones (names list for backward compatibility)."""
    _ensure_default_branch_data()
    branch_id = request.args.get("branch_id")
    zones_query = Zone.query.filter(Zone.is_active.is_(True))
    if branch_id:
        zones_query = zones_query.filter(Zone.branch_id == branch_id)
    zones = [z.name for z in zones_query.order_by(Zone.name).all()]

    if not zones:
        # Fallback to existing list if Zones table is empty
        zones = sorted(set(SA_ZONES))
    return jsonify(zones)


@app.route("/api/zones/objects")
def get_zones_objects():
    """Get all available zones as objects (id, name, branch_id)."""
    _ensure_default_branch_data()
    branch_id = request.args.get("branch_id")
    zones_query = Zone.query.filter(Zone.is_active.is_(True))
    if branch_id:
        zones_query = zones_query.filter(Zone.branch_id == branch_id)
    zones = zones_query.order_by(Zone.name).all()
    return jsonify([{"id": z.id, "name": z.name, "branch_id": z.branch_id} for z in zones])


@app.route("/api/branches")
def get_branches():
    _ensure_default_branch_data()
    branches = (
        Branch.query.filter(Branch.is_active.is_(True))
        .order_by(Branch.name)
        .all()
    )
    return jsonify([{"id": b.id, "name": b.name} for b in branches])


@app.route("/api/branches", methods=["POST"])
@admin_required
def create_branch():
    try:
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"success": False, "message": "Branch name is required."}), 400

        existing = Branch.query.filter(Branch.name == name).first()
        if existing:
            return (
                jsonify({"success": False, "message": "Branch already exists."}),
                409,
            )

        branch = Branch(name=name, is_active=True)
        db.session.add(branch)
        db.session.commit()
        return jsonify({"success": True, "branch": {"id": branch.id, "name": branch.name}})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/zones", methods=["POST"])
@admin_required
def create_zone():
    try:
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        branch_id = data.get("branch_id")

        if not name:
            return jsonify({"success": False, "message": "Zone name is required."}), 400
        if not branch_id:
            return (
                jsonify({"success": False, "message": "branch_id is required."}),
                400,
            )

        branch = Branch.query.get(branch_id)
        if not branch:
            return jsonify({"success": False, "message": "Branch not found."}), 404

        existing = Zone.query.filter(
            Zone.branch_id == branch_id, Zone.name == name
        ).first()
        if existing:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Zone already exists for this branch.",
                    }
                ),
                409,
            )

        zone = Zone(name=name, branch_id=branch_id, is_active=True)
        db.session.add(zone)
        db.session.commit()
        return jsonify(
            {
                "success": True,
                "zone": {"id": zone.id, "name": zone.name, "branch_id": zone.branch_id},
            }
        )
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/leader/<int:leader_id>/delete", methods=["DELETE"])
@admin_required
def delete_leader(leader_id):
    """Delete a leader"""
    try:
        leader = Leader.query.get_or_404(leader_id)

        # Delete profile picture if exists
        if leader.profile_picture:
            delete_profile_picture(leader.profile_picture)

        db.session.delete(leader)
        db.session.commit()

        return jsonify({"success": True, "message": "Leader deleted successfully!"})

    except Exception as e:
        db.session.rollback()
        return jsonify(
            {"success": False, "message": f"Error deleting leader: {str(e)}"}
        ), 500


@app.route("/api/debug/routes")
def debug_routes():
    """Show all available routes for debugging"""
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append(
            {
                "endpoint": rule.endpoint,
                "methods": list(rule.methods),
                "rule": rule.rule,
            }
        )
    return jsonify(routes)


@app.route("/healthz")
def healthz():
    """Simple health check with DB connectivity."""
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# Seed database with real branch/zone/leader structure (destructive)
@app.route("/seed-real-data")
@app.route("/seed-database")
def seed_database():
    allow_seed = app.debug or os.environ.get("ALLOW_SEED", "").lower() == "true"
    if not allow_seed:
        return "Seeding not allowed. Set ALLOW_SEED=true or run in debug mode.", 403

    try:
        # Wipe existing data (development/testing only)
        db.session.query(ServiceRecord).delete()
        db.session.query(Leader).delete()
        db.session.query(Zone).delete()
        db.session.query(Branch).delete()
        db.session.commit()

        branches_data = [
            "Korle-Bu",
            "Belhar East",
            "Symphony",
            "Delft North",
            "Delft South",
            "Outskirts",
            "Eersteriver",
            "Blackheath",
        ]

        zones_data = {
            "Blackheath": ["Kuilsriver", "Wesbank"],
            "Delft North": ["The hague", "Voorbrug", "Roosendal"],
            "Symphony": ["Symphony1", "Symphony2", "Leiden"],
            "Delft South": ["Delft South"],
            "Korle-Bu": ["KB north", "KB South"],
            "Belhar East": ["Extension", "Pentech"],
            "Eersteriver": ["Eersteriver"],
            "Outskirts": ["Tygerberg"],
        }

        leaders_data = {
            ("Blackheath", "Kuilsriver"): ["Darren", "Asive"],
            ("Blackheath", "Wesbank"): ["Jade Erskine", "Walenicia"],
            ("Delft North", "The hague"): ["Felicia", "Geraldine"],
            ("Delft North", "Voorbrug"): ["Nicole", "Clinton"],
            ("Delft North", "Roosendal"): ["Mark", "Zubeira"],
            ("Symphony", "Symphony1"): ["Berenice", "Elias"],
            ("Symphony", "Symphony2"): ["Ashwill", "Mandy"],
            ("Symphony", "Leiden"): ["Richard", "Kelly"],
            ("Delft South", "Delft South"): ["Pam", "Patricia"],
            ("Korle-Bu", "KB north"): ["Nancy", "Gershwin"],
            ("Korle-Bu", "KB South"): ["Micheline", "Daphne"],
            ("Belhar East", "Extension"): ["Griffin", "Ramone"],
            ("Belhar East", "Pentech"): ["Shane", "Aiden"],
            ("Eersteriver", "Eersteriver"): ["Maretha", "Emogan"],
            ("Outskirts", "Tygerberg"): ["Zeeque", "Sandi"],
        }

        branches = {}
        for name in branches_data:
            branch = Branch(name=name, is_active=True)
            db.session.add(branch)
            db.session.flush()
            branches[name] = branch

        zones = {}
        for branch_name, zone_list in zones_data.items():
            branch = branches[branch_name]
            for zone_name in zone_list:
                zone = Zone(
                    name=zone_name, branch_id=branch.id, is_active=True
                )
                db.session.add(zone)
                db.session.flush()
                zones[(branch_name, zone_name)] = zone

        def _make_contact_number(index):
            prefix = 71 + (index % 10)
            middle = 100 + (index * 7 % 900)
            last = 1000 + (index * 13 % 9000)
            return f"+27 {prefix:02d} {middle:03d} {last:04d}"

        leaders = []
        leader_index = 1
        for (branch_name, zone_name), names in leaders_data.items():
            zone = zones[(branch_name, zone_name)]
            branch = branches[branch_name]
            for full_name in names:
                parts = full_name.split()
                first = parts[0]
                last = parts[1] if len(parts) > 1 else "Doe"
                email = f"{first}.{last}@church.org.za".lower()
                leader = Leader(
                    name=f"{first} {last}",
                    zone=zone.name,
                    zone_id=zone.id,
                    branch_id=branch.id,
                    cell_day="Thursday",
                    contact_number=_make_contact_number(leader_index),
                    email=email,
                    address=f"10 Main Road, {zone.name}, Cape Town",
                    profile_picture=None,
                    is_active=True,
                )
                leaders.append(leader)
                leader_index += 1

        db.session.add_all(leaders)
        db.session.commit()

        return (
            "Seed completed successfully.<br><br>"
            + f"Branches: {len(branches)}<br>"
            + f"Zones: {len(zones)}<br>"
            + f"Leaders: {len(leaders)}"
        )

    except Exception as e:
        db.session.rollback()
        return f"Error seeding database: {str(e)}"


@app.cli.command("create-admin")
@click.option("--username", required=True, help="Admin username")
@click.option("--password", required=True, help="Admin password")
@click.option(
    "--role",
    default="admin",
    type=click.Choice(["admin", "user"]),
    help="Role for the user (admin or user)",
)
def create_admin(username, password, role):
    """Create or reset a user."""
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(username=username)
            db.session.add(user)
        user.set_password(password)
        user.is_active = True
        user.role = role
        db.session.commit()
        print(f"User {username} ({role}) is ready.")


@app.cli.command("bootstrap-admin")
@click.option("--username", required=True, help="Admin username")
@click.option("--password", required=True, help="Admin password")
def bootstrap_admin(username, password):
    """Create the first admin only if none exists."""
    with app.app_context():
        existing_admin = User.query.filter_by(role="admin").first()
        if existing_admin:
            print("Admin user already exists. Aborting bootstrap.")
            return
        user = User(username=username, role="admin")
        user.set_password(password)
        user.is_active = True
        db.session.add(user)
        db.session.commit()
        print(f"Admin user {username} created.")

if __name__ == "__main__":
    app.run(debug=True, port=5000)
