import base64
import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator

from app.models import AddressType

# ~1.5 MB decoded (base64 inflates size by ~4/3), which is generous for a profile
# photo while keeping the in-memory database and JSON payloads bounded.
MAX_PHOTO_DATA_URL_LENGTH = 2_000_000

# Plenty for any real contact, while keeping a single request from creating
# (and a single response from returning) an unbounded number of address rows.
MAX_ADDRESSES_PER_CONTACT = 20

_PHOTO_DATA_URL_PATTERN = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,(?P<payload>.+)$", re.DOTALL)


def _validate_photo_data_url(value: str | None) -> str | None:
    if value is None:
        return None
    match = _PHOTO_DATA_URL_PATTERN.match(value)
    if match is None:
        raise ValueError("photo_url must be a data URL, e.g. data:image/png;base64,...")
    try:
        base64.b64decode(match.group("payload"), validate=True)
    except ValueError as exc:
        raise ValueError("photo_url's base64 payload is not valid") from exc
    return value


class AddressBase(BaseModel):
    """Fields shared by every address request and response."""

    # AddressBase is its own hierarchy, separate from ContactBase — its
    # extra="forbid" doesn't propagate here, so an unknown field nested
    # inside one address entry (e.g. a typo'd "zip" instead of "postal_code")
    # needs the same rejection set explicitly.
    model_config = ConfigDict(extra="forbid")

    type: AddressType = Field(description="Home, Work, or Other.", examples=["Home"])
    address: str | None = Field(
        default=None,
        max_length=300,
        description="Street address, including unit or suite.",
        examples=["1 Market St, Suite 400"],
    )
    city: str | None = Field(default=None, max_length=120, description="City or locality.", examples=["San Francisco"])
    state: str | None = Field(
        default=None,
        max_length=120,
        description="State, province, or region.",
        examples=["CA"],
    )
    postal_code: str | None = Field(
        default=None,
        max_length=20,
        description="Postal or ZIP code.",
        examples=["94105"],
    )
    country: str | None = Field(default=None, max_length=120, description="Country name.", examples=["USA"])


class AddressCreate(AddressBase):
    """One address as submitted within a contact's `addresses` list."""


class AddressRead(AddressBase):
    """A stored address, as returned within a contact."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Server-assigned identifier.", examples=[1])


class ContactBase(BaseModel):
    """Fields shared by every contact request and response."""

    # Rejects unknown fields rather than silently discarding them — a client
    # still sending the old flat address/city/state/postal_code/country
    # fields (from before addresses became a list) gets a clear 422 instead
    # of a 201/200 that quietly drops the address they thought they sent.
    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(
        min_length=1,
        max_length=100,
        description="Given name. Required, must not be blank.",
        examples=["Ada"],
    )
    last_name: str = Field(
        min_length=1,
        max_length=100,
        description="Family name. Required, must not be blank.",
        examples=["Lovelace"],
    )
    email: EmailStr = Field(
        max_length=320,
        description=(
            "Primary email address. Required and unique across all contacts; "
            "compared case-insensitively and stored lowercased."
        ),
        examples=["ada@example.com"],
    )
    phone: str | None = Field(
        default=None,
        max_length=40,
        description="Phone number. Stored verbatim — any format is accepted.",
        examples=["+1-415-555-0101"],
    )
    photo_url: str | None = Field(
        default=None,
        max_length=MAX_PHOTO_DATA_URL_LENGTH,
        description=(
            "Contact photo as a data URL (e.g. `data:image/png;base64,...`). "
            "No external file storage — the image is stored and returned verbatim."
        ),
        examples=[None],
    )
    company: str | None = Field(
        default=None,
        max_length=200,
        description="Employer or organisation name.",
        examples=["Analytical Engines"],
    )
    job_title: str | None = Field(
        default=None,
        max_length=200,
        description="Role held at the company.",
        examples=["Mathematician"],
    )
    addresses: list[AddressCreate] = Field(
        default_factory=list,
        max_length=MAX_ADDRESSES_PER_CONTACT,
        description="The contact's addresses. Each has its own `type` (Home, Work, or Other).",
    )
    notes: str | None = Field(
        default=None,
        description="Free-form notes about the contact. No length limit.",
        examples=["Met at the SF hackathon."],
    )


class _PhotoWriteValidation(BaseModel):
    """
    Mixin applied only to the write schemas (Create/Replace/Update).

    `ContactRead` deliberately does *not* include this: values already in the
    database were validated on the way in, so re-decoding base64 on every read
    — including all 200 items a single list page can return — would be pure
    waste.
    """

    # check_fields=False: this mixin declares no fields of its own — photo_url
    # comes from whichever concrete model combines it with `ContactBase`.
    @field_validator("photo_url", check_fields=False)
    @classmethod
    def _check_photo_url(cls, value: str | None) -> str | None:
        return _validate_photo_data_url(value)


_FULL_EXAMPLE = {
    "first_name": "Ada",
    "last_name": "Lovelace",
    "email": "ada@example.com",
    "phone": "+1-415-555-0101",
    "company": "Analytical Engines",
    "job_title": "Mathematician",
    "addresses": [
        {
            "type": "Home",
            "address": "1 Market St, Suite 400",
            "city": "San Francisco",
            "state": "CA",
            "postal_code": "94105",
            "country": "USA",
        }
    ],
    "notes": "Met at the SF hackathon.",
}
_MINIMAL_EXAMPLE = {"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"}


class ContactCreate(ContactBase, _PhotoWriteValidation):
    """Body of `POST /api/v1/contacts`. Only the two names and email are required."""

    model_config = ConfigDict(json_schema_extra={"examples": [_FULL_EXAMPLE, _MINIMAL_EXAMPLE]})


class ContactReplace(ContactBase, _PhotoWriteValidation):
    """
    Body of `PUT /api/v1/contacts/{contact_id}`.

    This is a full replacement: any optional field you omit is set back to `null`.
    Use `PATCH` if you only want to change some fields.
    """

    model_config = ConfigDict(json_schema_extra={"examples": [_FULL_EXAMPLE]})


class ContactUpdate(BaseModel):
    """
    Body of `PATCH /api/v1/contacts/{contact_id}`.

    Every field is optional. Only the fields actually present in the request are
    written; omitted fields keep their current value. Sending an explicit `null`
    clears that field.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"phone": "+1-415-555-0199", "job_title": "Chief Engineer"}]},
    )

    first_name: str | None = Field(default=None, min_length=1, max_length=100, description="New given name.")
    last_name: str | None = Field(default=None, min_length=1, max_length=100, description="New family name.")
    email: EmailStr | None = Field(
        default=None,
        max_length=320,
        description="New email address. Must not belong to another contact.",
    )
    phone: str | None = Field(default=None, max_length=40, description="New phone number.")
    photo_url: str | None = Field(
        default=None,
        max_length=MAX_PHOTO_DATA_URL_LENGTH,
        description="New contact photo as a data URL. Send `null` to remove the existing photo.",
    )
    company: str | None = Field(default=None, max_length=200, description="New company.")
    job_title: str | None = Field(default=None, max_length=200, description="New job title.")
    addresses: list[AddressCreate] | None = Field(
        default=None,
        max_length=MAX_ADDRESSES_PER_CONTACT,
        description=(
            "Replace the contact's entire address list. Omit to leave addresses "
            "unchanged; send an empty list to clear them. `null` is invalid — "
            "use `[]` to clear."
        ),
    )
    notes: str | None = Field(default=None, description="New notes; replaces the existing text.")
    is_favorite: bool | None = Field(
        default=None,
        description=(
            "Favorite this contact, or unfavorite it. This is the only way to "
            "change it — POST and PUT don't accept it, so replacing a contact's "
            "other fields can never silently clear its favorite status."
        ),
    )

    @field_validator("photo_url")
    @classmethod
    def _check_photo_url(cls, value: str | None) -> str | None:
        return _validate_photo_data_url(value)

    @field_validator("addresses")
    @classmethod
    def _reject_null_addresses(cls, value: list[AddressCreate] | None) -> list[AddressCreate]:
        # Only runs when the client actually sends the key (Pydantic skips
        # "after" validators on an omitted field's default), so this can't
        # block the omit-to-leave-unchanged case — only an explicit `null`.
        if value is None:
            raise ValueError("addresses cannot be null — omit it to leave unchanged, or send [] to clear it")
        return value

    @field_validator("is_favorite")
    @classmethod
    def _reject_null_favorite(cls, value: bool | None) -> bool:
        # Same reasoning as addresses: only runs when the client actually
        # sends the key, so omitting it to leave it unchanged still works.
        # There's no sensible "clear to null" for a boolean flag.
        if value is None:
            raise ValueError("is_favorite cannot be null — omit it to leave unchanged, or send true/false")
        return value


class ContactRead(ContactBase):
    """A stored contact, as returned by every contact endpoint."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    **_FULL_EXAMPLE,
                    "addresses": [{**_FULL_EXAMPLE["addresses"][0], "id": 1}],
                    "id": 1,
                    "is_favorite": False,
                    "full_name": "Ada Lovelace",
                    "created_at": "2026-08-19T16:22:58.189507Z",
                    "updated_at": "2026-08-19T16:22:58.189511Z",
                }
            ]
        },
    )

    id: int = Field(description="Server-assigned identifier.", examples=[1])
    addresses: list[AddressRead] = Field(description="The contact's stored addresses, each with its own id.")
    is_favorite: bool = Field(
        description="Whether this contact is favorited. Favorited contacts are always listed first.",
        examples=[False],
    )
    created_at: datetime = Field(
        description="UTC timestamp of when the contact was created.",
        examples=["2026-08-19T16:22:58.189507Z"],
    )
    updated_at: datetime = Field(
        description="UTC timestamp of the last modification.",
        examples=["2026-08-19T16:22:58.189511Z"],
    )

    @field_validator("created_at", "updated_at")
    @classmethod
    def _as_utc(cls, value: datetime) -> datetime:
        # SQLite discards tzinfo on write; the stored values are UTC, so label
        # them as such rather than emitting an ambiguous naive timestamp.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    @computed_field(description="Convenience concatenation of first and last name.", examples=["Ada Lovelace"])
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class ContactPage(BaseModel):
    """One page of contacts plus the totals a client needs to paginate."""

    items: list[ContactRead] = Field(description="Contacts on this page, ordered by the requested sort.")
    total: int = Field(
        description="Total contacts matching the query, ignoring `limit` and `offset`.",
        examples=[42],
    )
    limit: int = Field(description="Page size that was applied.", examples=[50])
    offset: int = Field(description="Number of records skipped.", examples=[0])


class HealthResponse(BaseModel):
    """Result of the liveness probe."""

    status: str = Field(description="Always `ok` when the service can serve traffic.", examples=["ok"])
    database: str = Field(description="Active SQLAlchemy dialect.", examples=["sqlite"])
    contacts: int = Field(description="Number of contacts currently stored.", examples=[3])


class RootResponse(BaseModel):
    """Discovery document listing the API's entry points."""

    name: str = Field(description="Human-readable service name.", examples=["Contacts API"])
    version: str = Field(description="Service version.", examples=["0.1.0"])
    docs: str = Field(description="Path to the Swagger UI.", examples=["/docs"])
    redoc: str = Field(description="Path to the ReDoc UI.", examples=["/redoc"])
    openapi: str = Field(description="Path to the OpenAPI 3.1 document.", examples=["/openapi.json"])
    contacts: str = Field(description="Base path of the contacts collection.", examples=["/api/v1/contacts"])
    health: str = Field(description="Path to the liveness probe.", examples=["/health"])


class ErrorResponse(BaseModel):
    """Shape of every non-validation error returned by the API."""

    detail: str = Field(
        description="Human-readable explanation of the failure.",
        examples=["Contact 42 not found"],
    )
