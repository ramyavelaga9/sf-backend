from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Address, Contact, utcnow
from app.schemas import ContactCreate, ContactReplace, ContactUpdate

SORTABLE_FIELDS = ("id", "first_name", "last_name", "email", "company", "created_at", "updated_at")


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def get_contact(db: Session, contact_id: int) -> Contact | None:
    return db.get(Contact, contact_id)


def get_contact_by_email(db: Session, email: str) -> Contact | None:
    stmt = select(Contact).where(func.lower(Contact.email) == _normalize_email(email))
    return db.execute(stmt).scalar_one_or_none()


def count_contacts(db: Session) -> int:
    return db.execute(select(func.count()).select_from(Contact)).scalar_one()


def list_contacts(
    db: Session,
    *,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "id",
    order: str = "asc",
) -> tuple[list[Contact], int]:
    """Return (page of contacts, total matching count)."""
    # selectinload: without it, response serialization would lazy-load
    # `addresses` once per contact — up to 200 extra queries on a full page.
    stmt = select(Contact).options(selectinload(Contact.addresses))

    if search:
        pattern = f"%{search.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Contact.first_name).like(pattern),
                func.lower(Contact.last_name).like(pattern),
                func.lower(Contact.email).like(pattern),
                func.lower(func.coalesce(Contact.company, "")).like(pattern),
                func.lower(func.coalesce(Contact.phone, "")).like(pattern),
            )
        )

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    if sort_by not in SORTABLE_FIELDS:
        sort_by = "id"
    column = getattr(Contact, sort_by)
    # Favorites are always pinned above everything else; the requested sort
    # only decides the order within each of those two groups.
    stmt = stmt.order_by(Contact.is_favorite.desc(), column.desc() if order == "desc" else column.asc())

    items = db.execute(stmt.limit(limit).offset(offset)).scalars().all()
    return list(items), total


def _build_addresses(addresses: list[dict]) -> list[Address]:
    return [Address(**address) for address in addresses]


def create_contact(db: Session, payload: ContactCreate) -> Contact:
    data = payload.model_dump()
    data["email"] = _normalize_email(data["email"])
    addresses = _build_addresses(data.pop("addresses"))
    contact = Contact(**data, addresses=addresses)
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


def _replace_addresses(contact: Contact, addresses: list[dict]) -> None:
    contact.addresses = _build_addresses(addresses)
    # Replacing the relationship only inserts/deletes Address rows — it never
    # touches a Contact column, so the column-level `onupdate` that normally
    # bumps `updated_at` never fires. Set it explicitly so an address-only
    # change is still reflected.
    contact.updated_at = utcnow()


def replace_contact(db: Session, contact: Contact, payload: ContactReplace) -> Contact:
    data = payload.model_dump()
    _replace_addresses(contact, data.pop("addresses"))
    for field, value in data.items():
        setattr(contact, field, _normalize_email(value) if field == "email" else value)
    db.commit()
    db.refresh(contact)
    return contact


def update_contact(db: Session, contact: Contact, payload: ContactUpdate) -> Contact:
    data = payload.model_dump(exclude_unset=True)
    if "addresses" in data:
        _replace_addresses(contact, data.pop("addresses"))
    for field, value in data.items():
        setattr(contact, field, _normalize_email(value) if field == "email" else value)
    db.commit()
    db.refresh(contact)
    return contact


def delete_contact(db: Session, contact: Contact) -> None:
    db.delete(contact)
    db.commit()
