import re
from html import unescape

import pytest
from werkzeug.security import check_password_hash


PASSWORD = "StudyTest2026!"


def submit_form(client, page, data):
    """Load the real form and submit it with its CSRF token."""
    response = client.get(page)
    assert response.status_code == 200

    match = re.search(
        r'name="csrf_token"\s+value="([^"]+)"',
        response.get_data(as_text=True),
    )
    assert match, "The form is missing its CSRF token."

    return client.post(
        page,
        data={
            **data,
            "csrf_token": unescape(match.group(1)),
        },
    )


def signup(client, **changes):
    data = {
        "name": "Test Student",
        "email": "student@example.test",
        "password": PASSWORD,
        "confirm_password": PASSWORD,
    }
    data.update(changes)
    return submit_form(client, "/signup", data)


def create_account(store):
    return store.create_user({
        "name": "Test Student",
        "email": "student@example.test",
        "password": PASSWORD,
    })


def test_signup_creates_account_and_logs_in(app, store):
    client = app.test_client()

    response = signup(
        client,
        name="  Test Student  ",
        email="  STUDENT@example.test  ",
    )

    assert response.status_code == 303
    assert response.headers["Location"] == "/"

    user = store.users.find_one({"email": "student@example.test"})
    assert user is not None
    assert user["name"] == "Test Student"
    assert user["password_hash"] != PASSWORD
    assert check_password_hash(user["password_hash"], PASSWORD)
    assert "password" not in user
    assert "confirm_password" not in user

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json["user"]["email"] == "student@example.test"
    assert "password_hash" not in me.json["user"]


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"name": "   "}, "name must contain"),
        ({"email": "not-an-email"}, "Enter a valid email address."),
        (
            {"password": "short", "confirm_password": "short"},
            "Password must contain",
        ),
        (
            {"password": "x" * 129, "confirm_password": "x" * 129},
            "Password must contain",
        ),
        (
            {"confirm_password": "DifferentPassword2026!"},
            "Passwords do not match.",
        ),
    ],
)
def test_invalid_signup_does_not_create_account(
    app, store, changes, message
):
    client = app.test_client()
    response = signup(client, **changes)

    assert response.status_code == 400
    assert message in response.get_data(as_text=True)
    assert store.users.count_documents({}) == 0
    assert client.get("/api/auth/me").status_code == 401

    # Passwords must never be filled back into the form.
    assert f'value="{PASSWORD}"' not in response.get_data(as_text=True)


def test_duplicate_email_is_rejected(app, store):
    create_account(store)
    client = app.test_client()

    response = signup(client, email="STUDENT@example.test")

    assert response.status_code == 409
    assert "Email is already registered." in response.get_data(as_text=True)
    assert store.users.count_documents({}) == 1
    assert client.get("/api/auth/me").status_code == 401


def test_login_and_logout(app, store):
    create_account(store)
    client = app.test_client()

    response = submit_form(client, "/login", {
        "email": "STUDENT@example.test",
        "password": PASSWORD,
    })

    assert response.status_code == 303
    assert response.headers["Location"] == "/"
    assert client.get("/api/auth/me").status_code == 200

    # Fetch the logout token from the rendered navigation.
    home = client.get("/")
    match = re.search(
        r'name="csrf_token"\s+value="([^"]+)"',
        home.get_data(as_text=True),
    )
    assert match, "The logout form is missing its CSRF token."

    response = client.post("/logout", data={
        "csrf_token": unescape(match.group(1)),
    })

    assert response.status_code == 303
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/sessions/new").status_code == 302


@pytest.mark.parametrize(
    "email, password",
    [
        ("student@example.test", "WrongPassword2026!"),
        ("unknown@example.test", PASSWORD),
        ("student@example.test", ""),
    ],
)
def test_invalid_login_shows_generic_error(app, store, email, password):
    create_account(store)
    client = app.test_client()

    response = submit_form(client, "/login", {
        "email": email,
        "password": password,
    })

    assert response.status_code == 401
    assert "Invalid email or password." in response.get_data(as_text=True)
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    "destination",
    [
        "/sessions/new",
        "/sessions/000000000000000000000101",
    ],
)
def test_login_returns_to_requested_page(app, store, destination):
    create_account(store)
    client = app.test_client()

    protected = client.get(destination)
    assert protected.status_code == 302
    login_url = protected.headers["Location"]
    assert login_url.startswith("/login?")

    response = submit_form(client, login_url, {
        "email": "student@example.test",
        "password": PASSWORD,
        "next": destination,
    })

    assert response.status_code == 303
    assert response.headers["Location"] == destination
    assert client.get("/api/auth/me").status_code == 200


@pytest.mark.parametrize(
    "destination",
    [
        "https://example.com",
        "//example.com",
        "/\\example.com",
        "/not-an-allowed-page",
    ],
)
def test_login_rejects_unsafe_or_unknown_destinations(
    app, store, destination
):
    create_account(store)
    client = app.test_client()

    response = submit_form(client, "/login", {
        "email": "student@example.test",
        "password": PASSWORD,
        "next": destination,
    })

    assert response.status_code == 303
    assert response.headers["Location"] == "/"


@pytest.mark.parametrize("page", ["/signup", "/login"])
def test_signed_in_users_skip_authentication_forms(app, store, page):
    client = app.test_client()
    assert signup(client).status_code == 303

    response = client.get(page)

    assert response.status_code == 302
    assert response.headers["Location"] == "/"


@pytest.mark.parametrize("page", ["/signup", "/login", "/logout"])
def test_forms_require_csrf_token(app, store, page):
    client = app.test_client()

    # Establish a logged-in session so the logout check is meaningful.
    assert signup(client).status_code == 303
    assert app.config.get("WTF_CSRF_ENABLED", True)

    response = client.post(page, data={
        "name": "Another Student",
        "email": "another@example.test",
        "password": PASSWORD,
        "confirm_password": PASSWORD,
    })

    assert response.status_code == 400
    assert store.users.count_documents({}) == 1
    assert client.get("/api/auth/me").status_code == 200