# Web Application Exercise

A little exercise to build a web application following an agile development process. See the [instructions](instructions.md) for more detail.

## Product vision statement

Our goal is to help university students find study partners and organize collaborative study sessions by allowing them to create, discover, and join groups based on their courses and availability. 

## User stories

All user stories for our Study Group Finder application can be found in our [GitHub Issues](https://github.com/software-students-fall2026/web-app-exercise-smart-monkeys/issues).


## Steps necessary to run the software

Study Group Finder is a Flask web application using MongoDB for persistent data storage. Flask serves both the HTML website and the JSON API. The application runs locally and does not require deployment.

### 1. Prerequisites

Before starting, ensure you have:

- Python 3.11 or newer
- Git
- A MongoDB database (local MongoDB Community Server or MongoDB Atlas)
- An internet connection if using MongoDB Atlas

Check Python and Git:

```bash
python --version
git --version
```

On macOS/Linux, `python3` may be required instead of `python`.

### 2. Clone the repository

Open a terminal and run:

```bash
git clone https://github.com/software-students-fall2026/web-app-exercise-smart-monkeys.git
cd web-app-exercise-smart-monkeys
```

Team contributors must also run the required repository setup script once per clone:

**macOS/Linux:**
```bash
python3 .automations/setup.py
```

**Windows:**
```powershell
python .automations/setup.py
```

Follow any setup instructions displayed by the script.

### 3. Create a Python virtual environment

**macOS/Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can run the virtual environment's Python directly using `.\.venv\Scripts\python.exe`.

### 4. Install dependencies

With the virtual environment activated, run:

```bash
python -m pip install -r requirements.txt
```

This installs the Python dependencies required by the application.

### 5. Configure MongoDB

The application supports either a local MongoDB server or MongoDB Atlas.

**Option A — MongoDB Atlas (recommended for team testing)**

Use the MongoDB Atlas connection credentials shared privately through the team's course communication channel.

Ensure that:
- The database user has the necessary access permissions.
- Your IP address is permitted by Atlas Network Access settings.
- The connection string is configured in `.env`.

**Option B — Local MongoDB**

Install MongoDB Community Server and start the database service.

See the [official MongoDB installation guide](https://www.mongodb.com/docs/manual/installation/).

For macOS using Homebrew:

```bash
brew tap mongodb/brew
brew install mongodb-community@8.0
brew services start mongodb-community@8.0
```

For Windows, install MongoDB Community Server using the official Windows installer and ensure the MongoDB service is running.

The default local connection is:

```text
mongodb://localhost:27017/
```

### 6. Create the `.env` file

The application reads database credentials and configuration settings from `.env`.

Copy the provided example file:

**macOS/Linux:**

```bash
cp env.example .env
```

**Windows PowerShell:**

```powershell
Copy-Item env.example .env
```

Open `.env` and configure the values for your chosen database.

For a local database, the relevant settings are:

```dotenv
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DB=study_group_finder
SECRET_KEY=replace-with-a-secure-random-secret
```

For MongoDB Atlas, replace `MONGODB_URI` with your Atlas connection string.

Generate a secure Flask secret key using:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copy the generated value into `SECRET_KEY` in `.env`.

**Important:**
- Never commit `.env` to GitHub.
- `env.example` must contain dummy values only.
- Share real credentials privately with teammates and course staff through the approved course messaging channel.
- Shell environment variables override values in `.env`.
- Flask workers using the same application must share a consistent `SECRET_KEY`.

### 7. Start the application

From the repository's root directory, with the virtual environment activated, run:

```bash
python app.py
```

The application should start at:

**http://127.0.0.1:5000/**

Open this address in a web browser to access Study Group Finder.

To check database connectivity, visit:

**http://127.0.0.1:5000/api/health**

A successful connection returns:

```json
{"status": "ok"}
```

You can now create an account, log in, browse sessions, create study groups, and use the application's features.

Stop the Flask server with `Ctrl+C`.

### 8. Optional: Load demonstration data

For a disposable local database, sample data can be inserted using:

```bash
python seed.py
```

The script creates sample study sessions and a demonstration account:

- Email: `organizer@example.test`
- Password: `StudyDemo2026!`

The seeder preserves existing records and does not refresh expired sessions.

**Do not run the demo seeder against the team's shared Atlas database or a production database.**

You can also register your own account through the website without running the seeder.

### 9. Run session cleanup

The application includes a cleanup process for updating session statuses after registration deadlines.

In a separate terminal, with the virtual environment activated, run:

```bash
python cleanup.py
```

To perform one cleanup pass and exit:

```bash
python cleanup.py --once
```

Only one cleanup process is needed for a shared application database. Teammates connected to the same Atlas database should coordinate rather than each starting a cleanup process.

Stop the continuous process using `Ctrl+C`.

### 10. Run automated tests

Automated tests use disposable databases and require a running MongoDB server.

**Do not run the test suite against the team's shared application database.**

Install the testing dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Configure the test database server and run Pytest.

**macOS/Linux:**

```bash
TEST_MONGO_URI=mongodb://127.0.0.1:27017/ python -m pytest -q
```

**Windows PowerShell:**

```powershell
$env:TEST_MONGO_URI = "mongodb://127.0.0.1:27017/"
python -m pytest -q
```

The tests cover authentication, session management, permissions, validation, database operations, concurrency, and related functionality.

Successful execution displays the number of passing tests.

### 11. Troubleshooting

**MongoDB connection error**
- Confirm MongoDB is running or Atlas is reachable.
- Verify `MONGODB_URI` and `MONGODB_DB` in `.env`.
- For Atlas, check the database user's permissions and allowed network access.

**Python module not found**
- Activate the virtual environment.
- Reinstall dependencies using `python -m pip install -r requirements.txt`.

**SECRET_KEY error**
- Generate a valid secret key and save it in `.env`.

**Port 5000 already in use**
- Stop the other application using port 5000 before restarting Flask.

**Application changes not appearing**
- Stop Flask with `Ctrl+C`.
- Pull the latest code if appropriate, then restart the application.

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

While creating a session, the form suggests existing joinable sessions for the same course starting within one hour of the selected time. Additionally, the application prevents organizers from creating new study sessions that overlap with their own existing sessions, helping avoid duplicate bookings and scheduling conflicts.

## Task boards

Our development work was organised into two sprints, with user stories tracked using GitHub Projects.

- [Smart Monkeys — Sprint 1 Task Board](https://github.com/orgs/software-students-fall2026/projects/47/views/1)
- [Smart Monkeys — Sprint 2 Task Board](https://github.com/orgs/software-students-fall2026/projects/47/views/4)