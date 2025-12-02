from app import app, db

print("Creating database tables...")

with app.app_context():
    # This will create all tables
    db.create_all()
    print("✅ Database tables created successfully!")
    print("\nNow start Flask with: python app.py")
    print("Then visit: http://127.0.0.1:5000/seed-database")
