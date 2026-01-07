# Open-Nodebook UI

Open-Nodebook UI is a lightweight Flask dashboard to orchestrate multiple Open Notebook nodes. It centralizes:
- Node management (CRUD) with health checks for API (port 5055) and Web UI (port 8502)
- Knowledge Base (KB) authoring in YAML, plus link curation
- Remote notebook lifecycle actions via the Open Notebook API

## Executive Summary
The app auto-discovers modular features (blueprints) under `features/`, initializes a PostgreSQL-backed database via SQLAlchemy, and provides a PatternFly-based web UI. It saves KB articles to remote nodes with timestamped filenames (KB_YYYYMMDD_HHMMSS_summary.yaml) and aggregates both articles and links into a unified view.

## Pre-install
- Python 3.10+
- PostgreSQL 14+ (or compatible)
- Recommended system packages (Ubuntu): `build-essential libpq-dev python3-dev`

Create and activate a virtual environment, then install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install flask flask-sqlalchemy requests pyyaml gunicorn psycopg2-binary
```

### Configuration
The app reads settings from `config.py` and environment variables:
- `DATABASE_URL` (preferred): `postgresql://USER:PASSWORD@HOST/DBNAME`
- `SECRET_KEY`: Flask secret (set to a strong random value)

If `DATABASE_URL` is not set, `config.py` falls back to a Postgres URI. Override via environment variables in production.

## PostgreSQL install and setup (Ubuntu)
Install Postgres and create a database and user:

```bash
sudo apt update && sudo apt install -y postgresql postgresql-contrib
sudo -u postgres psql
```
Inside psql:
```sql
CREATE DATABASE nodebook_db;
CREATE USER node_admin WITH PASSWORD 'change_me';
GRANT ALL PRIVILEGES ON DATABASE nodebook_db TO node_admin;
\q
```
Then export your application `DATABASE_URL` (example):
```bash
export DATABASE_URL="postgresql://node_admin:change_me@localhost/nodebook_db"
export SECRET_KEY="$(openssl rand -hex 32)"
```

## Running locally
```bash
source venv/bin/activate
export DATABASE_URL="postgresql://node_admin:change_me@localhost/nodebook_db"
export SECRET_KEY="local-dev-secret"
python app.py  # serves on http://0.0.0.0:5000
```
On first start, tables are created automatically (`db.create_all()` in `create_app()`).

## File map (key parts)
- `app.py` — Application factory; loads `Config`, initializes `db`, auto-registers blueprints in `features/*/routes.py`.
- `config.py` — Configuration (SQLAlchemy URI, secret key). Uses env vars when provided.
- `core/models.py` — SQLAlchemy models and `db` instance. `Node` fields: `name`, `ip_address`, optional `ui_host`, `description`, `last_seen`.
- `core/api_client.py` — HTTP client for remote Open Notebook API:
  - Health check: `GET http://{ip}:5055/health`
  - Notebooks CRUD: `GET/POST/DELETE http://{ip}:5055/api/notebooks`
  - Save KB YAML: `POST http://{ip}:5055/api/sources` (creates `KB_YYYYMMDD_HHMMSS_<summary>.yaml`)
  - Save link: `POST http://{ip}:5055/api/sources/json` with `{ type: "link" }`
- `features/dashboard/routes.py` — Home, API and UI health indicators (5055/8502).
- `features/nodes/routes.py` — Node CRUD, manage notebooks per node.
- `features/kb/routes.py` — Create/list/delete KB articles; add/list links; manages notebooks. Targets a notebook named `service_kb_new` by default.
- `core/templates/base.html` — PatternFly 5 layout, HTMX, sidebar navigation.
- `features/**/templates/*` — Page templates for dashboard, nodes, and KB.

## Example systemd service
Create `/etc/systemd/system/open-nodebook-ui.service`:

```ini
[Unit]
Description=Gunicorn instance for Open-Nodebook UI
After=network.target

[Service]
User=david
Group=david
WorkingDirectory=/home/david/code/ainotebook_kb/open-nodebook-ui
Environment="PATH=/home/david/code/ainotebook_kb/open-nodebook-ui/venv/bin"
Environment="DATABASE_URL=postgresql://node_admin:change_me@localhost/nodebook_db"
Environment="SECRET_KEY={{REPLACE_WITH_STRONG_SECRET}}"
ExecStart=/home/david/code/ainotebook_kb/open-nodebook-ui/venv/bin/gunicorn \
  --workers 3 \
  --timeout 120 \
  --bind 0.0.0.0:5000 \
  "app:create_app()"
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```
Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable open-nodebook-ui
sudo systemctl start open-nodebook-ui
sudo systemctl status open-nodebook-ui --no-pager
```

## Troubleshooting
- Database connection fails:
  - Verify Postgres is running: `sudo systemctl status postgresql`.
  - Ensure `DATABASE_URL` matches your DB/user and that the user has privileges.
  - From Python shell, try connecting via SQLAlchemy URI to confirm credentials.
- Tables not created:
  - Check logs on startup for `Database initialization error` messages (printed from `app.py`).
  - Ensure the configured DB user can `CREATE` objects in the database.
- API health shows Offline:
  - Confirm the node’s API on port 5055 is reachable: `curl http://<node-ip>:5055/health`.
  - Check firewalls/security groups between UI host and node(s).
- UI health shows Offline:
  - Set `ui_host` on the Node (e.g. `node.example.com:8502`) if it differs from `ip_address:8502`.
  - Verify the remote UI is listening on 8502 and reachable from the UI host.
- KB actions complain "Notebook 'service_kb_new' not found":
  - Create the notebook via Nodes → Manage or KB → Manage Notebooks before saving articles/links.
- systemd service won’t start:
  - Inspect logs: `journalctl -u open-nodebook-ui -e --no-pager`.
  - Confirm the `venv` path and `ExecStart` path exist and are executable.
  - Ensure `WorkingDirectory` matches the deployed code location.

## Notes
- Default ports: UI (5000), node API (5055), node Web UI (8502).
- Blueprints load automatically if a `features/<name>/routes.py` exposes a `bp` Blueprint.
