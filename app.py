"""TechStore: страницы, формы и CRUD. SQLAlchemy-сессия выделяется на каждый запрос."""

import os
import secrets
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlencode, urlparse
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from database import get_db
from models import (
    Category,
    Promotion,
    Product,
    User,
    Order,
    OrderItem,
    Payment,
    Delivery,
    ORDER_STATUSES,
    PAYMENT_STATUSES,
    DELIVERY_STATUSES,
)
from security import (
    hasher,
    validate_password,
    verify_password,
    profile_fields,
    text_field,
    csrf_token,
    PASSWORD_HELP,
)

ROOT = Path(__file__).parent
app = FastAPI(title="TechStore", docs_url=None, redoc_url=None)
if len(os.environ.get("SECRET_KEY", "")) < 32:
    raise RuntimeError(
        "Укажите случайный SECRET_KEY длиной не менее 32 символов в .env."
    )
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SECRET_KEY"],
    same_site="lax",
    https_only=os.getenv("COOKIE_SECURE", "false").lower() == "true",
    max_age=86400,
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
templates.env.filters["rub"] = lambda v: (
    f"{Decimal(v):,.2f}".replace(",", " ").replace(".", ",").removesuffix(",00") + " ₽"
)
SECTIONS = {
    "products": ("Товары", Product),
    "categories": ("Категории", Category),
    "promotions": ("Акции", Promotion),
    "users": ("Покупатели", User),
    "orders": ("Заказы", Order),
    "payments": ("Платежи", Payment),
    "deliveries": ("Доставка", Delivery),
}


def current_user(request, db):
    return (
        db.get(User, request.session["user_id"])
        if request.session.get("user_id")
        else None
    )


def require_user(request, db, admin=False):
    user = current_user(request, db)
    if not user:
        raise HTTPException(303, headers={"Location": "/login"})
    if admin and not user.is_admin:
        raise HTTPException(403, "Доступ разрешён только администратору.")
    return user


def render(request, db, name, status_code=200, **context):
    return templates.TemplateResponse(
        request=request,
        name=name,
        context=dict(
            user=current_user(request, db),
            csrf=csrf_token(request),
            cart_count=sum(request.session.get("cart", {}).values()),
            sections=SECTIONS,
            password_help=PASSWORD_HELP,
            **context,
        ),
        status_code=status_code,
    )


def redirect(path, message=None):
    return RedirectResponse(
        path + ("?" + urlencode({"message": message}) if message else ""),
        status_code=303,
    )


async def checked_form(request):
    """Все изменения выполняются POST-формами с CSRF-токеном подписанной сессии."""
    form = await request.form()
    if not request.session.get("csrf") or not secrets.compare_digest(
        str(form.get("csrf", "")), request.session["csrf"]
    ):
        raise HTTPException(403, "Форма устарела. Обновите страницу.")
    return form


def integer(form, key, minimum=1, maximum=1000000):
    try:
        n = int(str(form.get(key, "")))
    except ValueError:
        raise ValueError(f"Поле {key}: требуется целое число.")
    if not minimum <= n <= maximum:
        raise ValueError(f"Поле {key}: допустимо от {minimum} до {maximum}.")
    return n


def money(form, key):
    try:
        value = Decimal(str(form.get(key, "")).replace(",", "."))
        if (
            not value.is_finite()
            or not Decimal("0.01") <= value <= Decimal("999999999.99")
            or value != value.quantize(Decimal(".01"))
        ):
            raise ValueError()
        return value
    except (InvalidOperation, ValueError):
        raise ValueError(
            "Стоимость должна быть положительным числом с точностью до копеек."
        )


def choice(form, key, options):
    value = str(form.get(key, ""))
    if value not in options:
        raise ValueError(f"Выберите допустимое значение поля {key}.")
    return value


def related(db, model, value):
    try:
        record = db.get(model, int(value))
    except (ValueError, TypeError):
        record = None
    if not record:
        raise ValueError("Связанная запись не найдена. Обновите форму.")
    return record


@app.get("/")
@app.get("/products")
def catalog(
    request: Request,
    q: str = "",
    category: int = 0,
    promo: bool = False,
    sort: str = "popular",
    page: int = 1,
    db: Session = Depends(get_db),
):
    query = select(Product)
    q = q.strip()[:160]
    if q:
        query = query.where(
            or_(
                Product.name.ilike(f"%{q}%"),
                Product.brand.ilike(f"%{q}%"),
                Product.description.ilike(f"%{q}%"),
            )
        )
    if category:
        query = query.where(Product.category_id == category)
    if promo:
        query = query.join(Promotion).where(
            Promotion.starts_on <= date.today(), Promotion.ends_on >= date.today()
        )
    products = list(db.scalars(query.order_by(Product.id)))
    if sort in ("price", "price_desc"):
        products.sort(key=lambda p: p.sale_price, reverse=sort == "price_desc")
    elif sort == "name":
        products.sort(key=lambda p: p.name)
    count = len(products)
    pages = max(1, (count + 11) // 12)
    page = max(1, min(page, pages))
    links = {
        p: "/products?"
        + urlencode(
            dict(q=q, category=category, promo=str(promo).lower(), sort=sort, page=p)
        )
        for p in range(1, pages + 1)
    }
    return render(
        request,
        db,
        "catalog.html",
        products=products[(page - 1) * 12 : page * 12],
        categories=db.scalars(select(Category).order_by(Category.id)).all(),
        q=q,
        category=category,
        promo=promo,
        sort=sort,
        count=count,
        page=page,
        pages=pages,
        links=links,
        home=request.url.path == "/",
    )


@app.get("/products/{product_id}")
def product_page(request: Request, product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Товар не найден.")
    return render(request, db, "product.html", product=product)


@app.get("/promotions")
def promotions(request: Request, db: Session = Depends(get_db)):
    return render(
        request,
        db,
        "promotions.html",
        promotions=db.scalars(select(Promotion).order_by(Promotion.id)).all(),
    )


@app.get("/register")
@app.get("/login")
def auth_page(request: Request, db: Session = Depends(get_db)):
    return render(
        request, db, "auth.html", form={}, register=request.url.path == "/register"
    )


@app.post("/register")
async def register(request: Request, db: Session = Depends(get_db)):
    form = await checked_form(request)
    try:
        values = profile_fields(form)
        password = validate_password(str(form.get("password", "")))
        if password != form.get("password_confirm"):
            raise ValueError("Пароли не совпадают.")
        if db.scalar(select(User).where(User.email == values["email"])):
            raise ValueError("Этот email уже зарегистрирован.")
        user = User(**values, password_hash=hasher.hash(password), is_admin=False)
        db.add(user)
        db.commit()
        # Смена токена после входа. Корзина гостя сохраняется.
        basket = request.session.get("cart", {})
        request.session.clear()
        request.session.update(
            user_id=user.id, csrf=secrets.token_urlsafe(32), cart=basket
        )
        return redirect("/profile", "Регистрация завершена!")
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        return render(
            request,
            db,
            "auth.html",
            status_code=400,
            register=True,
            form=form,
            error=str(exc) if isinstance(exc, ValueError) else "Этот email уже занят.",
        )


@app.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    form = await checked_form(request)
    user = db.scalar(
        select(User).where(User.email == str(form.get("email", "")).strip().lower())
    )
    # Даже для неизвестного email выполняется дорогая проверка хеша.
    encoded = user.password_hash if user else DUMMY_HASH
    password = str(form.get("password", ""))
    valid = verify_password(password if len(password) <= 128 else "", encoded)
    if not user or not valid:
        return render(
            request,
            db,
            "auth.html",
            status_code=400,
            register=False,
            form=form,
            error="Неверный email или пароль.",
        )
    basket = request.session.get("cart", {})
    request.session.clear()
    request.session.update(user_id=user.id, csrf=secrets.token_urlsafe(32), cart=basket)
    return redirect("/profile", "Вы вошли в аккаунт.")


DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))


@app.post("/logout")
async def logout(request: Request):
    await checked_form(request)
    request.session.clear()
    return redirect("/")


@app.get("/profile")
def profile(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    return render(request, db, "profile.html", form=user)


@app.post("/profile")
async def update_profile(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await checked_form(request)
    try:
        values = profile_fields(form)
        if form.get("password"):
            if not verify_password(
                str(form.get("current_password", "")), user.password_hash
            ):
                raise ValueError("Текущий пароль неверен.")
            user.password_hash = hasher.hash(validate_password(str(form["password"])))
        for key, value in values.items():
            setattr(user, key, value)
        db.commit()
        return redirect("/profile", "Профиль сохранён.")
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        return render(
            request,
            db,
            "profile.html",
            status_code=400,
            form=form,
            error=str(exc) if isinstance(exc, ValueError) else "Email уже занят.",
        )


def cart_rows(request, db):
    rows = []
    for key, quantity in request.session.get("cart", {}).items():
        p = db.get(Product, int(key))
        if p:
            rows.append(
                dict(product=p, quantity=quantity, total=p.sale_price * quantity)
            )
    return rows


@app.get("/cart")
def cart_page(request: Request, db: Session = Depends(get_db)):
    rows = cart_rows(request, db)
    return render(
        request,
        db,
        "cart.html",
        rows=rows,
        total=sum((r["total"] for r in rows), Decimal(0)),
    )


@app.post("/cart/{product_id}")
async def cart_update(request: Request, product_id: int, db: Session = Depends(get_db)):
    form = await checked_form(request)
    try:
        p = related(db, Product, product_id)
        basket = dict(request.session.get("cart", {}))
        quantity = integer(form, "quantity", 0, 99)
        if form.get("action") == "add":
            quantity += basket.get(str(product_id), 0)
        if quantity > p.stock or quantity > 99:
            raise ValueError(
                "Недостаточно товара на складе (не более 99 штук в корзине)."
            )
        if quantity:
            if str(product_id) not in basket and len(basket) >= 30:
                raise ValueError("В корзине может быть не более 30 разных товаров.")
            basket[str(product_id)] = quantity
        else:
            basket.pop(str(product_id), None)
        request.session["cart"] = basket
        return redirect("/cart", "Корзина обновлена.")
    except ValueError as exc:
        return redirect("/cart", str(exc))


def quantities_from_form(form):
    quantities = {}
    for key in form:
        if key.startswith("qty_"):
            try:
                pid = int(key[4:])
            except ValueError:
                raise ValueError("Некорректный ID товара.")
            n = integer(form, key, 0, 99)
            if n:
                quantities[pid] = n
    if not quantities or len(quantities) > 30:
        raise ValueError("Выберите от 1 до 30 товаров и укажите количество.")
    return quantities


def create_order(
    db,
    user_id,
    address,
    quantities,
    payment_method="При получении",
    delivery_method="Курьер",
):
    """Блокировка строк товаров предотвращает продажу одного остатка двум покупателям."""
    if not quantities:
        raise ValueError("Корзина пуста.")
    products = db.scalars(
        select(Product)
        .where(Product.id.in_(sorted(quantities)))
        .order_by(Product.id)
        .with_for_update()
    ).all()
    if len(products) != len(quantities):
        raise ValueError("Один из товаров удалён. Обновите корзину.")
    order = Order(user_id=user_id, address=address)
    for p in products:
        n = quantities[p.id]
        if not 1 <= n <= min(p.stock, 99):
            raise ValueError(f"Недостаточно товара «{p.name}».")
        p.stock -= n
        order.items.append(OrderItem(product_id=p.id, quantity=n, price=p.sale_price))
    order.payment = Payment(amount=order.total, method=payment_method)
    order.delivery = Delivery(address=address, method=delivery_method)
    db.add(order)
    db.flush()
    return order


@app.post("/checkout")
async def checkout(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    form = await checked_form(request)
    try:
        basket = {int(k): v for k, v in request.session.get("cart", {}).items()}
        create_order(
            db,
            user.id,
            text_field(form, "address"),
            basket,
            choice(form, "payment_method", ["При получении", "Учебная карта"]),
            choice(form, "delivery_method", ["Курьер", "Самовывоз"]),
        )
        db.commit()
        request.session["cart"] = {}
        return redirect(
            "/orders", "Заказ оформлен. Оплата учебная: реальные деньги не списываются."
        )
    except ValueError as exc:
        db.rollback()
        return redirect("/cart", str(exc))


@app.get("/orders")
def orders(request: Request, db: Session = Depends(get_db)):
    user = require_user(request, db)
    return render(
        request,
        db,
        "orders.html",
        orders=db.scalars(
            select(Order).where(Order.user_id == user.id).order_by(Order.id.desc())
        ).all(),
    )


def locked_order(db, oid):
    order = db.scalar(select(Order).where(Order.id == oid).with_for_update())
    if not order:
        raise HTTPException(404, "Заказ не найден.")
    return order


def change_status(db, order, status):
    """Отмена возвращает остатки ровно один раз; отменённый заказ не возобновляется."""
    if status == order.status:
        return
    if order.status in ("Отменён", "Доставлен"):
        raise ValueError(
            "Завершённый или отменённый заказ нельзя переводить в другой статус."
        )
    if status == "Отменён":
        for item in sorted(order.items, key=lambda i: i.product_id):
            p = db.scalar(
                select(Product).where(Product.id == item.product_id).with_for_update()
            )
            p.stock += item.quantity
        if order.payment and order.payment.status == "Оплачен":
            order.payment.status = "Возврат"
        if order.delivery:
            order.delivery.status = "Отменена"
    elif status in ("Отправлен", "Доставлен") and order.delivery:
        order.delivery.status = "В пути" if status == "Отправлен" else "Доставлена"
    order.status = status


def update_order_items(db, order, quantities):
    """Изменение состава до отправки: сохраняем старые цены, пересчитываем резерв и платёж."""
    old = {item.product_id: item for item in order.items}
    if {pid: item.quantity for pid, item in old.items()} == quantities:
        return
    if order.status not in ("Новый", "В обработке"):
        raise ValueError("Состав можно менять только до отправки заказа.")
    if order.payment and order.payment.status != "Ожидает оплаты":
        raise ValueError(
            "Состав оплаченного заказа менять нельзя. Сначала отмените заказ."
        )
    ids = sorted(set(old) | set(quantities))
    products = {
        p.id: p
        for p in db.scalars(
            select(Product)
            .where(Product.id.in_(ids))
            .order_by(Product.id)
            .with_for_update()
        )
    }
    if len(products) != len(ids):
        raise ValueError("Один из товаров удалён.")
    for pid in ids:
        delta = quantities.get(pid, 0) - (old[pid].quantity if pid in old else 0)
        if delta > products[pid].stock:
            raise ValueError(f"Недостаточно товара «{products[pid].name}».")
        products[pid].stock -= delta
        if pid in old:
            if pid in quantities:
                old[pid].quantity = quantities[pid]
            else:
                order.items.remove(old[pid])
        elif pid in quantities:
            order.items.append(
                OrderItem(
                    product_id=pid,
                    quantity=quantities[pid],
                    price=products[pid].sale_price,
                )
            )
    if order.payment:
        order.payment.amount = order.total


@app.post("/orders/{order_id}/cancel")
async def cancel_order(request: Request, order_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    await checked_form(request)
    order = locked_order(db, order_id)
    if order.user_id != user.id:
        raise HTTPException(403, "Это чужой заказ.")
    try:
        if order.status not in ("Новый", "В обработке"):
            raise ValueError("Заказ уже передан в доставку или завершён.")
        change_status(db, order, "Отменён")
        db.commit()
        return redirect("/orders", "Заказ отменён.")
    except ValueError as exc:
        db.rollback()
        return redirect("/orders", str(exc))


@app.post("/orders/{order_id}/pay")
async def pay_order(request: Request, order_id: int, db: Session = Depends(get_db)):
    user = require_user(request, db)
    await checked_form(request)
    order = locked_order(db, order_id)
    if order.user_id != user.id:
        raise HTTPException(403, "Это чужой заказ.")
    if (
        order.status == "Отменён"
        or not order.payment
        or order.payment.method != "Учебная карта"
        or order.payment.status != "Ожидает оплаты"
    ):
        return redirect("/orders", "Для этого заказа оплата недоступна.")
    order.payment.status = "Оплачен"
    db.commit()
    return redirect("/orders", "Учебный платёж выполнен. Деньги не списывались.")


def section_model(section):
    if section not in SECTIONS:
        raise HTTPException(404, "Раздел не найден.")
    return SECTIONS[section][1]


def edit_context(db, section, record=None, form=None):
    return dict(
        section=section,
        record=record,
        form=form if form is not None else record or {},
        categories=db.scalars(select(Category)).all(),
        promotions=db.scalars(select(Promotion)).all(),
        customers=db.scalars(select(User).order_by(User.id)).all(),
        products=db.scalars(select(Product).order_by(Product.id)).all(),
        orders=db.scalars(select(Order).order_by(Order.id.desc())).all(),
        order_statuses=ORDER_STATUSES,
        payment_statuses=PAYMENT_STATUSES,
        delivery_statuses=DELIVERY_STATUSES,
    )


@app.get("/admin")
def admin_home(request: Request, db: Session = Depends(get_db)):
    require_user(request, db, True)
    counts = {
        k: db.scalar(select(func.count()).select_from(m))
        for k, (_, m) in SECTIONS.items()
    }
    return render(request, db, "admin_home.html", counts=counts)


@app.get("/admin/{section}")
def admin_list(request: Request, section: str, db: Session = Depends(get_db)):
    require_user(request, db, True)
    model = section_model(section)
    return render(
        request,
        db,
        "admin_list.html",
        section=section,
        records=db.scalars(select(model).order_by(model.id.desc())).all(),
    )


@app.get("/admin/{section}/new")
@app.get("/admin/{section}/{record_id}/edit")
def admin_edit(
    request: Request, section: str, record_id: int = 0, db: Session = Depends(get_db)
):
    require_user(request, db, True)
    record = db.get(section_model(section), record_id) if record_id else None
    if record_id and not record:
        raise HTTPException(404, "Запись не найдена.")
    return render(request, db, "admin_edit.html", **edit_context(db, section, record))


@app.post("/admin/{section}/new")
@app.post("/admin/{section}/{record_id}/edit")
async def admin_save(
    request: Request, section: str, record_id: int = 0, db: Session = Depends(get_db)
):
    actor = require_user(request, db, True)
    form = await checked_form(request)
    model = section_model(section)
    record = db.get(model, record_id) if record_id else None
    if record_id and not record:
        raise HTTPException(404, "Запись не найдена.")
    try:
        values = {}
        if section == "categories":
            values = dict(name=text_field(form, "name", 100))
        elif section == "products":
            image = text_field(form, "image", 1000)
            parsed = urlparse(image)
            if not (image.startswith("/static/images/") and ".." not in image) and not (
                parsed.scheme in ("http", "https")
                and parsed.hostname
                and not parsed.username
            ):
                raise ValueError(
                    "Укажите HTTP(S)-ссылку на изображение или /static/images/имя."
                )
            values = dict(
                name=text_field(form, "name", 160),
                brand=text_field(form, "brand", 80),
                description=text_field(form, "description", 10000),
                image=image,
                price=money(form, "price"),
                stock=integer(form, "stock", 0),
                category_id=related(db, Category, form.get("category_id")).id,
                promotion_id=related(db, Promotion, form.get("promotion_id")).id
                if form.get("promotion_id")
                else None,
            )
        elif section == "promotions":
            try:
                start, end = (
                    date.fromisoformat(str(form.get("starts_on", ""))),
                    date.fromisoformat(str(form.get("ends_on", ""))),
                )
            except ValueError:
                raise ValueError("Укажите даты акции.")
            if end < start:
                raise ValueError("Дата окончания должна быть не раньше даты начала.")
            values = dict(
                name=text_field(form, "name", 100),
                description=text_field(form, "description", 3000),
                discount_percent=integer(form, "discount_percent", 1, 90),
                starts_on=start,
                ends_on=end,
            )
        elif section == "users":
            values = profile_fields(form)
            values["is_admin"] = form.get("is_admin") == "on"
            if record and record.id == actor.id and not values["is_admin"]:
                raise ValueError("Нельзя снять права администратора у самого себя.")
            if form.get("password") or not record:
                values["password_hash"] = hasher.hash(
                    validate_password(str(form.get("password", "")))
                )
        elif section == "orders":
            if record:
                record = locked_order(db, record.id)
                address = text_field(form, "address")
                status = choice(form, "status", ORDER_STATUSES)
                if any(key.startswith("qty_") for key in form):
                    update_order_items(db, record, quantities_from_form(form))
                if (
                    record.status in ("Отправлен", "Доставлен", "Отменён")
                    and address != record.address
                ):
                    raise ValueError(
                        "Адрес уже отправленного или завершённого заказа менять нельзя."
                    )
                record.address = address
                if record.delivery:
                    record.delivery.address = address
                change_status(db, record, status)
            else:
                customer = related(db, User, form.get("user_id"))
                record = create_order(
                    db,
                    customer.id,
                    text_field(form, "address"),
                    quantities_from_form(form),
                )
        elif section in ("payments", "deliveries"):
            order = locked_order(db, integer(form, "order_id"))
            if record and record.order_id != order.id:
                raise ValueError(
                    "Нельзя переносить оплату или доставку в другой заказ."
                )
            if not record and (
                order.payment if section == "payments" else order.delivery
            ):
                raise ValueError("У этого заказа уже есть такая запись.")
            values["order_id"] = order.id
            if section == "payments":
                status = choice(form, "status", PAYMENT_STATUSES)
                if order.status == "Отменён" and status == "Оплачен":
                    raise ValueError("Нельзя оплачивать отменённый заказ.")
                if status == "Возврат" and order.status != "Отменён":
                    raise ValueError("Для возврата сначала отмените заказ.")
                values.update(
                    amount=order.total,
                    method=choice(form, "method", ["При получении", "Учебная карта"]),
                    status=status,
                )
            else:
                status = choice(form, "status", DELIVERY_STATUSES)
                if order.status == "Отменён" and status != "Отменена":
                    raise ValueError(
                        "Для отменённого заказа доставка должна быть отменена."
                    )
                if status == "Отменена" and order.status != "Отменён":
                    raise ValueError("Для отмены доставки сначала отмените заказ.")
                if order.status == "Доставлен" and status != "Доставлена":
                    raise ValueError("Заказ уже доставлен.")
                if status == "Доставлена":
                    change_status(db, order, "Доставлен")
                elif status == "В пути":
                    change_status(db, order, "Отправлен")
                elif order.status == "Отправлен":
                    raise ValueError("Заказ уже отправлен.")
                values.update(
                    address=text_field(form, "address"),
                    method=choice(form, "method", ["Курьер", "Самовывоз"]),
                    status=status,
                    tracking_number=str(form.get("tracking_number", "")).strip()[:100],
                )
                order.address = values["address"]
        if record is None:
            record = model(**values)
            db.add(record)
        else:
            for key, value in values.items():
                setattr(record, key, value)
        db.commit()
        return redirect("/admin/" + section, "Запись сохранена.")
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        return render(
            request,
            db,
            "admin_edit.html",
            status_code=400,
            error=str(exc)
            if isinstance(exc, ValueError)
            else "Нарушена уникальность или связь записей. Проверьте email, название и выбранный заказ.",
            **edit_context(db, section, record, form),
        )


@app.post("/admin/{section}/{record_id}/delete")
async def admin_delete(
    request: Request, section: str, record_id: int, db: Session = Depends(get_db)
):
    actor = require_user(request, db, True)
    await checked_form(request)
    record = db.get(section_model(section), record_id)
    if not record:
        raise HTTPException(404, "Запись не найдена.")
    try:
        if section == "users" and record.id == actor.id:
            raise ValueError("Нельзя удалить собственный аккаунт администратора.")
        if section == "users" and record.orders:
            raise ValueError(
                "Покупателя с заказами удалить нельзя: сохраните историю заказов."
            )
        if section == "categories" and record.products:
            raise ValueError("Сначала перенесите или удалите товары категории.")
        if section == "products" and db.scalar(
            select(OrderItem.id).where(OrderItem.product_id == record.id).limit(1)
        ):
            raise ValueError(
                "Товар есть в заказах. Вместо удаления установите остаток 0."
            )
        if section == "orders":
            record = locked_order(db, record.id)
            if record.status == "Доставлен":
                raise ValueError(
                    "Доставленный заказ сохраняется в истории. Удалить можно новый или отменённый заказ."
                )
            change_status(db, record, "Отменён")
        db.delete(record)
        db.commit()
        return redirect("/admin/" + section, "Запись удалена.")
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        return redirect(
            "/admin/" + section,
            str(exc)
            if isinstance(exc, ValueError)
            else "Запись связана с другими данными и не может быть удалена.",
        )


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    if exc.status_code == 303:
        return RedirectResponse(exc.headers["Location"], status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context=dict(code=exc.status_code, detail=exc.detail),
        status_code=exc.status_code,
    )
