"""CLI: python -m app.cli <command> ...

Currently supports:
  create-user --username alice --display-name "Alice" [--admin]
    Prompts for password (twice). Hashes with Argon2id and inserts a User row.

  list-users
    Show all users in the DB.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import User
from app.security.auth import hash_password


async def _create_user(username: str, display_name: str, password: str, *, admin: bool) -> None:
    async with get_sessionmaker()() as session:
        existing = await session.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none() is not None:
            raise SystemExit(f"user '{username}' already exists")
        user = User(
            username=username,
            display_name=display_name,
            password_hash=hash_password(password),
            is_admin=admin,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        print(f"created user {user.username} ({user.id}) admin={user.is_admin}")


async def _list_users() -> None:
    async with get_sessionmaker()() as session:
        result = await session.execute(select(User).order_by(User.created_at))
        for u in result.scalars():
            flag = " [admin]" if u.is_admin else ""
            print(f"{u.id}  {u.username}  '{u.display_name}'{flag}")


def _prompt_password() -> str:
    pw = getpass.getpass("password: ")
    if len(pw) < 10:
        raise SystemExit("password must be at least 10 characters")
    confirm = getpass.getpass("confirm:  ")
    if pw != confirm:
        raise SystemExit("passwords did not match")
    return pw


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    cu = sub.add_parser("create-user", help="create a user (prompts for password)")
    cu.add_argument("--username", required=True)
    cu.add_argument("--display-name", required=True)
    cu.add_argument("--admin", action="store_true")
    cu.add_argument(
        "--password",
        help="for non-interactive scripting only; prefer the prompt for human use",
    )

    sub.add_parser("list-users", help="list users")

    args = parser.parse_args(argv)

    if args.cmd == "create-user":
        password = args.password or _prompt_password()
        asyncio.run(
            _create_user(args.username, args.display_name, password, admin=args.admin)
        )
    elif args.cmd == "list-users":
        asyncio.run(_list_users())
    else:  # pragma: no cover - argparse handles
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
