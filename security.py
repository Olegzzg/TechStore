# Общие проверки форм, хеширование паролей и создание CSRF-токена.
# app.py вызывает эти функции при регистрации, входе, изменении профиля и в админке.
# seed.py использует тот же PasswordHasher при создании демонстрационных пользователей.
# Функции валидации возвращают проверенные значения либо вызывают ValueError с текстом ошибки.

import re
import secrets
from datetime import date
from urllib.parse import urlparse
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

# argon2-cffi по умолчанию создаёт Argon2id с новой солью; параметры и соль входят в строку хеша.
# Для паролей здесь не используется SHA-256 из скрипта миграции.
hasher = PasswordHasher()
PASSWORD_HELP = "От 7 до 128 символов. Обязателен каждый пункт: A–Z, a–z, цифра, спецсимвол (например !), обычный пробел, дефис - и подчёркивание _. Кириллица запрещена."


# Проверяет все учебные требования к паролю, не удаляя значимые пробелы.
# Вход: value — исходная строка пароля, ровно как ввёл пользователь.
# Результат и вызов: Та же строка либо ValueError с причиной; вызывается register(), update_profile(), admin_save(), seed() и тестами.
def validate_password(value):
    # Пробел, дефис и подчёркивание проверяются отдельно от другого спецсимвола.
    if not 7 <= len(value) <= 128:
        raise ValueError("Пароль должен содержать от 7 до 128 символов.")
    # Печатный ASCII включает A–Z/a–z, цифры, обычный пробел и знаки, но исключает кириллицу и невидимые символы.
    if not all(32 <= ord(c) <= 126 for c in value):
        raise ValueError(
            "В пароле разрешены латинские буквы, цифры, печатные знаки ASCII и обычный пробел. Кириллица, табуляция и переносы строк запрещены."
        )
    checks = [
        (r"[A-Z]", "заглавной латинской буквы A–Z"),
        (r"[a-z]", "строчной латинской буквы a–z"),
        (r"[0-9]", "цифры"),
        (r"[^A-Za-z0-9 _-]", "спецсимвола, например ! или @"),
        (" ", "обычного пробела"),
        ("-", "дефиса «-»"),
        ("_", "подчёркивания «_»"),
    ]
    # Каждый шаблон обязателен сам по себе: пробел, дефис и подчёркивание не заменяют отдельный спецсимвол.
    missing = [label for pattern, label in checks if not re.search(pattern, value)]
    if missing:
        raise ValueError("В пароле не хватает: " + "; ".join(missing) + ".")
    return value


# Сравнивает введённый пароль с Argon2-хешем без расшифровки.
# Вход: password — исходный пароль; encoded — сохранённая строка password_hash.
# Результат и вызов: bool; неверный пароль/повреждённый хеш дают False. Вызывается login(), update_profile() и тестами.
def verify_password(password, encoded):
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


# Читает обязательное текстовое поле, убирает пробелы по краям и проверяет длину.
# Вход: form — словарь/FormData; key — имя поля; limit — максимальное число символов.
# Результат и вызов: Непустая строка либо ValueError; вызывается profile_fields() и проверками полей в app.py. Для паролей не используется.
def text_field(form, key, limit=300):
    value = str(form.get(key, "")).strip()
    if not value or len(value) > limit:
        raise ValueError(f"Поле «{key}» обязательно (до {limit} символов).")
    return value


# Проверяет и приводит к нужным типам все общие поля профиля.
# Вход: form — поля регистрации, профиля или административной формы пользователя.
# Результат и вызов: dict для User: включая date рождения и email в нижнем регистре; иначе ValueError. Вызывается app.py и тестами.
def profile_fields(form):
    email = text_field(form, "email", 254).lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Введите корректный email.")
    try:
        birthday = date.fromisoformat(str(form.get("birth_date", "")))
    except ValueError:
        raise ValueError("Введите дату рождения.")
    if not date(1900, 1, 1) <= birthday <= date.today():
        raise ValueError(
            "Дата рождения должна быть между 1900 годом и сегодняшним днём."
        )
    vk = text_field(form, "vk_url", 250)
    # Проверка hostname не позволит принять https://vk.ru.example.org/... за настоящий домен VK.
    parsed = urlparse(vk)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ("vk.ru", "www.vk.ru", "vk.com", "www.vk.com")
        or not parsed.path.strip("/")
    ):
        raise ValueError(
            "Ссылка VK должна иметь вид https://vk.ru/username (также поддерживается vk.com)."
        )
    values = {
        key: text_field(form, key, size)
        for key, size in [("full_name", 160), ("address", 300), ("interests", 2000)]
    }
    for key, allowed in [
        ("gender", ["Мужской", "Женский"]),
        ("blood_group", ["I", "II", "III", "IV"]),
        ("rhesus", ["+", "-"]),
    ]:
        values[key] = str(form.get(key, ""))
        if values[key] not in allowed:
            raise ValueError("Выберите пол, группу крови и резус-фактор.")
    return dict(values, email=email, birth_date=birthday, vk_url=vk)


# Возвращает токен формы и создаёт случайный, если его ещё нет в сессии.
# Вход: request — запрос с session, предоставленной SessionMiddleware.
# Результат и вызов: Строка токена; вызывается render(), затем hidden-поле формы проверяет checked_form() из app.py.
def csrf_token(request):
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(32)
    return request.session["csrf"]
