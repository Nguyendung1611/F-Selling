import sqlite3
from datetime import datetime, timezone

conn = sqlite3.connect("fselling_v4.db")
cursor = conn.cursor()

# Find expired unverified users
cursor.execute("""
    SELECT id, username, email, is_verified, verification_code_expires 
    FROM users 
    WHERE is_verified = 0 
    AND verification_code_expires IS NOT NULL
""")

expired_users = cursor.fetchall()
print(f"\nFound {len(expired_users)} unverified users:")
for user in expired_users:
    user_id, username, email, is_verified, verification_code_expires = user
    print(f"  ID: {user_id}, Username: {username}, Email: {email}")
    print(f"  Expires: {verification_code_expires}")
    
    # Parse the datetime and compare
    try:
        expiry_str = verification_code_expires
        # SQLite stores datetime as string, parse it (naive datetime)
        # Format: '2026-06-25 09:24:43.486028'
        expiry_datetime = datetime.fromisoformat(expiry_str)
        # Use naive datetime for comparison to match SQLAlchemy behavior
        now = datetime.utcnow()
        
        print(f"  Expiry datetime: {expiry_datetime}")
        print(f"  Current time: {now}")
        print(f"  Expired: {now > expiry_datetime}")
        
        if now > expiry_datetime:
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            print(f"  ✓ DELETED")
        else:
            remaining = expiry_datetime - now
            print(f"  Not expired yet - {remaining.total_seconds():.1f} seconds remaining")
    except Exception as e:
        print(f"  Error parsing datetime: {e}")
    print()

conn.commit()

# Show remaining users
print("\n=== Remaining users after cleanup ===")
cursor.execute("SELECT id, username, email, is_verified FROM users")
for row in cursor.fetchall():
    print(f"ID: {row[0]}, Username: {row[1]}, Email: {row[2]}, Verified: {row[3]}")

conn.close()
print("\nCleanup complete!")
