# ReminderBot

A lightweight Django backend for managing reminders through Mattermost Interactive Dialogs. Designed for self-hosted Mattermost instances with n8n as the scheduling trigger.

## Architecture

```
User → Mattermost Slash Command → ReminderBot (Django) → SQLite
n8n → ReminderBot API → Mattermost (via ReminderBot)
```

**Key constraint:** n8n never communicates directly with Mattermost. All Mattermost interaction goes through ReminderBot.

## Features

- **Interactive Dialogs** — `/remind` slash command opens a Mattermost dialog for reminder creation
- **Recurring Reminders** — Hourly, daily, weekly, monthly, yearly recurrence
- **Snooze Support** — Configurable snooze durations
- **n8n Integration** — Poll for due reminders and trigger delivery
- **Auto-Discovery** — Bot user ID and team ID are discovered automatically
- **REST API** — Full CRUD with Swagger documentation

## Quick Start (Local)

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Mattermost details

# Run migrations
python manage.py migrate

# Start development server
python manage.py runserver
```

## Quick Start (Docker)

```bash
# Configure environment
cp .env.example .env
# Edit .env with your Mattermost details

# Build and start
docker compose up -d --build
```

The SQLite database is persisted in `./data/db.sqlite3` via a Docker volume mount.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `MATTERMOST_URL` | ✅ | Base URL of your Mattermost instance (e.g. `https://comms.example.com`) |
| `MATTERMOST_BOT_TOKEN` | ✅ | Bot account access token |
| `MATTERMOST_REMINDER_CHANNEL_ID` | ✅ | Channel ID where reminders are posted |
| `SECRET_KEY` | ✅ | Django secret key |
| `DEBUG` | ❌ | `True` for development (default: `False`) |

**Not required:** `MATTERMOST_TEAM_ID` and `MATTERMOST_BOT_USER_ID` are auto-discovered.

## API Endpoints

### Reminders CRUD

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/reminders/` | List all reminders |
| `POST` | `/api/v1/reminders/` | Create a reminder |
| `GET` | `/api/v1/reminders/{external_id}/` | Retrieve a reminder |
| `PUT` | `/api/v1/reminders/{external_id}/` | Update a reminder |
| `PATCH` | `/api/v1/reminders/{external_id}/` | Partially update a reminder |
| `DELETE` | `/api/v1/reminders/{external_id}/` | Delete a reminder |

### n8n Integration

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/reminders/pending/` | Get all due reminders (status=pending, datetime ≤ now) |
| `POST` | `/api/v1/reminders/{external_id}/trigger/` | Trigger a reminder (send message + update state) |

### Mattermost Webhooks

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/mattermost/slash/remind/` | Slash command handler — opens the dialog |
| `POST` | `/mattermost/dialog/submit/` | Dialog submission handler — saves the reminder |

### Documentation

| Endpoint | Description |
|---|---|
| `/api/schema/` | OpenAPI 3.0 schema (JSON) |
| `/api/docs/` | Swagger UI |

## Mattermost Setup

1. **Create a Bot Account** in Mattermost → Integrations → Bot Accounts
2. **Create a Slash Command:**
   - Command: `/remind`
   - Request URL: `https://your-reminderbot-host/mattermost/slash/remind/`
   - Request Method: `POST`
3. **Note the Channel ID** where you want reminders posted (Settings → Channel → View Info)

## n8n Workflow

Set up a simple n8n workflow:

1. **Schedule Trigger** — Run every minute
2. **HTTP Request** — `GET /api/v1/reminders/pending/`
3. **Loop** — For each reminder in the response
4. **HTTP Request** — `POST /api/v1/reminders/{external_id}/trigger/`

## Project Structure

```
├── reminderbot/            # Django project settings
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── reminders/              # Main application
│   ├── models.py           # Reminder model
│   ├── serializers.py      # DRF serializers
│   ├── views.py            # API views + Mattermost handlers
│   ├── urls.py             # URL routing
│   ├── admin.py            # Django admin config
│   └── services/           # Business logic
│       ├── mattermost_service.py    # Mattermost API client
│       └── reminder_service.py      # Execution & recurrence logic
├── data/                   # SQLite database (Docker volume)
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── requirements.txt
└── manage.py
```
