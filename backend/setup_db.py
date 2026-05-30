"""One-off Postgres bootstrap.

Creates the `jarvis` user (password `jarvis`), the `jarvis` database
owned by that user, and enables the `vector` extension. Idempotent —
re-running won't fail if anything already exists.

Run this once if `psql` isn't on PATH. Otherwise prefer:
    psql -U postgres -c "CREATE USER jarvis WITH PASSWORD 'jarvis';"
"""

from __future__ import annotations

import getpass
import sys

import psycopg


def main() -> None:
    pw = getpass.getpass("Postgres superuser password (for 'postgres'): ")

    # Step 1: connect to the postgres meta-database to create user + db.
    # CREATE DATABASE requires autocommit (cannot be in a transaction).
    with psycopg.connect(
        host="127.0.0.1",
        port=5432,
        user="postgres",
        password=pw,
        dbname="postgres",
        autocommit=True,
    ) as conn:
        with conn.cursor() as cur:
            # User.
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'jarvis';")
            if cur.fetchone() is None:
                cur.execute("CREATE USER jarvis WITH PASSWORD 'jarvis';")
                print("✓ created user 'jarvis'")
            else:
                cur.execute("ALTER USER jarvis WITH PASSWORD 'jarvis';")
                print("✓ user 'jarvis' already exists (password reset)")

            # Database.
            cur.execute("SELECT 1 FROM pg_database WHERE datname = 'jarvis';")
            if cur.fetchone() is None:
                cur.execute('CREATE DATABASE jarvis OWNER jarvis;')
                print("✓ created database 'jarvis'")
            else:
                print("✓ database 'jarvis' already exists")

    # Step 2: connect to the jarvis db itself to enable the extension.
    try:
        with psycopg.connect(
            host="127.0.0.1",
            port=5432,
            user="postgres",
            password=pw,
            dbname="jarvis",
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                print("✓ vector extension enabled")
    except psycopg.errors.UndefinedFile:
        print(
            "✗ pgvector is not installed on this Postgres.\n"
            "  Install from https://github.com/pgvector/pgvector#windows\n"
            "  Then re-run this script. Auth/tasks/projects/grants/agents\n"
            "  will work without it; memory endpoints will not."
        )
        sys.exit(1)
    except psycopg.Error as exc:
        print(f"✗ extension setup failed: {exc}")
        sys.exit(1)

    print("\nDone. Now:")
    print("  alembic upgrade head")
    print("  python -m app.cli create-user --username jim --display-name \"Jim Mullen\" --admin")


if __name__ == "__main__":
    main()
