"""Назначить/снять администратора: python scripts/set_admin.py email [--revoke]."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select, func
from database import SessionLocal
from models import User


def main():
    parser = argparse.ArgumentParser(description="Управление администратором TechStore")
    parser.add_argument("email")
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args.email.strip().lower()))
        if not user:
            raise SystemExit(
                "Пользователь не найден. Сначала зарегистрируйте его на сайте."
            )
        if (
            args.revoke
            and user.is_admin
            and db.scalar(select(func.count()).select_from(User).where(User.is_admin))
            <= 1
        ):
            raise SystemExit("Нельзя снять права у последнего администратора.")
        user.is_admin = not args.revoke
        db.commit()
        print(
            f"{user.email}: "
            + ("права администратора сняты" if args.revoke else "администратор")
        )


if __name__ == "__main__":
    main()
