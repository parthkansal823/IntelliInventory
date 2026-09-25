"""Small admin commands.

uv run python -m app.cli reset-password you@yourshop.in "new-password"
uv run python -m app.cli create-admin you@yourshop.in "password" --name "Owner"
"""

from __future__ import annotations

import argparse
import sys

from sqlmodel import select

from app.db import init_db, session_scope
from app.models import Role, User
from app.security import hash_password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    reset = sub.add_parser("reset-password", help="Set a new password for an existing user")
    reset.add_argument("email")
    reset.add_argument("password")
    create = sub.add_parser("create-admin", help="Create (or promote) an admin account")
    create.add_argument("email")
    create.add_argument("password")
    create.add_argument("--name", default="Owner")
    args = parser.parse_args(argv)

    if len(args.password) < 8:
        print("Password must be at least 8 characters", file=sys.stderr)
        return 2
    init_db()
    with session_scope() as s:
        user = s.exec(select(User).where(User.email == args.email.lower())).first()
        if args.command == "reset-password":
            if user is None:
                print(f"No user {args.email}", file=sys.stderr)
                return 1
            user.password_hash = hash_password(args.password)
            user.is_active = True
        else:
            user = user or User(email=args.email.lower(), name=args.name, role=Role.ADMIN, password_hash="")
            user.role, user.is_active = Role.ADMIN, True
            user.password_hash = hash_password(args.password)
        s.add(user)
        s.commit()
    print(f"Done: {args.email} can sign in now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
