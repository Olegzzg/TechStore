# TechStore
Простой учебный FastAPI + PostgreSQL + SQLAlchemy + Jinja2, вариант 34.
Ответы, комментарии и интерфейс на русском. Не изменять соседний SportStore.
Секреты только в .env, локальная БД только в .local (оба исключены из Git).

Команды PowerShell из корня:
- `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`
- `.\.venv\Scripts\python.exe scripts\setup_local_db.py` — отдельный кластер 127.0.0.1:55433.
- `.\.venv\Scripts\python.exe seed.py` — схема и демонстрационные данные, повторный запуск сохраняет изменения.
- `.\start.ps1` — PostgreSQL и сайт localhost:8000.
- `.\.venv\Scripts\python.exe -m pytest -q` — интеграционные тесты в отдельной схеме PostgreSQL, не в рабочих таблицах.
- `.\.venv\Scripts\python.exe scripts\set_admin.py EMAIL` — выдать администратора; `--revoke` — снять.
