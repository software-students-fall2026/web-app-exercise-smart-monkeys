"""MongoDB access and session rules shared by HTTP and cleanup processes."""

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
from werkzeug.security import generate_password_hash, check_password_hash


class DomainError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def utcnow():
    return datetime.now(timezone.utc)


def object_id(value):
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError) as exc:
        raise DomainError("Invalid ID.") from exc


def text_field(data, name, maximum=200):
    value = data.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise DomainError(f"{name} must contain 1–{maximum} characters.")
    return value.strip()


def parse_time(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise DomainError("Use an ISO 8601 date/time with a timezone.") from exc
    else:
        raise DomainError("Use an ISO 8601 date/time with a timezone.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DomainError("Date/time must include a timezone, for example -04:00 or Z.")
    return parsed.astimezone(timezone.utc)


SESSION_FIELDS = {
    "course", "topic", "start_at", "end_at", "session_type", "location",
    "meeting_url", "min_participants", "max_participants",
}


def validate_session(data, settings, now):
    result = {name: text_field(data, name) for name in ("course", "topic")}
    result["start_at"] = parse_time(data.get("start_at"))
    result["end_at"] = parse_time(data.get("end_at"))
    if result["start_at"] <= now or result["end_at"] <= result["start_at"]:
        raise DomainError("Start must be in the future and end must be after start.")

    kind = data.get("session_type")
    if kind not in ("in_person", "virtual"):
        raise DomainError("session_type must be in_person or virtual.")
    result.update(session_type=kind, location=None, meeting_url=None)
    if kind == "in_person":
        result["location"] = text_field(data, "location", 500)
    else:
        url = text_field(data, "meeting_url", 1000)
        try:
            parsed = urlparse(url)
            valid = parsed.scheme in ("https", "http") and bool(parsed.hostname)
        except ValueError:
            valid = False
        if not valid:
            raise DomainError("meeting_url must be an HTTP or HTTPS URL.")
        result["meeting_url"] = url

    minimum = data.get("min_participants", settings["DEFAULT_MIN_PARTICIPANTS"])
    maximum = data.get("max_participants", settings["DEFAULT_MAX_PARTICIPANTS"])
    if type(minimum) is not int or type(maximum) is not int:
        raise DomainError("Participant limits must be integers.")
    lower, upper = settings["MIN_ALLOWED_PARTICIPANTS"], settings["MAX_ALLOWED_PARTICIPANTS"]
    if not lower <= minimum <= maximum <= upper:
        raise DomainError(f"Participant limits must satisfy {lower} <= min <= max <= {upper}.")
    result.update(min_participants=minimum, max_participants=maximum)
    return result


class Store:
    def __init__(self, uri, database_name):
        # Create one Store per worker, never share a client across a process fork.
        self.client = MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=5000)
        self.database = self.client[database_name]
        self.users = self.database["users"]
        self.sessions = self.database["sessions"]

    def close(self):
        self.client.close()

    def ensure_indexes(self):
        self.users.create_index("email", unique=True)
        self.sessions.create_index([("participant_ids", ASCENDING), ("start_at", ASCENDING)])
        self.sessions.create_index([("status", ASCENDING), ("start_at", ASCENDING)])
        self.sessions.create_index("start_at")

    def create_user(self, data):
        name = text_field(data, "name", 100)
        email = text_field(data, "email", 254).lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            raise DomainError("Enter a valid email address.")
        password = data.get("password")
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            raise DomainError("Password must contain 8–128 characters.")
        user = dict(name=name, email=email, password_hash=generate_password_hash(password),
                    created_at=utcnow())
        try:
            self.users.insert_one(user)
        except DuplicateKeyError as exc:
            raise DomainError("Email is already registered.", 409) from exc
        return user

    def authenticate_user(self, email, password):
        """Check credentials and return the user without signing them in."""
        if (
            not isinstance(email, str)
            or not isinstance(password, str)
            or not email.strip()
            or not 1 <= len(password) <= 128
        ):
            raise DomainError("Invalid email or password.", 401)

        document = self.users.find_one({
            "email": email.strip().lower()
        })

        if document is None or not check_password_hash(
            document["password_hash"], password
        ):
            raise DomainError("Invalid email or password.", 401)

        return document


    def get_session(self, session_id):
        document = self.sessions.find_one({"_id": object_id(session_id)})
        if document is None:
            raise DomainError("Session not found.", 404)
        return document

    def create_session(self, user_id, data, settings):
        if set(data) - SESSION_FIELDS:
            raise DomainError("Unknown or read-only session fields.")
        now = utcnow()
        document = validate_session(data, settings, now)

        # Prevent students from duplicating their own sessions.
        duplicate = self.sessions.find_one({
           "organizer_id": user_id,
            "course": document["course"],
            "topic": document["topic"],
            "start_at": document["start_at"],
            "end_at": document["end_at"],
            "session_type": document["session_type"],
            "location": document["location"],
            "meeting_url": document["meeting_url"],
            "status": {"$nin": ["cancelled", "closed"]},
        })
        if duplicate:
            raise DomainError(
                "You already created an identical study session. "
                "Please use your existing session instead.",
                409,
            )

            # Prevent an organizer from creating overlapping study sessions.
        overlapping = self.sessions.find_one({
            "organizer_id": user_id,
            "status": {"$nin": ["cancelled", "closed"]},
            "start_at": {"$lt": document["end_at"]},
            "end_at": {"$gt": document["start_at"]},
        })

        if overlapping:
            raise DomainError(
                "You already have a study session scheduled during this time. "
                "Please choose a different time.",
                409,
            )
        # Registration stays open until start_at; the organizer is participant one.
        document.update(
            organizer_id=user_id, participant_ids=[user_id],
            status="confirmed" if document["min_participants"] <= 1 else "waiting",
            revision=1, created_at=now, updated_at=now,
        )
        self.sessions.insert_one(document)
        return document

    def update_session(self, session_id, user_id, changes, settings):
        if not changes or set(changes) - SESSION_FIELDS:
            raise DomainError("Supply editable session fields only.")
        old = self.get_session(session_id)
        if old["organizer_id"] != user_id:
            raise DomainError("Only the organizer can edit this session.", 403)
        now = utcnow()
        # Check the deadline first so an expired start_at reports 409, not a
        # validation error about the old start time.
        if old["status"] not in ("waiting", "confirmed") or old["start_at"] <= now:
            raise DomainError("Registration closed; the session can no longer be edited.", 409)
        updated = validate_session({**old, **changes}, settings, now)
        updated["updated_at"] = now
        # $literal keeps user-supplied strings from being read as aggregation paths.
        values = {key: {"$literal": value} for key, value in updated.items()}
        # New limits can flip waiting/confirmed, so recompute status in the same write.
        values["status"] = {"$cond": [
            {"$gte": [{"$size": "$participant_ids"}, updated["min_participants"]]},
            "confirmed", "waiting",
        ]}
        values["revision"] = {"$add": ["$revision", 1]}
        result = self.sessions.find_one_and_update(
            {"_id": old["_id"], "organizer_id": user_id, "revision": old["revision"],
             "status": {"$in": ["waiting", "confirmed"]}, "start_at": {"$gt": now},
             "$expr": {"$lte": [{"$size": "$participant_ids"}, updated["max_participants"]]}},
            [{"$set": values}],
            return_document=ReturnDocument.AFTER,
        )
        if result is None:
            raise DomainError("Session changed, registration closed, or capacity is below membership. Refresh and retry.", 409)
        return result

    def cancel_session(self, session_id, user_id):
        document = self.get_session(session_id)

        if document["organizer_id"] != user_id:
            raise DomainError("Only the organizer can cancel this session.", 403)

        now = utcnow()

        if document["status"] not in ("waiting", "confirmed") or document["start_at"] <= now:
            raise DomainError("This session can no longer be cancelled.", 409)

        result = self.sessions.find_one_and_update(
            {
                "_id": document["_id"],
                "organizer_id": user_id,
                "status": {"$in": ["waiting", "confirmed"]},
                "start_at": {"$gt": now},
            },
            {
                "$set": {"status": "cancelled", "updated_at": now},
                "$inc": {"revision": 1},
            },
            return_document=ReturnDocument.AFTER,
        )

        if result is None:
            raise DomainError("Session changed or can no longer be cancelled.", 409)

        return result

    def delete_session(self, session_id, user_id):
        document = self.get_session(session_id)
        if document["organizer_id"] != user_id:
            raise DomainError("Only the organizer can delete this session.", 403)
        self.sessions.delete_one({"_id": document["_id"], "organizer_id": user_id})

    def join_session(self, session_id, user_id):
        now = utcnow()
        # Membership and status change in one atomic pipeline: reaching
        # min_participants before the deadline flips the session to confirmed.
        grown = {"$concatArrays": ["$participant_ids", [user_id]]}
        result = self.sessions.find_one_and_update(
            {"_id": object_id(session_id), "status": {"$in": ["waiting", "confirmed"]},
             "start_at": {"$gt": now}, "participant_ids": {"$ne": user_id},
             "$expr": {"$lt": [{"$size": "$participant_ids"}, "$max_participants"]}},
            [{"$set": {
                "participant_ids": grown,
                "status": {"$cond": [{"$gte": [{"$size": grown}, "$min_participants"]},
                                     "confirmed", "waiting"]},
                "updated_at": now, "revision": {"$add": ["$revision", 1]},
            }}],
            return_document=ReturnDocument.AFTER,
        )
        if result is None:
            self.get_session(session_id)
            raise DomainError("Already joined, session full, or registration closed.", 409)
        return result

    def leave_session(self, session_id, user_id):
        now = utcnow()
        # Leaving re-evaluates the state machine: back to waiting before the
        # deadline, closed after the deadline once the count drops below minimum.
        remaining = {"$filter": {"input": "$participant_ids",
                                 "cond": {"$ne": ["$$this", user_id]}}}
        result = self.sessions.find_one_and_update(
            {"_id": object_id(session_id), "organizer_id": {"$ne": user_id},
             "participant_ids": user_id, "end_at": {"$gt": now},
             "status": {"$in": ["waiting", "confirmed"]}},
            [{"$set": {
                "participant_ids": remaining,
                "status": {"$switch": {"branches": [
                    {"case": {"$gte": [{"$size": remaining}, "$min_participants"]},
                     "then": "confirmed"},
                    {"case": {"$gt": ["$start_at", now]}, "then": "waiting"},
                ], "default": "closed"}},
                "updated_at": now, "revision": {"$add": ["$revision", 1]},
            }}],
            return_document=ReturnDocument.AFTER,
        )
        if result is None:
            self.get_session(session_id)
            raise DomainError("Cannot leave: organizer, not joined, completed, or closed.", 409)
        return result

    def cleanup_expired(self, now=None):
        """Settle sessions whose deadline (start_at) passed while still waiting."""
        now = now or utcnow()
        due = {"status": "waiting", "start_at": {"$lte": now}}
        # The current count is checked inside each atomic write, not in Python.
        closed = self.sessions.update_many(
            {**due, "$expr": {"$lt": [{"$size": "$participant_ids"}, "$min_participants"]}},
            {"$set": {"status": "closed", "updated_at": now}, "$inc": {"revision": 1}},
        )
        confirmed = self.sessions.update_many(
            {**due, "$expr": {"$gte": [{"$size": "$participant_ids"}, "$min_participants"]}},
            {"$set": {"status": "confirmed", "updated_at": now}, "$inc": {"revision": 1}},
        )
        return {"closed": closed.modified_count, "confirmed": confirmed.modified_count}


def public_user(document):
    return {key: document[key] for key in ("_id", "name", "email")}


def public_session(document):
    result = dict(document)
    result.pop("registration_deadline", None)  # Legacy field on pre-migration records.
    result["participant_count"] = len(document["participant_ids"])
    now = utcnow()
    before_deadline = document["start_at"] > now
    result["registration_open"] = document["status"] in ("waiting", "confirmed") and before_deadline
    if document["status"] == "cancelled":
        result["display_status"] = "cancelled"
    elif document["status"] == "closed" or (document["status"] == "waiting" and not before_deadline):
        # Underfilled past the deadline; cleanup persists "closed" shortly.
        result["display_status"] = "closed"
    elif document["end_at"] <= now:
        result["display_status"] = "completed"
    elif result["registration_open"] and result["participant_count"] >= document["max_participants"]:
        result["display_status"] = "full"
    else:
        result["display_status"] = document["status"]
    return result
