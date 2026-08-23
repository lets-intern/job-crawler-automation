"""운영 명령. 지금은 마이그레이션 적용·역적용·상태 확인만 있다.

python -m app.cli migrate up
python -m app.cli migrate down --steps 1
python -m app.cli migrate status
"""

from __future__ import annotations

import argparse

from app import db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="group", required=True)
    migrate = sub.add_parser("migrate", help="스키마 마이그레이션")
    migrate_sub = migrate.add_subparsers(dest="action", required=True)
    migrate_sub.add_parser("up", help="미적용 마이그레이션을 전부 적용")
    down = migrate_sub.add_parser("down", help="마지막 마이그레이션부터 역적용")
    down.add_argument("--steps", type=int, default=1)
    migrate_sub.add_parser("status", help="버전별 적용 여부")
    parser.add_argument("--database", default=None, help="기본값은 DATABASE_PATH")

    args = parser.parse_args(argv)
    conn = db.connect(args.database)
    try:
        if args.action == "up":
            applied = db.migrate_up(conn)
            print("적용됨: " + (", ".join(applied) if applied else "없음 (이미 최신)"))
        elif args.action == "down":
            reverted = db.migrate_down(conn, steps=args.steps)
            print("역적용됨: " + (", ".join(reverted) if reverted else "없음"))
        else:
            for version, state in db.migration_status(conn):
                print(f"{version}\t{state}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
