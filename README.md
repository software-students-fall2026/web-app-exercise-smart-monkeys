# Web Application Exercise

A little exercise to build a web application following an agile development process. See the [instructions](instructions.md) for more detail.

## Product vision statement

Our goal is to help university students find study partners and organize collaborative study sessions by allowing them to create, discover, and join groups based on their courses and availability. 

## User stories

All user stories for our Study Group Finder application can be found in our [GitHub Issues](https://github.com/software-students-fall2026/web-app-exercise-smart-monkeys/issues).

## Steps necessary to run the software

The app is a Flask application backed by MongoDB. One server serves both the
website pages and the JSON API.

### 1. Install and start MongoDB

Use Python 3.11 or newer and a running MongoDB Community server (8.0 recommended).
For macOS with Homebrew:

```bash
brew tap mongodb/brew
brew install mongodb-community@8.0
brew services start mongodb-community@8.0
```

See the [official macOS installation guide](https://www.mongodb.com/docs/v8.0/tutorial/install-mongodb-on-os-x/)
or [installation instructions for other operating systems](https://www.mongodb.com/docs/manual/installation/).
MongoDB must be running separately from Flask. Its data persists on disk after
Flask stops. `localhost` connects to each developer's own computer, so these
local databases are not shared between teammates.

### 2. Configure Python and environment variables

```bash
git clone https://github.com/software-students-fall2026/web-app-exercise-smart-monkeys.git
cd web-app-exercise-smart-monkeys
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate with `.venv\Scripts\activate` instead. If `.env` does not
already exist, copy `env.example` to `.env`. Set `SECRET_KEY` to the output of:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

The local database settings are:

```dotenv
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DB=study_group_finder
```

`config.py` loads `.env` and reads all settings. Variables exported in the shell
take precedence over `.env`; code defaults are used when neither sets a value.
Keep the same `SECRET_KEY` for all web workers so login cookies work across them.
`.env` is ignored by Git. Do not commit passwords or real connection credentials.

### 3. Seed and run

From the repository root with the virtual environment active:

```bash
python seed.py
python app.py
```

Check `http://127.0.0.1:5000/api/health`, then open `http://127.0.0.1:5000/` for
the website. Indexes are created automatically on startup.
The seed script inserts four sample sessions and one local demo account:
`organizer@example.test` / `StudyDemo2026!`. It preserves existing records on
subsequent runs; it does not refresh expired sample sessions. Do not run this
demo seeder against a production database.

In a second terminal, activate the same virtual environment and run exactly one
cleanup process:

```bash
python cleanup.py
# Or perform one pass and exit:
python cleanup.py --once
```

For a two-worker demo on macOS/Linux, use this **instead of** `python app.py`:

```bash
gunicorn --workers 2 --bind 127.0.0.1:5000 'app:create_app()'
```

Do not add `--preload`: each worker must construct its own MongoDB client after
forking. Cleanup is not started inside Flask workers. Stop foreground processes
with Ctrl+C. Restart them after changing environment settings.

### 4. Test

Tests require a running real MongoDB server and use a uniquely named disposable
database per test; they never delete the application database.

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

To use another local test server:

```bash
TEST_MONGO_URI=mongodb://127.0.0.1:27018/ python -m pytest -q
```

Tests cover authentication, permissions, validation, CRUD, membership, deadlines,
cleanup, repeatable seeding, and concurrent attempts to take the last seat.

### Backend integration

All endpoints return JSON except successful deletes/logouts, which return 204.
Errors have the shape `{"error": "message"}`. IDs are strings; timestamps are
ISO 8601 UTC strings. Submit times with an explicit timezone (`Z` or an offset).

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Check database connectivity |
| GET | `/api/auth/csrf` | Get a CSRF token and session cookie |
| POST | `/api/auth/register` | Register with name, email, password; log in |
| POST | `/api/auth/login` | Log in with email and password |
| POST | `/api/auth/logout` | Log out |
| GET | `/api/auth/me` | Current user's profile |
| GET | `/api/sessions` | Browse and search |
| POST | `/api/sessions` | Create a session |
| GET | `/api/sessions/<id>` | View details and participant names |
| PATCH | `/api/sessions/<id>` | Organizer edits before registration closes |
| DELETE | `/api/sessions/<id>` | Organizer permanently deletes a session |
| POST | `/api/sessions/<id>/cancel` | Organizer cancels; the record is kept |
| POST | `/api/sessions/<id>/join` | Join before the deadline |
| POST | `/api/sessions/<id>/leave` | Leave a joined session |

Browse filters: `course`, `topic` (case-insensitive literal substring), `date`
(`YYYY-MM-DD`, UTC), `start_from` and `start_to` (a time window; send both, with
timezones, and do not also send `date`), `session_type` (`in_person` or
`virtual`), `mine=true`, `available=true`, `page` (default 1), and `limit`
(default 20, maximum 100).
`mine=true`, detail, and write endpoints require login. Public browse responses
exclude location, meeting links, and member IDs.

Example create payload (replace the times with future dates):

```json
{
  "course": "CSCI-UA 480",
  "topic": "Database design",
  "start_at": "2030-10-20T15:00:00-04:00",
  "end_at": "2030-10-20T16:00:00-04:00",
  "session_type": "in_person",
  "location": "Bobst Library",
  "min_participants": 2,
  "max_participants": 8
}
```

For virtual sessions, use `session_type: "virtual"` and an HTTP(S) `meeting_url`
instead of `location`. Participant limits are optional.

Authentication uses Flask-Login cookies. For every POST/PATCH/DELETE, first fetch
`/api/auth/csrf` and send its token in the `X-CSRFToken` header, with the same
cookie. Fetch a fresh token after login, registration, or logout, which resets
the session. A same-origin frontend can use:

```javascript
const { csrf_token } = await fetch('/api/auth/csrf').then(r => r.json());
const response = await fetch('/api/sessions', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf_token },
  body: JSON.stringify(sessionData)
});
```

### Data and concurrency rules

- `users`: name, normalized unique email, password hash, creation time.
- `sessions`: course/topic, start/end, type/location/link, organizer ID,
  participant ID array, participant limits, status, revision and timestamps.
- The organizer is automatically the first participant and cannot leave their
  own session; they can cancel or delete it. Membership is stored only on the
  session.
- Defaults are minimum 2, maximum 8. Explicit values in the create request take
  priority over the defaults. Overrides must satisfy `2 <= min <= max <= 40`,
  with bounds/defaults configurable in the environment.
- The registration deadline is the session's required `start_at`. Rescheduling
  moves the deadline together with the start time.
- Status is a state machine persisted on the document. Before the deadline,
  join/leave atomically switch between `waiting` (below minimum) and `confirmed`
  (minimum reached). After the deadline, underfilled sessions become `closed`
  and are kept, not deleted; filled sessions stay `confirmed`.
- Join uses one atomic MongoDB update checking the deadline, duplicates and
  capacity, and recomputing status in the same write. An edit cannot lower
  capacity below current membership. Concurrent edits or membership changes can
  cause a 409; refresh before retrying an edit.
- The cleanup process polls every 60 seconds by default and settles sessions
  still `waiting` after the deadline: `closed` below minimum, `confirmed`
  otherwise. Confirmed participants may leave until the session ends; dropping
  below minimum after the deadline also closes the session.
- `display_status` derives `full`, `completed` (after end time), `cancelled`, or
  `closed` (including waiting sessions past the deadline pending cleanup);
  persisted status is `waiting`, `confirmed`, `closed`, or `cancelled`. The
  organizer can cancel a session, which keeps the record, or delete it for good.
- One independent cleanup process is sufficient; no lease-lock collection is
  needed. Cleanup uses conditional database writes and is safe to rerun.

While creating a session, the form suggests existing joinable sessions for the
same course starting within an hour of the chosen time. Schedule-conflict
detection is not implemented.

## Task boards
Sprint 1: https://github.com/orgs/software-students-fall2026/projects/47/views/1


Sprint 2: https://github.com/orgs/software-students-fall2026/projects/47/views/4

