"""Восемь таблиц варианта 34. Денежные значения хранятся точно: NUMERIC, не float."""

from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    String,
    Text,
    ForeignKey,
    Date,
    DateTime,
    Numeric,
    CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

ORDER_STATUSES = ["Новый", "В обработке", "Отправлен", "Доставлен", "Отменён"]
PAYMENT_STATUSES = ["Ожидает оплаты", "Оплачен", "Возврат"]
DELIVERY_STATUSES = ["Ожидает отправки", "В пути", "Доставлена", "Отменена"]


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Promotion(Base):
    __tablename__ = "promotions"
    __table_args__ = (
        CheckConstraint("discount_percent BETWEEN 1 AND 90"),
        CheckConstraint("ends_on >= starts_on"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text)
    discount_percent: Mapped[int]
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    products: Mapped[list["Product"]] = relationship(
        back_populates="promotion", passive_deletes=True
    )

    @property
    def active(self):
        return self.starts_on <= date.today() <= self.ends_on


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (CheckConstraint("price > 0"), CheckConstraint("stock >= 0"))
    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    # В товаре хранится ID акции. Удаление акции оставляет товар без скидки.
    promotion_id: Mapped[int | None] = mapped_column(
        ForeignKey("promotions.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    brand: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    image: Mapped[str] = mapped_column(String(1000))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    stock: Mapped[int] = mapped_column(default=20)
    category: Mapped[Category] = relationship(back_populates="products")
    promotion: Mapped[Promotion | None] = relationship(back_populates="products")

    @property
    def sale_price(self):
        discount = (
            self.promotion.discount_percent
            if self.promotion and self.promotion.active
            else 0
        )
        return (Decimal(self.price) * (100 - discount) / 100).quantize(Decimal("0.01"))


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(160))
    birth_date: Mapped[date] = mapped_column(Date)
    address: Mapped[str] = mapped_column(String(300))
    gender: Mapped[str] = mapped_column(String(20))
    interests: Mapped[str] = mapped_column(Text)
    vk_url: Mapped[str] = mapped_column(String(250))
    blood_group: Mapped[str] = mapped_column(String(5))
    rhesus: Mapped[str] = mapped_column(String(1))
    is_admin: Mapped[bool] = mapped_column(default=False)
    orders: Mapped[list["Order"]] = relationship(back_populates="user")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Новый','В обработке','Отправлен','Доставлен','Отменён')"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="Новый")
    address: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    user: Mapped[User] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )
    payment: Mapped["Payment | None"] = relationship(
        back_populates="order", cascade="all, delete-orphan", uselist=False
    )
    delivery: Mapped["Delivery | None"] = relationship(
        back_populates="order", cascade="all, delete-orphan", uselist=False
    )

    @property
    def total(self):
        return sum((i.price * i.quantity for i in self.items), Decimal(0))


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity > 0"), CheckConstraint("price > 0"))
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[int]
    # Снимок цены со скидкой на момент оформления сохраняет историю заказа.
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0"),
        CheckConstraint("status IN ('Ожидает оплаты','Оплачен','Возврат')"),
        CheckConstraint("method IN ('При получении','Учебная карта')"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), unique=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    method: Mapped[str] = mapped_column(String(30), default="При получении")
    status: Mapped[str] = mapped_column(String(30), default="Ожидает оплаты")
    order: Mapped[Order] = relationship(back_populates="payment")


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Ожидает отправки','В пути','Доставлена','Отменена')"
        ),
        CheckConstraint("method IN ('Курьер','Самовывоз')"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), unique=True
    )
    address: Mapped[str] = mapped_column(String(300))
    method: Mapped[str] = mapped_column(String(30), default="Курьер")
    status: Mapped[str] = mapped_column(String(30), default="Ожидает отправки")
    tracking_number: Mapped[str] = mapped_column(String(100), default="")
    order: Mapped[Order] = relationship(back_populates="delivery")
