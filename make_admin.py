#!/usr/bin/env python3
"""
Make a user an admin.

Usage:
    python3 make_admin.py user@email.com
"""

import sys
from server import app, db
from models import User

def make_admin(email):
    with app.app_context():
        user = User.query.filter_by(email=email.lower()).first()
        if not user:
            print(f"Error: User '{email}' not found.")
            print("\nExisting users:")
            for u in User.query.all():
                admin_tag = " [ADMIN]" if u.is_admin else ""
                print(f"  - {u.email}{admin_tag}")
            return False

        if user.is_admin:
            print(f"User '{email}' is already an admin.")
            return True

        user.is_admin = True
        db.session.commit()
        print(f"Success! User '{email}' is now an admin.")
        print(f"They can access the admin dashboard at /admin")
        return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 make_admin.py user@email.com")
        print("\nThis will grant admin access to the specified user.")
        sys.exit(1)

    email = sys.argv[1]
    success = make_admin(email)
    sys.exit(0 if success else 1)
