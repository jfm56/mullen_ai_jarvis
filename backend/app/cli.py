"""CLI: python -m app.cli <command> ...

Commands:
  init
    Guided first-run setup: ensure DB is reachable, run migrations,
    set backup encryption key in keyring, optionally create the first
    admin user.

  create-user --username alice --display-name "Alice" [--admin]
    Prompts for password (twice). Hashes with Argon2id and inserts a User row.

  list-users
    Show all users in the DB.

  backup create --output-dir <path>
    Run pg_dump and encrypt to <path>/jarvis-<ts>.dump.enc.

  backup list
    Show recorded backups.

  backup restore --file <path>
    DESTRUCTIVE — restore the named encrypted dump into the configured DB.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from datetime import datetime, timezone

# Match app.main: psycopg async needs SelectorEventLoop on Windows.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import select  # noqa: E402

from app.db.base import get_sessionmaker  # noqa: E402
from app.db.models import BackupRecord, BackupStatus, User
from app.security.auth import hash_password


# ---- user mgmt ------------------------------------------------------------


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


# ---- backups --------------------------------------------------------------


async def _backup_create(output_dir: str) -> None:
    # Defer imports so `python -m app.cli --help` works without all deps loaded.
    from app.integrations import backup as backup_svc
    from app.integrations.computer import safe_path

    try:
        safe_path.resolve_safe(output_dir)
    except safe_path.UnsafePathError as exc:
        raise SystemExit(f"unsafe output_dir: {exc}")

    print(f"running pg_dump -> {output_dir} ...")
    try:
        result = await backup_svc.create_backup(output_dir=output_dir)
    except backup_svc.BackupError as exc:
        raise SystemExit(str(exc))

    # Record into the DB if a user row exists; otherwise just print the path.
    async with get_sessionmaker()() as session:
        first_user = (await session.execute(
            select(User).order_by(User.created_at).limit(1)
        )).scalar_one_or_none()
        if first_user is None:
            print(f"backup written to {result.path} ({result.bytes_written} bytes)")
            return
        rec = BackupRecord(
            user_id=first_user.id,
            status=BackupStatus.completed,
            file_path=str(result.path),
            file_size=result.bytes_written,
            sha256_hash=result.sha256,
            completed_at=datetime.now(timezone.utc),
        )
        session.add(rec)
        await session.commit()
    print(f"backup completed: {result.path}")
    print(f"  size: {result.bytes_written} bytes")
    print(f"  sha256: {result.sha256}")


async def _backup_list() -> None:
    async with get_sessionmaker()() as session:
        rows = (await session.execute(
            select(BackupRecord).order_by(BackupRecord.started_at.desc())
        )).scalars().all()
        if not rows:
            print("no backups recorded")
            return
        for r in rows:
            ts = r.started_at.strftime("%Y-%m-%d %H:%M:%S")
            print(f"{ts}  {r.status.value:11}  {r.file_size:>12} B  {r.file_path}")


async def _backup_restore(file_path: str) -> None:
    from app.integrations import backup as backup_svc

    answer = input(
        f"DESTRUCTIVE: this will restore {file_path} into the configured DB and "
        f"DROP existing tables that conflict.\nType 'I CONFIRM' to proceed: "
    )
    if answer.strip() != "I CONFIRM":
        raise SystemExit("aborted (confirmation phrase not provided)")

    try:
        await backup_svc.restore_backup(backup_path=file_path)
    except backup_svc.BackupError as exc:
        raise SystemExit(str(exc))
    print(f"restored from {file_path}")


# ---- init ------------------------------------------------------------------


async def _init() -> None:
    """Guided first-run setup."""
    print("== mullen_ai_jarvis init ==")
    print()

    # 1. DB reachable?
    print("1) checking database connection ...")
    try:
        from sqlalchemy import text
        from app.db.base import get_engine

        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        print("   ok")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"database not reachable: {exc}\n"
            f"  install PostgreSQL, create the DB, then set DATABASE_URL in .env"
        )
    print()

    # 2. Backup key in keyring?
    print("2) checking backup encryption key in keyring ...")
    from app.integrations import backup as backup_svc
    from app.security import secrets as secret_store

    try:
        secret_store.get_secret("backup_master_key")
        print("   already set")
    except secret_store.SecretNotFoundError:
        ans = input("   no key found. Generate one now and store in keyring? [y/N]: ")
        if ans.strip().lower() == "y":
            key_b64 = backup_svc.generate_key_b64()
            secret_store.set_secret("backup_master_key", key_b64)
            print("   generated + stored. KEEP A BACKUP OF THIS KEY OFF-MACHINE:")
            print(f"   {key_b64}")
        else:
            print("   skipped — backups won't work until the key is set")
    print()

    # 3. First admin user?
    print("3) checking for at least one user ...")
    async with get_sessionmaker()() as session:
        count = len((await session.execute(select(User))).scalars().all())
    if count > 0:
        print(f"   {count} user(s) already exist — skipping create")
    else:
        ans = input("   no users found. Create an admin user now? [y/N]: ")
        if ans.strip().lower() == "y":
            username = input("     username: ").strip() or "jim"
            display = input(f"     display name [{username}]: ").strip() or username
            password = _prompt_password()
            await _create_user(username, display, password, admin=True)
        else:
            print("   skipped — run `python -m app.cli create-user ...` later")
    print()

    print("== init complete ==")


# ---- main ------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="guided first-run setup (DB, keyring, admin user)")

    cu = sub.add_parser("create-user", help="create a user (prompts for password)")
    cu.add_argument("--username", required=True)
    cu.add_argument("--display-name", required=True)
    cu.add_argument("--admin", action="store_true")
    cu.add_argument(
        "--password",
        help="for non-interactive scripting only; prefer the prompt for human use",
    )

    sub.add_parser("list-users", help="list users")

    bk = sub.add_parser("backup", help="backup operations")
    bk_sub = bk.add_subparsers(dest="subcmd", required=True)
    bc = bk_sub.add_parser("create", help="encrypted pg_dump")
    bc.add_argument("--output-dir", required=True)
    bk_sub.add_parser("list", help="list recorded backups")
    br = bk_sub.add_parser("restore", help="DESTRUCTIVE — restore from an encrypted dump")
    br.add_argument("--file", required=True)

    args = parser.parse_args(argv)

    if args.cmd == "init":
        asyncio.run(_init())
    elif args.cmd == "create-user":
        password = args.password or _prompt_password()
        asyncio.run(
            _create_user(args.username, args.display_name, password, admin=args.admin)
        )
    elif args.cmd == "list-users":
        asyncio.run(_list_users())
    elif args.cmd == "backup":
        if args.subcmd == "create":
            asyncio.run(_backup_create(args.output_dir))
        elif args.subcmd == "list":
            asyncio.run(_backup_list())
        elif args.subcmd == "restore":
            asyncio.run(_backup_restore(args.file))
    else:  # pragma: no cover - argparse handles
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
