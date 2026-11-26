"""Local staff-account setup. Never exposes account registration over HTTP."""
import argparse
from getpass import getpass
import os
from pathlib import Path

from .database import contextmanager_connection, initialize, now
from .security import hash_password, ROLES


def main():
    parser = argparse.ArgumentParser(description="Create a Jamrock Bitez staff account")
    parser.add_argument("username")
    parser.add_argument("--role", choices=ROLES, required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    password = getpass("Password (minimum 10 characters): ")
    if len(password) < 10 or password != getpass("Confirm password: "):
        parser.error("Passwords must match and contain at least 10 characters.")
    database = initialize(os.environ.get("JAMROCK_DATA_DIR") or str(Path(__file__).resolve().parents[1] / "jamrock_data"))
    with contextmanager_connection(database) as conn:
        cursor = conn.execute("INSERT INTO users(username,display_name,role,password_hash) VALUES (?,?,?,?)",
                              (args.username, args.name, args.role, hash_password(password)))
        conn.execute("INSERT INTO audit_log(user_id,action,resource,recorded_at) VALUES (?,?,?,?)",
                     (cursor.lastrowid, "local_account_creation", str(cursor.lastrowid), now()))
    print(f"Created {args.username} as {args.role}.")


if __name__ == "__main__":
    main()
