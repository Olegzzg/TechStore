"""Интеграционные тесты с настоящим PostgreSQL, без изменения рабочих таблиц."""

import re
import sys
import uuid
from pathlib import Path
from datetime import date, timedelta
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text, select, create_engine, inspect
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import Base, engine, get_db
from models import (
    User,
    Product,
    Promotion,
    Category,
    Order,
    Payment,
    Delivery,
    OrderItem,
)
from app import app
from security import hasher, validate_password, verify_password

PASSWORD = "Study1! -_"


def profile(email="buyer@example.com"):
    return dict(
        email=email,
        full_name="Тестовый Покупатель",
        birth_date="2000-01-01",
        address="Москва, Учебная, 1",
        gender="Мужской",
        interests="Компьютеры",
        vk_url="https://vk.com/test",
        blood_group="II",
        rhesus="+",
    )


@pytest.fixture
def store():
    schema = "test_techstore_" + uuid.uuid4().hex
    with engine.begin() as c:
        c.execute(text(f"CREATE SCHEMA {schema}"))
    test_engine = engine.execution_options(schema_translate_map={None: schema})
    Base.metadata.create_all(test_engine)
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    with factory() as db:
        c = Category(name="Ноутбуки")
        promo = Promotion(
            name="Скидка",
            description="Тест",
            discount_percent=10,
            starts_on=date.today() - timedelta(days=1),
            ends_on=date.today() + timedelta(days=1),
        )
        db.add_all([c, promo])
        db.flush()
        db.add_all(
            [
                Product(
                    name="Apple MacBook",
                    brand="Apple",
                    description="Тестовый ноутбук",
                    price=Decimal("10000"),
                    stock=10,
                    image="/static/images/product-78.webp",
                    category_id=c.id,
                    promotion_id=promo.id,
                ),
                Product(
                    name="ASUS Zenbook",
                    brand="ASUS",
                    description="Ноутбук",
                    price=Decimal("20000"),
                    stock=2,
                    image="/static/images/product-79.webp",
                    category_id=c.id,
                ),
            ]
        )
        for email, admin in [
            ("admin@example.com", True),
            ("buyer@example.com", False),
            ("other@example.com", False),
        ]:
            values = profile(email)
            values["birth_date"] = date.fromisoformat(values["birth_date"])
            db.add(User(**values, password_hash=hasher.hash(PASSWORD), is_admin=admin))
        db.commit()

    def dependency():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.clear()
    with engine.begin() as c:
        c.execute(text(f"DROP SCHEMA {schema} CASCADE"))


def token(client, path="/"):
    response = client.get(path)
    assert response.status_code == 200, response.text[:400]
    match = re.search(r'name="csrf" value="([^"]+)"', response.text)
    assert match, path
    return match.group(1)


def post(client, path, data=None, source="/"):
    return client.post(
        path, data=dict(data or {}, csrf=token(client, source)), follow_redirects=False
    )


def login(client, email="buyer@example.com"):
    r = post(client, "/login", dict(email=email, password=PASSWORD), "/login")
    assert r.status_code == 303, r.text


def checkout(client):
    login(client)
    assert post(client, "/cart/1", dict(quantity=2, action="add")).status_code == 303
    r = post(
        client,
        "/checkout",
        dict(
            address="Москва, 1",
            payment_method="Учебная карта",
            delivery_method="Курьер",
        ),
        "/cart",
    )
    assert r.status_code == 303 and "/orders" in r.headers["location"]


@pytest.mark.parametrize("password", ["Aa1! -_", "Study1! -_"])
def test_valid_password(password):
    assert validate_password(password) == password
    encoded = hasher.hash(password)
    assert encoded.startswith("$argon2id$") and verify_password(password, encoded)
    assert not verify_password(password + "x", encoded)


@pytest.mark.parametrize(
    "password",
    [
        "Aa1!-_",
        "aa1! -_",
        "AA1! -_",
        "Aaa! -_",
        "Aa1 -_",
        "Aa1!__ ",
        "Aa1!-- ",
        "ПарольAa1! -_",
        "Aa1!\t-_",
        "Aa1!\n-_",
    ],
)
def test_invalid_password(password):
    with pytest.raises(ValueError):
        validate_password(password)


def test_public_pages_search_and_images(store):
    client, _ = store
    for path in [
        "/",
        "/products",
        "/products/1",
        "/promotions",
        "/cart",
        "/login",
        "/register",
        "/static/style.css",
        "/static/app.js",
        "/static/vendor/bootstrap.min.css",
        "/static/images/product-78.webp",
    ]:
        assert client.get(path).status_code == 200, path
    r = client.get("/products?q=Apple")
    assert "Apple MacBook" in r.text and "ASUS Zenbook" not in r.text
    assert "9 000 ₽" in r.text
    assert "Apple MacBook" not in client.get("/products?q=notfound").text
    assert client.get("/products/99999").status_code == 404


def test_registration_validation_profile_and_logout(store):
    client, factory = store
    values = profile("new@example.com")
    r = post(
        client,
        "/register",
        dict(values, password=PASSWORD, password_confirm=PASSWORD, is_admin="on"),
        "/register",
    )
    assert r.status_code == 303, r.text
    with factory() as db:
        user = db.scalar(select(User).where(User.email == "new@example.com"))
        assert (
            user and not user.is_admin and verify_password(PASSWORD, user.password_hash)
        )
    assert client.get("/admin").status_code == 403
    assert "new@example.com" in client.get("/profile").text
    r = post(client, "/profile", dict(values, address="Новый адрес"), "/profile")
    assert r.status_code == 303
    assert "Новый адрес" in client.get("/profile").text
    assert post(client, "/logout", source="/profile").status_code == 303
    assert client.get("/profile", follow_redirects=False).status_code == 303
    assert (
        post(
            client, "/login", dict(email="new@example.com", password="wrong"), "/login"
        ).status_code
        == 400
    )
    assert (
        post(
            client,
            "/register",
            dict(values, password=PASSWORD, password_confirm=PASSWORD),
            "/register",
        ).status_code
        == 400
    )


def test_register_invalid_profile_and_password(store):
    client, _ = store
    values = profile("bad@example.com")
    for change in [
        dict(password="Bad"),
        dict(vk_url="https://vk.com.evil.org/test"),
        dict(birth_date="2999-01-01"),
        dict(blood_group="V"),
        dict(email="invalid"),
    ]:
        data = dict(values, password=PASSWORD, password_confirm=PASSWORD)
        data.update(change)
        assert post(client, "/register", data, "/register").status_code == 400


def test_checkout_payment_cancel_and_ownership(store):
    client, factory = store
    checkout(client)
    with factory() as db:
        o = db.scalar(select(Order))
        oid = o.id
        assert (
            o.total == Decimal("18000")
            and o.payment.amount == o.total
            and o.delivery.address == o.address
        )
        assert db.get(Product, 1).stock == 8
        assert o.items[0].price == Decimal("9000")
    assert post(client, f"/orders/{oid}/pay", source="/orders").status_code == 303
    with factory() as db:
        assert db.get(Order, oid).payment.status == "Оплачен"
    assert post(client, f"/orders/{oid}/cancel", source="/orders").status_code == 303
    post(client, f"/orders/{oid}/cancel", source="/orders")
    with factory() as db:
        o = db.get(Order, oid)
        assert (
            o.status == "Отменён"
            and o.payment.status == "Возврат"
            and o.delivery.status == "Отменена"
        )
        assert db.get(Product, 1).stock == 10
    login(client, "other@example.com")
    assert f"Заказ №{oid}" not in client.get("/orders").text
    assert post(client, f"/orders/{oid}/cancel").status_code == 403
    assert post(client, f"/orders/{oid}/pay").status_code == 403


def test_checkout_rejects_missing_stock_and_empty_cart(store):
    client, factory = store
    login(client)
    r = post(
        client,
        "/checkout",
        dict(
            address="Москва", payment_method="Учебная карта", delivery_method="Курьер"
        ),
        "/cart",
    )
    assert "/cart" in r.headers["location"]
    post(client, "/cart/1", dict(quantity=3, action="add"))
    with factory() as db:
        db.get(Product, 1).stock = 1
        db.commit()
    r = post(
        client,
        "/checkout",
        dict(
            address="Москва", payment_method="Учебная карта", delivery_method="Курьер"
        ),
        "/cart",
    )
    assert "/cart" in r.headers["location"]
    with factory() as db:
        assert not db.scalar(select(Order.id)) and db.get(Product, 1).stock == 1


def test_csrf_and_admin_access(store):
    client, _ = store
    assert client.post("/register", data=profile()).status_code == 403
    login(client)
    for path in ["/admin", "/admin/users", "/admin/products/new"]:
        assert client.get(path).status_code == 403
    for path in ["/admin/products/new", "/admin/users/1/delete", "/admin/users/1/edit"]:
        assert post(client, path).status_code == 403
    assert (
        client.post("/cart/1", data=dict(quantity=1, csrf="forged")).status_code == 403
    )


def test_admin_product_promotion_category_crud(store):
    client, factory = store
    login(client, "admin@example.com")
    for section in [
        "products",
        "categories",
        "promotions",
        "users",
        "orders",
        "payments",
        "deliveries",
    ]:
        assert client.get("/admin/" + section).status_code == 200, section
        assert client.get("/admin/" + section + "/new").status_code == 200, section
    assert post(client, "/admin/categories/new", dict(name="Мыши")).status_code == 303
    promotion = dict(
        name="Акция 2",
        description="Новая скидка",
        discount_percent=20,
        starts_on="2026-01-01",
        ends_on="2030-01-01",
    )
    assert post(client, "/admin/promotions/new", promotion).status_code == 303
    with factory() as db:
        cid = db.scalar(select(Category.id).where(Category.name == "Мыши"))
        pid = db.scalar(select(Promotion.id).where(Promotion.name == "Акция 2"))
    data = dict(
        name="Logitech Mouse",
        brand="Logitech",
        description="Описание",
        image="https://example.com/mouse.png",
        price="5000",
        stock=5,
        category_id=cid,
        promotion_id=pid,
    )
    assert post(client, "/admin/products/new", data).status_code == 303
    with factory() as db:
        p = db.scalar(select(Product).where(Product.name == "Logitech Mouse"))
        product_id = p.id
        assert (
            p.image == data["image"]
            and p.promotion_id == pid
            and p.sale_price == Decimal("4000")
        )
    assert (
        post(
            client, f"/admin/products/{product_id}/edit", dict(data, price="6000")
        ).status_code
        == 303
    )
    assert (
        post(
            client,
            f"/admin/products/{product_id}/edit",
            dict(data, image="javascript:alert(1)"),
        ).status_code
        == 400
    )
    assert (
        post(
            client, f"/admin/products/{product_id}/edit", dict(data, price="NaN")
        ).status_code
        == 400
    )
    assert (
        post(
            client, f"/admin/products/{product_id}/edit", dict(data, category_id=99999)
        ).status_code
        == 400
    )
    post(client, f"/admin/categories/{cid}/delete")
    with factory() as db:
        assert db.get(Category, cid)
    assert post(client, f"/admin/promotions/{pid}/delete").status_code == 303
    with factory() as db:
        assert db.get(Product, product_id).promotion_id is None
    assert post(client, f"/admin/products/{product_id}/delete").status_code == 303
    assert post(client, f"/admin/categories/{cid}/delete").status_code == 303
    with factory() as db:
        assert not db.get(Product, product_id) and not db.get(Category, cid)


def test_admin_users_and_roles(store):
    client, factory = store
    login(client, "admin@example.com")
    data = profile("created@example.com")
    assert (
        post(client, "/admin/users/new", dict(data, password=PASSWORD)).status_code
        == 303
    )
    with factory() as db:
        uid = db.scalar(select(User.id).where(User.email == data["email"]))
    assert (
        post(
            client,
            f"/admin/users/{uid}/edit",
            dict(data, full_name="Изменённый Пользователь", is_admin="on"),
        ).status_code
        == 303
    )
    with factory() as db:
        assert db.get(User, uid).is_admin
    assert (
        post(
            client,
            "/admin/users/1/edit",
            dict(profile("admin@example.com"), password=""),
        ).status_code
        == 400
    )
    post(client, "/admin/users/1/delete")
    with factory() as db:
        assert db.get(User, 1)
    assert post(client, f"/admin/users/{uid}/delete").status_code == 303
    with factory() as db:
        assert not db.get(User, uid)


def test_admin_order_payment_delivery_crud_and_stock(store):
    client, factory = store
    login(client, "admin@example.com")
    assert (
        post(
            client, "/admin/orders/new", dict(user_id=2, address="Москва", qty_1=2)
        ).status_code
        == 303
    )
    with factory() as db:
        o = db.scalar(select(Order))
        oid = o.id
        pay_id = o.payment.id
        del_id = o.delivery.id
        assert db.get(Product, 1).stock == 8
    assert client.get(f"/admin/orders/{oid}/edit").status_code == 200
    assert (
        post(
            client,
            f"/admin/orders/{oid}/edit",
            dict(address="Новый адрес", status="В обработке", qty_1=1, qty_2=1),
        ).status_code
        == 303
    )
    with factory() as db:
        o = db.get(Order, oid)
        assert o.total == Decimal("29000") and o.payment.amount == o.total
        assert db.get(Product, 1).stock == 9 and db.get(Product, 2).stock == 1
    assert (
        post(
            client,
            "/admin/payments/new",
            dict(order_id=oid, method="Учебная карта", status="Оплачен"),
        ).status_code
        == 400
    )
    assert post(client, f"/admin/payments/{pay_id}/delete").status_code == 303
    assert (
        post(
            client,
            "/admin/payments/new",
            dict(order_id=oid, method="Учебная карта", status="Ожидает оплаты"),
        ).status_code
        == 303
    )
    assert post(client, f"/admin/deliveries/{del_id}/delete").status_code == 303
    assert (
        post(
            client,
            "/admin/deliveries/new",
            dict(
                order_id=oid,
                address="Москва",
                method="Курьер",
                status="Ожидает отправки",
                tracking_number="TEST123",
            ),
        ).status_code
        == 303
    )
    with factory() as db:
        o = db.get(Order, oid)
        pay_id = o.payment.id
        del_id = o.delivery.id
    assert client.get(f"/admin/payments/{pay_id}/edit").status_code == 200
    assert client.get(f"/admin/deliveries/{del_id}/edit").status_code == 200
    assert (
        post(
            client,
            f"/admin/payments/{pay_id}/edit",
            dict(order_id=oid, method="При получении", status="Оплачен"),
        ).status_code
        == 303
    )
    assert (
        post(
            client,
            f"/admin/deliveries/{del_id}/edit",
            dict(
                order_id=oid,
                address="Москва",
                method="Курьер",
                status="В пути",
                tracking_number="TEST123",
            ),
        ).status_code
        == 303
    )
    with factory() as db:
        assert db.get(Order, oid).status == "Отправлен"
    post(client, "/admin/products/1/delete")
    post(client, "/admin/users/2/delete")
    with factory() as db:
        assert db.get(Product, 1) and db.get(User, 2)
    assert post(client, f"/admin/orders/{oid}/delete").status_code == 303
    with factory() as db:
        assert (
            not db.get(Order, oid)
            and not db.scalar(select(Payment.id))
            and not db.scalar(select(Delivery.id))
            and not db.scalar(select(OrderItem.id))
        )
        assert db.get(Product, 1).stock == 10 and db.get(Product, 2).stock == 2


def test_promotion_period_and_schema_constraints(store):
    _, factory = store
    with factory() as db:
        p = db.get(Product, 1)
        p.promotion.ends_on = date.today() - timedelta(days=1)
        assert p.sale_price == p.price
        # Сами ограничения проверяются PostgreSQL, независимо от формы.
        with pytest.raises(Exception):
            db.get(Product, 1).stock = -1
            db.commit()
        db.rollback()
        assert db.get(Product, 1).stock == 10
