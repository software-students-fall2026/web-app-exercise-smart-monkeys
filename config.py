"""Application configuration loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get_positive_int(name: str, default: int) -> int:
    """Read a positive integer environment variable."""
    raw_value = os.getenv(name, str(default))

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw_value!r}") from exc

    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")

    return value


class Config:
    """Shared settings for the Flask app and background cleanup process."""

    MONGO_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    MONGO_DB_NAME = os.getenv("MONGODB_DB", "study_group_finder")
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    MAX_CONTENT_LENGTH = 16 * 1024

    # Study groups are small; explicit values in the create request always win.
    DEFAULT_MAX_PARTICIPANTS = _get_positive_int(
        "DEFAULT_MAX_PARTICIPANTS", 8
    )
    DEFAULT_MIN_PARTICIPANTS = _get_positive_int(
        "DEFAULT_MIN_PARTICIPANTS", 2
    )
    MAX_ALLOWED_PARTICIPANTS = _get_positive_int(
        "MAX_ALLOWED_PARTICIPANTS", 40
    )
    MIN_ALLOWED_PARTICIPANTS = _get_positive_int(
        "MIN_ALLOWED_PARTICIPANTS", 2
    )

    CLEANUP_INTERVAL_SECONDS = _get_positive_int(
        "CLEANUP_INTERVAL_SECONDS", 60
    )


def _validate_participant_limits() -> None:
    if Config.MIN_ALLOWED_PARTICIPANTS > Config.DEFAULT_MIN_PARTICIPANTS:
        raise ValueError(
            "MIN_ALLOWED_PARTICIPANTS cannot exceed DEFAULT_MIN_PARTICIPANTS"
        )

    if Config.DEFAULT_MIN_PARTICIPANTS > Config.DEFAULT_MAX_PARTICIPANTS:
        raise ValueError(
            "DEFAULT_MIN_PARTICIPANTS cannot exceed DEFAULT_MAX_PARTICIPANTS"
        )

    if Config.DEFAULT_MAX_PARTICIPANTS > Config.MAX_ALLOWED_PARTICIPANTS:
        raise ValueError(
            "DEFAULT_MAX_PARTICIPANTS cannot exceed MAX_ALLOWED_PARTICIPANTS"
        )


_validate_participant_limits()
