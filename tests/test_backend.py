from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from bson import ObjectId

from db import DomainError, object_id, utcnow
from seed import seed


def write(client, method, path, data=None):
    token = client.get("/api/auth/csrf").json["csrf_token"]
    return client.open(path, method=method, json=data, headers={"X-CSRFToken": token})


def register(app, email="owner@example.test"):
    client = app.test_client()
    response = write(client, "POST", "/api/auth/register", {
        "name": "Test Student", "email": email, "password": "test-password-123",
    })
    assert response.status_code == 201, response.json
    return client, object_id(response.json["user"]["_id"])


def payload(**changes):
    start = utcnow() + timedelta(days=2)
    return {
        "course": "CSCI-UA 480", "topic": "MongoDB study group", "session_type": "in_person",
        "location": "Bobst Library", "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=1)).isoformat(), **changes,
    }


def create(client, **changes):
    response = write(client, "POST", "/api/sessions", payload(**changes))
    assert response.status_code == 201, response.json
    return response.json["session"]


def test_auth_csrf_and_unique_email(app, store):
    client = app.test_client()
    assert client.post("/api/auth/register", json={}).status_code == 400
    assert client.get("/api/auth/me").status_code == 401
    owner, user_id = register(app)
    assert "password_hash" not in owner.get("/api/auth/me").json["user"]
    assert store.users.find_one({"_id": user_id})["password_hash"] != "test-password-123"
    duplicate = write(client, "POST", "/api/auth/register", {
        "name": "Other", "email": "OWNER@EXAMPLE.TEST", "password": "test-password-123",
    })
    assert duplicate.status_code == 409
    assert write(owner, "POST", "/api/auth/logout").status_code == 204
    assert owner.get("/api/auth/me").status_code == 401
    assert write(owner, "POST", "/api/auth/login", {
        "email": "owner@example.test", "password": "wrong-password",
    }).status_code == 401
    assert write(owner, "POST", "/api/auth/login", {
        "email": "OWNER@EXAMPLE.TEST", "password": "test-password-123",
    }).status_code == 200


def test_create_browse_detail_search_and_permissions(app):
    owner, owner_id = register(app)
    member, _ = register(app, "member@example.test")
    document = create(owner)
    sid = document["_id"]
    assert document["participant_ids"] == [str(owner_id)]
    assert document["min_participants"] == 2
    assert document["max_participants"] == 8
    assert document["participant_count"] == 1
    assert len(owner.get("/api/sessions?course=csci&topic=mongo").json["sessions"]) == 1
    assert owner.get("/api/sessions?topic=.*").json["sessions"] == []
    assert len(owner.get("/api/sessions?mine=true").json["sessions"]) == 1
    assert member.get("/api/sessions?mine=true").json["sessions"] == []
    detail = owner.get(f"/api/sessions/{sid}").json["session"]
    assert detail["participants"] == [{"_id": str(owner_id), "name": "Test Student"}]
    assert write(member, "PATCH", f"/api/sessions/{sid}", {"topic": "Stolen"}).status_code == 403
    assert write(member, "DELETE", f"/api/sessions/{sid}").status_code == 403
    assert write(owner, "PATCH", f"/api/sessions/{sid}", {"topic": "Updated topic"}).status_code == 200
    assert write(owner, "DELETE", f"/api/sessions/{sid}").status_code == 204
    assert owner.get(f"/api/sessions/{sid}").status_code == 404
def test_similar_session_time_filter(app):
    owner, _ = register(app)

    # Create an existing study session.
    session = create(owner)

    # Use the session's actual start time.
    from datetime import datetime, timedelta, timezone

    start = datetime.fromisoformat(
        session["start_at"].replace("Z", "+00:00")
    )

    # Search within one hour of its start time.
    params = {
        "course": session["course"],
        "available": "true",
        "start_from": (start - timedelta(hours=1)).isoformat(),
        "start_to": (start + timedelta(hours=1)).isoformat(),
    }

    response = owner.get("/api/sessions", query_string=params)

    assert response.status_code == 200
    assert any(
        s["_id"] == session["_id"]
        for s in response.json["sessions"]
    )

    # Search a time window that excludes the session.
    params["start_from"] = (
        start + timedelta(hours=2)
    ).isoformat()
    params["start_to"] = (
        start + timedelta(hours=3)
    ).isoformat()

    response = owner.get("/api/sessions", query_string=params)

    assert response.status_code == 200
    assert all(
        s["_id"] != session["_id"]
        for s in response.json["sessions"]
    )

    # An invalid time range should be rejected.
    params["start_to"] = params["start_from"]

    response = owner.get("/api/sessions", query_string=params)

    assert response.status_code == 400


@pytest.mark.parametrize("changes", [
    {"min_participants": 1}, {"max_participants": 41},
    {"min_participants": 15, "max_participants": 10}, {"max_participants": True},
    {"max_participants": "40"}, {"start_at": "2020-01-01T10:00:00Z"},
    {"start_at": "2030-01-01T10:00:00"}, {"end_at": "2020-01-01T10:00:00Z"},
    {"session_type": "virtual", "meeting_url": "javascript:alert(1)"},
    {"location": ""}, {"participant_ids": []}, {"registration_deadline": "2030-01-01"},
])
def test_invalid_session_rejected(app, changes):
    client, _ = register(app)
    response = write(client, "POST", "/api/sessions", payload(**changes))
    assert response.status_code == 400, response.json


def test_membership_capacity_and_status_state_machine(app, store):
    owner, _ = register(app)
    member, _ = register(app, "member@example.test")
    third, _ = register(app, "third@example.test")
    document = create(owner, min_participants=2, max_participants=2)
    sid = document["_id"]
    assert document["status"] == "waiting"
    # Reaching the minimum before the deadline flips the session to confirmed.
    joined = write(member, "POST", f"/api/sessions/{sid}/join")
    assert joined.status_code == 200
    assert joined.json["session"]["status"] == "confirmed"
    assert len(member.get("/api/sessions?mine=true").json["sessions"]) == 1
    assert write(member, "POST", f"/api/sessions/{sid}/join").status_code == 409
    assert write(third, "POST", f"/api/sessions/{sid}/join").status_code == 409
    assert write(owner, "POST", f"/api/sessions/{sid}/leave").status_code == 409
    # Dropping below the minimum before the deadline switches back to waiting.
    left = write(member, "POST", f"/api/sessions/{sid}/leave")
    assert left.status_code == 200
    assert left.json["session"]["status"] == "waiting"
    assert write(third, "POST", f"/api/sessions/{sid}/join").status_code == 200
    # The registration deadline is start_at; move it into the past.
    store.sessions.update_one({"_id": object_id(sid)},
                              {"$set": {"start_at": utcnow() - timedelta(seconds=1)}})
    assert write(member, "POST", f"/api/sessions/{sid}/join").status_code == 409
    assert write(owner, "PATCH", f"/api/sessions/{sid}", {"topic": "Too late"}).status_code == 409
    # The session confirmed inline before the deadline, so cleanup settles nothing.
    assert store.cleanup_expired() == {"closed": 0, "confirmed": 0}
    assert store.get_session(sid)["status"] == "confirmed"
    # Leaving after the deadline below the minimum closes the session but keeps it.
    left = write(third, "POST", f"/api/sessions/{sid}/leave")
    assert left.status_code == 200
    assert left.json["session"]["status"] == "closed"
    assert store.get_session(sid)["status"] == "closed"


def test_deadline_is_start_time_and_capacity_not_shrunk_below_members(app, store):
    owner, _ = register(app)
    member, _ = register(app, "member@example.test")
    third, _ = register(app, "third@example.test")
    start = utcnow() + timedelta(minutes=10)
    document = create(owner, min_participants=2, max_participants=3,
                      start_at=start.isoformat(), end_at=(start + timedelta(hours=1)).isoformat())
    assert "registration_deadline" not in document
    assert write(owner, "POST", "/api/sessions",
                 {k: v for k, v in payload().items() if k != "start_at"}).status_code == 400
    sid = document["_id"]
    assert write(member, "POST", f"/api/sessions/{sid}/join").status_code == 200
    assert write(third, "POST", f"/api/sessions/{sid}/join").status_code == 200
    assert write(owner, "PATCH", f"/api/sessions/{sid}", {"max_participants": 2}).status_code == 409


def test_atomic_race_for_last_seat(app, store):
    owner, owner_id = register(app)
    document = create(owner, min_participants=2, max_participants=2)
    # Model requests handled by separate worker clients, all targeting the same MongoDB document.
    def attempt(_):
        from db import Store
        worker = Store(app.config["MONGO_URI"], app.config["MONGO_DB_NAME"])
        try:
            worker.join_session(document["_id"], ObjectId())
            return True
        except DomainError as error:
            assert error.status == 409
            return False
        finally:
            worker.close()
    with ThreadPoolExecutor(max_workers=12) as executor:
        successes = list(executor.map(attempt, range(24)))
    assert sum(successes) == 1
    saved = store.get_session(document["_id"])
    assert len(saved["participant_ids"]) == 2
    assert owner_id in saved["participant_ids"]


def test_concurrent_duplicate_joins(app, store):
    owner, _ = register(app)
    document = create(owner)
    member = ObjectId()
    def attempt(_):
        try:
            store.join_session(document["_id"], member)
            return True
        except DomainError:
            return False
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(16))) == 1
    assert store.get_session(document["_id"])["participant_ids"].count(member) == 1


def test_cleanup_closes_underfilled_and_confirms_filled_sessions(app, store):
    owner, _ = register(app)
    underfilled = create(owner)
    sufficient = create(owner, min_participants=2)
    future = create(owner)
    store.join_session(sufficient["_id"], ObjectId())
    # Backdate both deadlines; reset "sufficient" to waiting so the sweep settles it.
    store.sessions.update_many(
        {"_id": {"$in": [object_id(underfilled["_id"]), object_id(sufficient["_id"])]}},
        {"$set": {"start_at": utcnow() - timedelta(seconds=1), "status": "waiting"}},
    )
    assert store.cleanup_expired() == {"closed": 1, "confirmed": 1}
    assert store.get_session(underfilled["_id"])["status"] == "closed"
    assert store.get_session(sufficient["_id"])["status"] == "confirmed"
    assert store.get_session(future["_id"])["status"] == "waiting"
    assert store.cleanup_expired() == {"closed": 0, "confirmed": 0}


def test_seed_is_repeatable_and_preserves_edits(store):
    assert seed(store) == 4
    document = store.sessions.find_one({})
    store.sessions.update_one({"_id": document["_id"]}, {"$set": {"topic": "Student edit"}})
    assert seed(store) == 0
    assert store.sessions.count_documents({}) == 4
    assert store.users.count_documents({}) == 1
    assert store.get_session(document["_id"])["topic"] == "Student edit"


def test_virtual_session_and_invalid_search_inputs(app):
    owner, _ = register(app)
    document = create(owner, session_type="virtual", meeting_url="https://example.com/meeting")
    assert document["location"] is None
    assert document["meeting_url"] == "https://example.com/meeting"
    public = app.test_client()
    listed = public.get("/api/sessions?session_type=virtual").json["sessions"]
    assert len(listed) == 1
    assert "meeting_url" not in listed[0]
    assert public.get(f"/api/sessions/{document['_id']}").status_code == 401
    for query in ("date=bad", "date=9999-12-31", "page=0", "limit=101", "limit=no", "mine=yes"):
        assert public.get("/api/sessions?" + query).status_code == 400

def test_delete_requires_confirmation(app):
    owner, _ = register(app)
    document = create(owner)
    session_id = document["_id"]
    url = f"/sessions/{session_id}/delete"

    # Without confirmation, deletion must be rejected.
    response = write(owner, "POST", url)
    assert response.status_code == 302
    assert owner.get(f"/api/sessions/{session_id}").status_code == 200

    # With confirmation, deletion succeeds.
    token = owner.get("/api/auth/csrf").json["csrf_token"]
    response = owner.post(
        url,
        data={"confirm_delete": "yes"},
        headers={"X-CSRFToken": token},
    )
    assert response.status_code == 302
    assert owner.get(f"/api/sessions/{session_id}").status_code == 404
    
def test_cancel_session(app, store):
    owner, owner_id = register(app)
    member, _ = register(app, "member@example.test")

    document = create(owner)
    session_id = document["_id"]
    cancel_url = f"/api/sessions/{session_id}/cancel"

    # Only the organizer can cancel.
    response = write(member, "POST", cancel_url)
    assert response.status_code == 403

    # The organizer can cancel successfully.
    response = write(owner, "POST", cancel_url)
    assert response.status_code == 200
    assert response.json["session"]["status"] == "cancelled"
    assert response.json["session"]["display_status"] == "cancelled"
    assert response.json["session"]["registration_open"] is False

    # The cancelled session remains in the database.
    saved = store.get_session(session_id)
    assert saved["status"] == "cancelled"
    assert saved["participant_ids"] == [owner_id]

    # Nobody can join a cancelled session.
    response = write(member, "POST", f"/api/sessions/{session_id}/join")
    assert response.status_code == 409

    # Cancelling the same session again is rejected.
    response = write(owner, "POST", cancel_url)
    assert response.status_code == 409

    # A cancelled session should still display Cancelled after its end time.
    from datetime import timedelta
    from db import public_session, utcnow

    past_session = dict(saved)
    past_session["end_at"] = utcnow() - timedelta(hours=1)

    assert public_session(past_session)["display_status"] == "cancelled"