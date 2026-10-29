# Первичная установка отдельного локального PostgreSQL для TechStore на Windows.
# Использует уже установленные initdb/pg_ctl, создаёт .local/postgres и собственную .env.
# Запускается вручную один раз; затем база и сайт запускаются через start.ps1.
# Не создаёт таблицы магазина: этим позже занимается seed.py.

"""Подготовка отдельного PostgreSQL на Windows без изменения других баз."""

import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
PORT = 55433


# Создаёт кластер на 127.0.0.1:55433, роль приложения и отдельную базу techstore.
# Вход: Аргументов нет; пути Windows и свободный порт проверяются внутри.
# Результат и вызов: None либо SystemExit/ошибка subprocess; вызывается только CLI. Существующий .env сохраняется без изменений.
def main():
    if (ROOT / ".env").exists():
        print(".env уже существует. Настройки не изменены; используйте start.ps1.")
        return
    installs = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "PostgreSQL"
    options = sorted(
        installs.glob("*/bin/pg_ctl.exe"),
        key=lambda p: tuple(
            int(n) for n in p.parent.parent.name.split(".") if n.isdigit()
        ),
        reverse=True,
    )
    if not options:
        raise SystemExit(
            "Установите PostgreSQL или настройте DATABASE_URL в .env вручную."
        )
    pg_bin = options[0].parent
    if (LOCAL / "postgres").exists():
        raise SystemExit(
            "Локальный кластер уже существует. Восстановите .env из собственной копии."
        )
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", PORT)) == 0:
            raise SystemExit(f"Порт {PORT} занят. Настройте другую базу вручную.")
    LOCAL.mkdir(exist_ok=True)
    owner_password = secrets.token_urlsafe(24)
    app_password = secrets.token_urlsafe(24)
    password_file = LOCAL / "pg-password.txt"
    password_file.write_text(owner_password, encoding="ascii")
    subprocess.run(
        [
            str(pg_bin / "initdb.exe"),
            "-D",
            str(LOCAL / "postgres"),
            "-U",
            "techstore_owner",
            "--auth=scram-sha-256",
            "--pwfile=" + str(password_file),
            "--encoding=UTF8",
            "--locale=C",
        ],
        check=True,
    )
    subprocess.run(
        [
            str(pg_bin / "pg_ctl.exe"),
            "-D",
            str(LOCAL / "postgres"),
            "-l",
            str(LOCAL / "postgres.log"),
            "-o",
            f"-h 127.0.0.1 -p {PORT}",
            "start",
        ],
        check=True,
    )
    engine = create_engine(
        f"postgresql+pg8000://techstore_owner:{owner_password}@127.0.0.1:{PORT}/postgres",
        # CREATE DATABASE PostgreSQL не разрешает внутри обычного блока транзакции.
        isolation_level="AUTOCOMMIT",
    )
    with engine.connect() as db:
        # Пароль создан secrets, состоит только из URL-safe символов.
        db.execute(
            text(
                f"CREATE ROLE techstore LOGIN PASSWORD '{app_password}' NOSUPERUSER NOCREATEDB NOCREATEROLE"
            )
        )
        db.execute(text("CREATE DATABASE techstore OWNER techstore"))
    engine.dispose()
    (ROOT / ".env").write_text(
        f'DATABASE_URL=postgresql+pg8000://techstore:{app_password}@127.0.0.1:{PORT}/techstore\nSECRET_KEY={secrets.token_urlsafe(48)}\nCOOKIE_SECURE=false\nADMIN_EMAIL=admin@techstore.local\nADMIN_PASSWORD="Admin1! -_Tech"\n',
        encoding="utf-8",
    )
    print(
        f"Готово: PostgreSQL 127.0.0.1:{PORT}, база techstore. Запустите .\\start.ps1"
    )


if __name__ == "__main__":
    main()
