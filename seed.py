"""Insert demo records without replacing existing records. Local development only."""

from datetime import timedelta

from bson import ObjectId
from werkzeug.security import generate_password_hash

from config import Config
from db import Store, utcnow


DEMO_PASSWORD = "StudyDemo2026!"


def seed(store):
    store.ensure_indexes()
    now = utcnow()
    store.users.update_one(
        {"email": "organizer@example.test"},
        {"$setOnInsert": {"name": "Demo Organizer", "created_at": now,
                          "password_hash": generate_password_hash(DEMO_PASSWORD)}},
        upsert=True,
    )
    organizer = store.users.find_one({"email": "organizer@example.test"})["_id"]
    samples = [
        ("CSCI-UA 480", "Software engineering sprint planning", "in_person", "Bobst Library"),
        ("CSCI-UA 201", "Linked lists and trees", "virtual", "https://example.com/study-room"),
        ("MATH-UA 121", "Calculus practice", "in_person", "Courant study lounge"),
        ("CSCI-UA 60", "Database schema review", "virtual", "https://example.com/database-room"),
    ]
    inserted = 0
    for index, (course, topic, kind, place) in enumerate(samples):
        start = now + timedelta(days=index + 2)
        result = store.sessions.update_one(
            {"_id": ObjectId(f"00000000000000000000010{index}")},
            {"$setOnInsert": {
                "course": course, "topic": topic, "session_type": kind,
                "location": place if kind == "in_person" else None,
                "meeting_url": place if kind == "virtual" else None,
                "start_at": start, "end_at": start + timedelta(hours=1),
                "organizer_id": organizer, "participant_ids": [organizer],
                "min_participants": Config.DEFAULT_MIN_PARTICIPANTS,
                "max_participants": Config.DEFAULT_MAX_PARTICIPANTS,
                "registration_deadline": min(start, now + timedelta(minutes=Config.REGISTRATION_WINDOW_MINUTES)),
                "status": "waiting", "revision": 1, "created_at": now, "updated_at": now,
            }},
            upsert=True,
        )
        inserted += result.upserted_id is not None
    return inserted


def main():
    store = Store(Config.MONGO_URI, Config.MONGO_DB_NAME)
    try:
        print(f"Inserted {seed(store)} demo sessions; existing records were preserved.")
        print(f"New demo account: organizer@example.test / {DEMO_PASSWORD}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
