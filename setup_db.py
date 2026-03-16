# setup_db.py
from app import app, db, create_admin

print("=" * 50)
print("🚀 BLOOD AID DATABASE SETUP")
print("=" * 50)

with app.app_context():
    try:
        print("📦 Creating database tables...")
        db.create_all()
        print("✓ Database tables created successfully!")
    except Exception as e:
        print(f"✗ Error creating tables: {e}")

    try:
        print("\n👑 Setting up admin user...")
        create_admin()
        print("✓ Admin user setup complete")
    except Exception as e:
        print(f"✗ Error creating admin: {e}")

print("\n✅ Database setup finished!")
print("=" * 50)
