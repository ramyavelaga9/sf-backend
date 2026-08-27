from sqlalchemy import select

from app.database import SessionLocal
from app.models import Address, Contact

BASE = "/api/v1/contacts"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "sqlite"


def test_create_contact(client, payload):
    response = client.post(BASE, json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["email"] == "ada@example.com"
    assert body["full_name"] == "Ada Lovelace"
    assert body["created_at"] and body["updated_at"]


def test_create_requires_valid_email(client, payload):
    response = client.post(BASE, json={**payload, "email": "not-an-email"})
    assert response.status_code == 422


def test_create_requires_names(client, payload):
    response = client.post(BASE, json={**payload, "first_name": ""})
    assert response.status_code == 422


def test_duplicate_email_conflicts(client, payload):
    assert client.post(BASE, json=payload).status_code == 201
    response = client.post(BASE, json={**payload, "email": "ADA@example.com"})
    assert response.status_code == 409


def test_create_contact_without_photo_defaults_to_none(client, payload):
    response = client.post(BASE, json=payload)
    assert response.json()["photo_url"] is None


def test_create_contact_with_photo(client, payload):
    photo = "data:image/png;base64,aGVsbG8="
    response = client.post(BASE, json={**payload, "photo_url": photo})
    assert response.status_code == 201
    assert response.json()["photo_url"] == photo


def test_photo_url_must_be_a_data_url(client, payload):
    response = client.post(BASE, json={**payload, "photo_url": "not-a-photo"})
    assert response.status_code == 422


def test_photo_url_requires_the_base64_marker(client, payload):
    response = client.post(BASE, json={**payload, "photo_url": "data:image/png,plain text"})
    assert response.status_code == 422


def test_photo_url_rejects_invalid_base64_payload(client, payload):
    response = client.post(BASE, json={**payload, "photo_url": "data:image/png;base64,!!!!"})
    assert response.status_code == 422


def test_photo_url_rejects_oversized_payload(client, payload):
    oversized = "data:image/png;base64," + "a" * 2_000_000
    response = client.post(BASE, json={**payload, "photo_url": oversized})
    assert response.status_code == 422


def test_put_omitting_photo_clears_it(client, payload):
    photo = "data:image/png;base64,aGVsbG8="
    contact_id = client.post(BASE, json={**payload, "photo_url": photo}).json()["id"]

    response = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"},
    )
    assert response.status_code == 200
    assert response.json()["photo_url"] is None  # PUT is a full replace


def test_patch_leaves_photo_untouched_when_omitted(client, payload):
    photo = "data:image/png;base64,aGVsbG8="
    contact_id = client.post(BASE, json={**payload, "photo_url": photo}).json()["id"]

    response = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"})
    assert response.status_code == 200
    assert response.json()["photo_url"] == photo


def test_reading_does_not_revalidate_a_stored_photo(client, payload):
    # A row already in the database (written before validation existed, or by
    # another process) bypasses request-side validation entirely. Reads must
    # still serve it rather than re-decoding — and rejecting — trusted data.
    with SessionLocal() as db:
        contact = Contact(
            **{k: v for k, v in payload.items() if k != "addresses"},
            photo_url="not-a-valid-data-url",
        )
        db.add(contact)
        db.commit()
        contact_id = contact.id

    response = client.get(f"{BASE}/{contact_id}")
    assert response.status_code == 200
    assert response.json()["photo_url"] == "not-a-valid-data-url"


def test_patch_null_removes_photo(client, payload):
    photo = "data:image/png;base64,aGVsbG8="
    contact_id = client.post(BASE, json={**payload, "photo_url": photo}).json()["id"]

    response = client.patch(f"{BASE}/{contact_id}", json={"photo_url": None})
    assert response.status_code == 200
    assert response.json()["photo_url"] is None


def test_get_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.get(f"{BASE}/{contact_id}")
    assert response.status_code == 200
    assert response.json()["id"] == contact_id


def test_get_missing_contact_returns_404(client):
    assert client.get(f"{BASE}/9999").status_code == 404


def test_list_pagination_and_total(client, payload):
    for index in range(5):
        client.post(BASE, json={**payload, "email": f"user{index}@example.com"})

    response = client.get(BASE, params={"limit": 2, "offset": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2 and body["offset"] == 2


def test_list_search(client, payload):
    client.post(BASE, json=payload)
    client.post(
        BASE,
        json={**payload, "first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com", "company": "US Navy"},
    )

    hits = client.get(BASE, params={"search": "hopper"}).json()
    assert hits["total"] == 1
    assert hits["items"][0]["last_name"] == "Hopper"

    by_company = client.get(BASE, params={"search": "navy"}).json()
    assert by_company["total"] == 1

    misses = client.get(BASE, params={"search": "nobody"}).json()
    assert misses["total"] == 0


def test_list_sorting(client, payload):
    client.post(BASE, json={**payload, "last_name": "Zhang", "email": "z@example.com"})
    client.post(BASE, json={**payload, "last_name": "Adams", "email": "a@example.com"})

    names = [
        item["last_name"]
        for item in client.get(BASE, params={"sort_by": "last_name", "order": "asc"}).json()["items"]
    ]
    assert names == ["Adams", "Zhang"]


def test_list_rejects_bad_sort_field(client):
    assert client.get(BASE, params={"sort_by": "; DROP TABLE contacts"}).status_code == 422


def test_patch_updates_only_sent_fields(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"})
    assert response.status_code == 200
    body = response.json()
    assert body["phone"] == "+1-000-000-0000"
    assert body["first_name"] == "Ada"
    assert body["company"] == "Analytical Engines"


def test_patch_duplicate_email_conflicts(client, payload):
    first = client.post(BASE, json=payload).json()["id"]
    client.post(BASE, json={**payload, "email": "grace@example.com"})
    response = client.patch(f"{BASE}/{first}", json={"email": "grace@example.com"})
    assert response.status_code == 409


def test_patch_same_email_is_allowed(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"email": payload["email"]})
    assert response.status_code == 200


def test_put_replaces_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Grace Hopper"
    assert body["company"] is None  # omitted fields are cleared by PUT


def test_put_missing_contact_returns_404(client):
    response = client.put(
        f"{BASE}/9999",
        json={"first_name": "A", "last_name": "B", "email": "ab@example.com"},
    )
    assert response.status_code == 404


def test_delete_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    assert client.delete(f"{BASE}/{contact_id}").status_code == 204
    assert client.get(f"{BASE}/{contact_id}").status_code == 404
    assert client.delete(f"{BASE}/{contact_id}").status_code == 404


def test_root_lists_entrypoints(client):
    body = client.get("/").json()
    assert body["contacts"] == BASE


def test_create_contact_with_multiple_addresses(client, payload):
    response = client.post(
        BASE,
        json={
            **payload,
            "addresses": [
                {"type": "Home", "city": "San Francisco", "state": "CA", "country": "USA"},
                {"type": "Work", "city": "New York", "state": "NY", "country": "USA"},
            ],
        },
    )
    assert response.status_code == 201
    addresses = response.json()["addresses"]
    assert {a["type"] for a in addresses} == {"Home", "Work"}
    assert all(a["id"] > 0 for a in addresses)


def test_create_contact_with_no_addresses(client, payload):
    response = client.post(BASE, json={**payload, "addresses": []})
    assert response.status_code == 201
    assert response.json()["addresses"] == []


def test_create_rejects_an_unknown_address_type(client, payload):
    response = client.post(BASE, json={**payload, "addresses": [{"type": "Vacation", "city": "Reno"}]})
    assert response.status_code == 422


def test_put_replaces_the_whole_address_list(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]

    response = client.put(
        f"{BASE}/{contact_id}",
        json={
            "first_name": "Ada",
            "last_name": "Lovelace",
            "email": "ada@example.com",
            "addresses": [{"type": "Other", "city": "Reno"}],
        },
    )
    assert response.status_code == 200
    addresses = response.json()["addresses"]
    assert len(addresses) == 1
    assert addresses[0]["type"] == "Other" and addresses[0]["city"] == "Reno"


def test_patch_without_addresses_key_leaves_them_untouched(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]

    response = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"})
    assert response.status_code == 200
    assert len(response.json()["addresses"]) == 1


def test_patch_with_an_empty_address_list_clears_it(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]

    response = client.patch(f"{BASE}/{contact_id}", json={"addresses": []})
    assert response.status_code == 200
    assert response.json()["addresses"] == []


def test_deleting_a_contact_cascades_to_its_addresses(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]

    with SessionLocal() as db:
        stmt = select(Address).where(Address.contact_id == contact_id)
        assert len(db.execute(stmt).scalars().all()) == 1

    assert client.delete(f"{BASE}/{contact_id}").status_code == 204

    with SessionLocal() as db:
        stmt = select(Address).where(Address.contact_id == contact_id)
        assert db.execute(stmt).scalars().all() == []
