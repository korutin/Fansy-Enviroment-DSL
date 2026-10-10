"""CLI: python -m cte scenario.tenv [--dsn ... --user ... --password ...] [--dry-run]

Без --dsn (или явно с --dry-run) сценарий прогоняется на FakeDatabase:
ничего не пишет в БД, только печатает план вызовов API_* — полезно, чтобы
проверить сам сценарий (алиасы, порядок, as_of) до похода на реальный стенд.
"""
from __future__ import annotations

import argparse
import sys

from .db import DryRunDatabase, FirebirdDatabase
from .engine import Engine, required_generators, required_procedures
from .model import DslError, parse_file


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="cte", description="Fansy CTE — создатель тестового окружения")
    ap.add_argument("scenario", help="путь к .tenv файлу")
    ap.add_argument("--dsn", help="Firebird DSN, напр. localhost/3050:/path/to/data.fdb")
    ap.add_argument("--user", default="SYSDBA")
    ap.add_argument("--password", default="")
    ap.add_argument(
        "--charset", default="WIN1251",
        help="кодировка подключения (по умолчанию WIN1251 — базы Fansy в cp1251)",
    )
    ap.add_argument(
        "--driver", default="auto", choices=["auto", "fdb", "firebird-driver"],
        help="fdb — для Firebird 2.5; firebird-driver — для 3.0+ (по умолчанию auto)",
    )
    ap.add_argument(
        "--fb-client", default=None,
        help="путь к fbclient.dll, если библиотека не находится автоматически",
    )
    ap.add_argument(
        "--no-preflight", action="store_true",
        help="не проверять наличие нужных процедур в БД перед запуском",
    )
    ap.add_argument("--dry-run", action="store_true", help="не подключаться к БД, только показать план вызовов")
    args = ap.parse_args(argv)

    try:
        blocks = parse_file(args.scenario)
    except DslError as e:
        print(f"Ошибка разбора: {e}", file=sys.stderr)
        return 1

    dry_run = args.dry_run or not args.dsn
    if dry_run:
        db = DryRunDatabase()
    else:
        try:
            db = FirebirdDatabase(
                args.dsn, args.user, args.password,
                charset=args.charset, driver=args.driver, fb_client=args.fb_client,
            )
        except (RuntimeError, ValueError) as e:
            print(f"Не удалось подключиться к БД:\n{e}", file=sys.stderr)
            return 2
        print(f"Подключение установлено (драйвер {db.driver}, кодировка {args.charset})")

        if not args.no_preflight:
            need, optional = required_procedures(blocks)
            missing = db.missing_procedures(need)
            missing_opt = db.missing_procedures(optional)
            missing_gen = db.missing_generators(required_generators(blocks))
            if missing_gen:
                print(
                    "\nВ базе отсутствуют генераторы: " + ", ".join(missing_gen),
                    file=sys.stderr,
                )
                db.close()
                return 3
            if missing:
                print(
                    "\nВ базе отсутствуют процедуры, без которых сценарий не отработает:",
                    file=sys.stderr,
                )
                for name in missing:
                    print(f"  {name}", file=sys.stderr)
                print(
                    "\nНакатите sql/api_stubs_test_env.sql на стенд "
                    "(isql -i sql/api_stubs_test_env.sql) либо реализуйте их.",
                    file=sys.stderr,
                )
                db.close()
                return 3
            if missing_opt:
                print(
                    "Предупреждение: нет процедур обновления "
                    + ", ".join(missing_opt)
                    + " — повторные блоки в сценарии не сработают."
                )

    engine = Engine(db)
    exit_code = 0
    try:
        engine.run(blocks)
    except DslError as e:
        print(f"Ошибка сценария: {e}", file=sys.stderr)
        exit_code = 1
    except RuntimeError as e:
        print(f"Ошибка вызова процедуры: {e}", file=sys.stderr)
        exit_code = 1
    finally:
        for line in engine.log:
            print(line)
        if engine.warnings:
            print("\n--- предупреждения (вызваны нереализованные процедуры) ---")
            for w in engine.warnings:
                print(f"  {w}")
        if dry_run:
            print("\n--- DRY RUN: журнал вызовов API_* (в БД ничего не записано) ---")
            for proc, call_args in db.calls:
                print(f"{proc}({', '.join(repr(a) for a in call_args)})")
        else:
            if exit_code == 0:
                db.commit()
                print("\nТранзакция зафиксирована (commit).")
            else:
                print(
                    "\nТранзакция НЕ зафиксирована — всё созданное этим прогоном "
                    "откатывается, база остаётся в исходном состоянии.",
                    file=sys.stderr,
                )
            db.close()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
