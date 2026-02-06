"""Helper script for initializing the database via migrations."""
import os

print("Initializing database with Flask-Migrate...")

# Set FLASK_APP if not already set
os.environ.setdefault("FLASK_APP", "app.py")

print("Run these commands:")
print("  flask db init    # first time only")
print("  flask db migrate -m \"initial\"")
print("  flask db upgrade")
print("\nThen start the app with: python app.py")
