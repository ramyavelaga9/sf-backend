import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AddressType(str, enum.Enum):
    HOME = "Home"
    WORK = "Work"
    OTHER = "Other"


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    first_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    photo_url: Mapped[str | None] = mapped_column(Text)

    company: Mapped[str | None] = mapped_column(String(200))
    job_title: Mapped[str | None] = mapped_column(String(200))

    notes: Mapped[str | None] = mapped_column(Text)

    # One contact can have many addresses (Home/Work/Other); see `Address` below.
    addresses: Mapped[list["Address"]] = relationship(
        back_populates="contact",
        cascade="all, delete-orphan",
        order_by="Address.id",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Contact id={self.id} email={self.email!r}>"


class Address(Base):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # native_enum=False stores this as a plain VARCHAR rather than a native
    # Postgres ENUM type, so it behaves identically on SQLite too.
    # create_constraint=True adds the CHECK that actually enforces the allowed
    # values at the DB layer (SQLAlchemy does not add one by default).
    # values_callable persists the enum's *values* ("Home") rather than its
    # member names ("HOME"), matching what the API documents and returns.
    type: Mapped[AddressType] = mapped_column(
        Enum(
            AddressType,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    address: Mapped[str | None] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(120))

    contact: Mapped[Contact] = relationship(back_populates="addresses")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Address id={self.id} type={self.type.value} contact_id={self.contact_id}>"
