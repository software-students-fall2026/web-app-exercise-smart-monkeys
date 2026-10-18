"""Flask JSON API. Frontend templates can consume these endpoints."""

import re
from datetime import date, datetime, timedelta, timezone

from bson import ObjectId
from flask import Flask, jsonify, request, session
from flask.json.provider import DefaultJSONProvider
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_wtf.csrf import CSRFError, CSRFProtect, generate_csrf
from pymongo.errors import PyMongoError
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash

from config import Config
from db import DomainError, Store, object_id, public_session, public_user, utcnow


class MongoJSONProvider(DefaultJSONProvider):
    @staticmethod
    def default(value):
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return DefaultJSONProvider.default(value)


class User(UserMixin):
    def __init__(self, document):
        self.id = str(document["_id"])
        self.document = document


def json_body():
    data = request.get_json()
    if not isinstance(data, dict):
        raise DomainError("Request body must be a JSON object.")
    return data


def create_app(test_config=None):
    app = Flask(__name__)
    app.json = MongoJSONProvider(app)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    secret = app.config.get("SECRET_KEY", "")
    if not isinstance(secret, str) or len(secret) < 32 or secret == "replace-with-a-random-secret":
        raise RuntimeError("Set SECRET_KEY in .env to a random string of at least 32 characters.")

    store = Store(app.config["MONGO_URI"], app.config["MONGO_DB_NAME"])
    try:
        store.ensure_indexes()
    except PyMongoError:
        store.close()
        raise RuntimeError("Cannot initialize MongoDB. Start MongoDB and check MONGO_URI.") from None
    app.extensions["store"] = store
    # Keep the pool for the life of this worker; do not close it after each request.
    CSRFProtect(app)
    login_manager = LoginManager(app)

    @login_manager.user_loader
    def load_user(user_id):
        try:
            document = store.users.find_one({"_id": object_id(user_id)})
        except DomainError:
            return None
        return User(document) if document else None

    @login_manager.unauthorized_handler
    def unauthorized():
        return jsonify(error="Login required."), 401

    @app.errorhandler(DomainError)
    def domain_error(error):
        return jsonify(error=str(error)), error.status

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return jsonify(error=error.description), 400

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(PyMongoError)
    def database_error(error):
        app.logger.error("Database operation failed (%s)", type(error).__name__)
        return jsonify(error="Database unavailable. Please retry shortly."), 503

    @app.get("/api/health")
    def health():
        store.client.admin.command("ping")
        return jsonify(status="ok")

    @app.get("/api/auth/csrf")
    def csrf_token():
        response = jsonify(csrf_token=generate_csrf())
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/auth/register")
    def register():
        document = store.create_user(json_body())
        session.clear()
        login_user(User(document))
        return jsonify(user=public_user(document)), 201

    @app.post("/api/auth/login")
    def login():
        data = json_body()
        email, password = data.get("email"), data.get("password")
        if not isinstance(email, str) or not isinstance(password, str) or len(password) > 128:
            raise DomainError("Supply an email and password.")
        document = store.users.find_one({"email": email.strip().lower()})
        if document is None or not check_password_hash(document["password_hash"], password):
            raise DomainError("Invalid email or password.", 401)
        session.clear()
        login_user(User(document))
        return jsonify(user=public_user(document))

    @app.post("/api/auth/logout")
    @login_required
    def logout():
        logout_user()
        session.clear()
        return "", 204

    @app.get("/api/auth/me")
    @login_required
    def me():
        return jsonify(user=public_user(current_user.document))
    from flask import render_template

    @app.get("/create-session")
    def create_session_page():
        return render_template("create_session.html")
        

    @app.get("/api/sessions")
    def browse_sessions():
        query = {}
        for field in ("course", "topic"):
            value = request.args.get(field, "").strip()
            if len(value) > 200:
                raise DomainError(f"{field} search is too long.")
            if value:
                query[field] = {"$regex": re.escape(value), "$options": "i"}
        if "session_type" in request.args:
            kind = request.args["session_type"]
            if kind not in ("in_person", "virtual"):
                raise DomainError("session_type must be in_person or virtual.")
            query["session_type"] = kind
        if "date" in request.args:
            try:
                day = date.fromisoformat(request.args["date"])
                start = datetime.combine(day, datetime.min.time(), timezone.utc)
                end = start + timedelta(days=1)
            except (ValueError, OverflowError) as exc:
                raise DomainError("date must be YYYY-MM-DD (UTC).") from exc
            query["start_at"] = {"$gte": start, "$lt": end}
        for flag in ("mine", "available"):
            if flag in request.args and request.args[flag] not in ("true", "false"):
                raise DomainError(f"{flag} must be true or false.")
        if request.args.get("mine") == "true":
            if not current_user.is_authenticated:
                raise DomainError("Login required.", 401)
            query["participant_ids"] = current_user.document["_id"]
        if request.args.get("available") == "true":
            # Joinable until the deadline (start_at), including already-confirmed groups.
            query["status"] = {"$in": ["waiting", "confirmed"]}
            query.setdefault("start_at", {})["$gt"] = utcnow()
            query["$expr"] = {"$lt": [{"$size": "$participant_ids"}, "$max_participants"]}
        try:
            page, limit = int(request.args.get("page", 1)), int(request.args.get("limit", 20))
        except ValueError as exc:
            raise DomainError("page and limit must be integers.") from exc
        if not 1 <= page <= 10000 or not 1 <= limit <= 100:
            raise DomainError("page must be 1–10000 and limit 1–100.")
        documents = store.sessions.find(query).sort([("start_at", 1), ("_id", 1)]).skip((page - 1) * limit).limit(limit)
        # Meeting links and member IDs are available only on the authenticated detail endpoint.
        results = []
        for document in documents:
            result = public_session(document)
            for key in ("participant_ids", "meeting_url", "location"):
                result.pop(key, None)
            results.append(result)
        return jsonify(sessions=results, page=page, limit=limit)

    @app.post("/api/sessions")
    @login_required
    def create_session():
        document = store.create_session(current_user.document["_id"], json_body(), app.config)
        return jsonify(session=public_session(document)), 201

    @app.get("/api/sessions/<session_id>")
    @login_required
    def session_detail(session_id):
        document = store.get_session(session_id)
        result = public_session(document)
        result["participants"] = list(store.users.find(
            {"_id": {"$in": document["participant_ids"]}}, {"name": 1},
        ))
        return jsonify(session=result)

    @app.patch("/api/sessions/<session_id>")
    @login_required
    def edit_session(session_id):
        document = store.update_session(session_id, current_user.document["_id"], json_body(), app.config)
        return jsonify(session=public_session(document))

    @app.delete("/api/sessions/<session_id>")
    @login_required
    def delete_session(session_id):
        store.delete_session(session_id, current_user.document["_id"])
        return "", 204

    @app.post("/api/sessions/<session_id>/join")
    @login_required
    def join_session(session_id):
        document = store.join_session(session_id, current_user.document["_id"])
        return jsonify(session=public_session(document))

    @app.post("/api/sessions/<session_id>/leave")
    @login_required
    def leave_session(session_id):
        document = store.leave_session(session_id, current_user.document["_id"])
        return jsonify(session=public_session(document))

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000)
