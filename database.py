# Общая настройка PostgreSQL для сайта, seed.py и служебных скриптов.
# Из .env/окружения берутся DATABASE_URL и DATABASE_SSL; секреты в код не записываются.
# Здесь создаются engine, фабрика сессий SessionLocal и основа моделей Base.
# FastAPI получает отдельную сессию на запрос через зависимость get_db().

import os
import ssl
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Локальный файл дополняет окружение; уже заданные переменные Vercel имеют приоритет по умолчанию.
load_dotenv()


# Приводит URL PostgreSQL к драйверу pg8000 и готовит параметры TLS.
# Вход: value — строка подключения; force_ssl — принудительно включить проверяемый TLS.
# Результат и вызов: Пара (URL SQLAlchemy, dict connect_args); вызывается при импорте модуля и тестами.
def connection_settings(value, force_ssl=False):
    """Neon выдаёт стандартный URL; приложение использует драйвер pg8000."""
    url = make_url(value)
    if url.drivername in ("postgres", "postgresql"):
        url = url.set(drivername="postgresql+pg8000")
    use_ssl = force_ssl or url.query.get("sslmode") in (
        "require",
        "verify-ca",
        "verify-full",
    )
    # Эти параметры libpq не являются аргументами pg8000. TLS проверяет ssl_context.
    url = url.difference_update_query(["sslmode", "channel_binding"])
    return url, {"ssl_context": ssl.create_default_context()} if use_ssl else {}


database_url, connection_args = connection_settings(
    os.environ["DATABASE_URL"], os.getenv("DATABASE_SSL", "false").lower() == "true"
)
# Engine — общий диспетчер соединений, не конкретный HTTP-запрос.
# Малый пул (2 + максимум 3 дополнительных) ограничивает подключения; pre_ping проверяет их пригодность.
engine = create_engine(
    database_url,
    connect_args=connection_args,
    pool_pre_ping=True,
    pool_size=2,
    max_overflow=3,
    hide_parameters=True,
)
# Session хранит отслеживаемые ORM-объекты и текущую транзакцию; это не браузерная session-cookie.
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


# Общая основа ORM-моделей: хранит metadata с описаниями таблиц, сама отдельную таблицу не создаёт.
class Base(DeclarativeBase):
    pass


# Выдаёт одну сессию БД на обработку HTTP-запроса и затем закрывает её.
# Вход: Аргументов нет; фабрика SessionLocal использует общий engine.
# Результат и вызов: Генератор с yield Session; вызывается FastAPI через Depends. commit выполняют сами обработчики.
def get_db():
    # FastAPI продолжает обработчик после yield, затем выходит из with и освобождает соединение.
    # Закрытие без commit не сохраняет незавершённые изменения.
    with SessionLocal() as db:
        yield db
