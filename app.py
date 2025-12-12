import csv
import io
import json
import os
from datetime import datetime, timedelta

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
from sqlalchemy import inspect
from werkzeug.security import check_password_hash, generate_password_hash

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///cell_tracker.db"
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
class Leader(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    zone = db.Column(db.String(50), nullable=False)
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
    id = db.Column(db.Integer, primary_key=True)
    leader_id = db.Column(db.Integer, db.ForeignKey("leader.id"), nullable=False)
    service_type = db.Column(db.String(20), nullable=False)
    service_date = db.Column(db.Date, nullable=False)

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
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.leader_id = leader_id
        self.service_type = service_type
        self.service_date = service_date
        self.sunday_attendance = sunday_attendance
        self.sunday_visitors = sunday_visitors
        self.cell_attendance = cell_attendance
        self.cell_visitors = cell_visitors
        self.cell_offering = cell_offering
        self.cell_decisions = cell_decisions
        self.notes = notes


# Create tables
with app.app_context():
    db.create_all()


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


def is_authenticated():
    """Check if user is logged in"""
    return session.get("logged_in", False)


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


@app.route("/system-status")
@login_required
def system_status():
    return render_template("system_status.html")


# Authentication routes
@app.route("/login", methods=["GET", "POST"])
def login():
    # If already logged in, redirect to intended page or home
    if is_authenticated():
        next_page = request.args.get("next", url_for("home"))
        return redirect(next_page)

    if request.method == "POST":
        password = request.form.get("password")
        admin_password = os.environ.get("ADMIN_PASSWORD", "church123")

        if password == admin_password:
            session["logged_in"] = True
            session["login_time"] = datetime.utcnow().isoformat()

            next_page = request.args.get("next", url_for("enter_totals"))
            return redirect(next_page)
        else:
            return render_template("login.html", error="Invalid password")

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
@login_required
def leaders_management():
    return render_template("leaders_management.html")


# API Routes


# Public API endpoints (no authentication required)
@app.route("/api/search-leaders")
def search_leaders():
    query = request.args.get("q", "").lower()

    if query:
        leaders = (
            Leader.query.filter(
                (Leader.name.ilike(f"%{query}%")) | (Leader.zone.ilike(f"%{query}%"))
            )
            .filter_by(is_active=True)
            .limit(10)
            .all()
        )
    else:
        leaders = Leader.query.filter_by(is_active=True).limit(5).all()

    leaders_data = [
        {
            "id": leader.id,
            "name": leader.name,
            "zone": leader.zone,
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
    zone_filter = request.args.get("zone", "")
    leader_id = request.args.get("leader_id", "")

    # Calculate date range
    end_date = datetime.now().date()
    if period == "week":
        start_date = end_date - timedelta(days=7)
    elif period == "month":
        start_date = end_date - timedelta(days=30)
    else:  # year
        start_date = end_date - timedelta(days=365)

    # Build query
    query = ServiceRecord.query.join(Leader).filter(
        ServiceRecord.service_date >= start_date, ServiceRecord.service_date <= end_date
    )

    if zone_filter:
        query = query.filter(Leader.zone == zone_filter)

    if leader_id:
        query = query.filter(ServiceRecord.leader_id == leader_id)

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
    zone_filter = request.args.get("zone", "")

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
    query = ServiceRecord.query.join(Leader).filter(
        ServiceRecord.service_date >= start_date, ServiceRecord.service_date <= end_date
    )

    if zone_filter:
        query = query.filter(Leader.zone == zone_filter)

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
        data = request.json

        record = ServiceRecord(
            leader_id=data["leader_id"],
            service_type=data["service_type"],
            service_date=datetime.strptime(data["service_date"], "%Y-%m-%d").date(),
            notes=data.get("notes", ""),
        )

        if data["service_type"] == "sunday":
            record.sunday_attendance = data["sunday_attendance"]
            record.sunday_visitors = data.get("sunday_visitors", 0)
        else:
            record.cell_attendance = data["cell_attendance"]
            record.cell_visitors = data.get("cell_visitors", 0)
            record.cell_offering = data.get("cell_offering", 0.0)
            record.cell_decisions = data.get("cell_decisions", 0)

        db.session.add(record)
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
@login_required  # Temporarily commented out for debugging
def get_leaders():
    zone_filter = request.args.get("zone", "")
    active_only = request.args.get("active_only", "true") == "true"

    query = Leader.query

    if zone_filter:
        query = query.filter(Leader.zone == zone_filter)

    if active_only:
        query = query.filter(Leader.is_active == True)

    leaders = query.order_by(Leader.name).all()

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

    leader_data = {
        "id": leader.id,
        "name": leader.name,
        "zone": leader.zone,
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
@login_required
def create_leader():
    try:
        data = request.json

        leader = Leader(
            name=data["name"],
            zone=data["zone"],
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
@login_required
def update_leader(leader_id):
    try:
        leader = Leader.query.get_or_404(leader_id)
        data = request.json

        leader.name = data["name"]
        leader.zone = data["zone"]
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
    total_submissions = ServiceRecord.query.count()
    total_leaders = Leader.query.filter_by(is_active=True).count()

    week_ago = datetime.now().date() - timedelta(days=7)
    recent_submissions = ServiceRecord.query.filter(
        ServiceRecord.service_date >= week_ago
    ).count()

    total_offering = (
        db.session.query(db.func.sum(ServiceRecord.cell_offering)).scalar() or 0
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
    """Get all available zones"""
    # Use your SA_ZONES list as the source
    zones = sorted(set(SA_ZONES))
    return jsonify(zones)


@app.route("/api/leader/<int:leader_id>/delete", methods=["DELETE"])
@login_required
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


# Seed database with enhanced sample data
# Seed database with enhanced sample data
@app.route("/seed-database")
def seed_database():
    try:
        db.session.query(ServiceRecord).delete()
        db.session.query(Leader).delete()
        db.session.commit()

        leaders = []
        # Create 30 leaders (10 per zone)
        for i in range(1, 31):
            # Distribute evenly among 3 zones
            zone_index = (i - 1) % 3
            zone = SA_ZONES[zone_index]

            # Create leader names like Leader 1, Leader 2, etc.
            leader = Leader(
                name=f"Leader {i}",
                zone=zone,
                cell_day=CELL_DAYS[i % len(CELL_DAYS)],  # Spread across days
                contact_number=f"+27 {70 + i % 30:02d} {100 + i % 900:03d} {1000 + i % 9000:04d}",
                email=f"leader{i}@church.org.za",
                address=f"{i * 10} Main Street, {zone}, South Africa",
            )
            leaders.append(leader)

        db.session.add_all(leaders)
        db.session.commit()

        return (
            f"Successfully added {len(leaders)} leaders across 3 zones to database!<br><br>"
            + f"Zones: {', '.join(SA_ZONES)}<br>"
            + f"Leaders per zone: {len(leaders) // len(SA_ZONES)}"
        )

    except Exception as e:
        db.session.rollback()
        return f"Error seeding database: {str(e)}"


if __name__ == "__main__":
    app.run(debug=True, port=5000)
