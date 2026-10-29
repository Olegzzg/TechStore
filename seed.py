"""Создание схемы и демонстрационных данных. Повторный запуск не перезаписывает записи."""

import json
import os
from datetime import date
from pathlib import Path
from decimal import Decimal
from sqlalchemy import select
from database import Base, engine, SessionLocal
from models import (
    Category,
    Promotion,
    Product,
    User,
    Order,
    OrderItem,
    Payment,
    Delivery,
)
from security import hasher, validate_password


def seed():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        # Наличие категории означает, что каталог уже инициализирован: удаления в админке сохраняются.
        if db.scalar(select(Category.id).limit(1)):
            print("TechStore: база готова, существующие данные сохранены.")
            return
        categories = {
            name: Category(name=name)
            for name in [
                "Ноутбуки",
                "Мониторы",
                "Смартфоны",
                "Планшеты",
                "Аудио",
                "Периферия",
            ]
        }
        db.add_all(categories.values())
        promotions = [
            Promotion(
                name="Техника для больших идей",
                description="Скидка на ноутбуки и мониторы для работы, учёбы и творчества.",
                discount_percent=10,
                starts_on=date(2026, 1, 1),
                ends_on=date(2030, 12, 31),
            ),
            Promotion(
                name="Музыка всегда с собой",
                description="Любимые треки звучат выгоднее: специальное предложение на аудиотехнику.",
                discount_percent=15,
                starts_on=date(2026, 1, 1),
                ends_on=date(2030, 12, 31),
            ),
            Promotion(
                name="Мобильная выгода",
                description="Откройте больше возможностей с новым смартфоном или планшетом.",
                discount_percent=7,
                starts_on=date(2026, 1, 1),
                ends_on=date(2030, 12, 31),
            ),
        ]
        db.add_all(promotions)
        db.flush()
        catalog = json.loads(
            (Path(__file__).parent / "catalog.json").read_text(encoding="utf-8")
        )
        products = []
        for i, data in enumerate(catalog):
            values = dict(data)
            category = values.pop("category")
            values.pop("source_url", None)
            values.pop("image_source", None)
            values["price"] = Decimal(str(values["price"]))
            product = Product(
                **values,
                category_id=categories[category].id,
                promotion_id=promotions[
                    (
                        0
                        if category in ["Ноутбуки", "Мониторы"]
                        else 1
                        if category == "Аудио"
                        else 2
                    )
                ].id
                if i % 3 != 2
                else None,
                stock=15 + i % 12,
            )
            db.add(product)
            products.append(product)
        admin_password = validate_password(os.environ["ADMIN_PASSWORD"])
        if admin_password.startswith("CHANGE_ME"):
            raise ValueError("Замените ADMIN_PASSWORD в .env перед запуском seed.py.")
        common = dict(
            birth_date=date(2000, 1, 1),
            address="г. Москва, ул. Учебная, д. 1",
            gender="Мужской",
            interests="Компьютеры, программирование, фотография",
            vk_url="https://vk.com/example",
            blood_group="II",
            rhesus="+",
        )
        admin = User(
            email=os.environ.get("ADMIN_EMAIL", "admin@techstore.local").lower(),
            full_name="Администратор TechStore",
            password_hash=hasher.hash(admin_password),
            is_admin=True,
            **common,
        )
        customer = User(
            email="demo@techstore.local",
            full_name="Иванов Иван Иванович",
            password_hash=hasher.hash(
                validate_password(os.getenv("DEMO_PASSWORD", "Demo1! -_Tech"))
            ),
            is_admin=False,
            **common,
        )
        db.add_all([admin, customer])
        db.flush()
        for index, status in enumerate(["Новый", "Доставлен"]):
            p = products[index]
            p.stock -= 1
            order = Order(user_id=customer.id, address=customer.address, status=status)
            order.items.append(
                OrderItem(product_id=p.id, quantity=1, price=p.sale_price)
            )
            order.payment = Payment(
                amount=order.total,
                method="Учебная карта",
                status="Ожидает оплаты" if index == 0 else "Оплачен",
            )
            order.delivery = Delivery(
                address=order.address,
                method="Курьер",
                status="Ожидает отправки" if index == 0 else "Доставлена",
                tracking_number="" if index == 0 else "DEMO-TECH-002",
            )
            db.add(order)
        db.commit()
        print(
            f"TechStore: создано {len(products)} товаров, 6 категорий, 3 акции, 2 пользователя и 2 заказа."
        )


if __name__ == "__main__":
    seed()
