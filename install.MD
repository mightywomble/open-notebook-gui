# Open Notebook + Open-Nodebook UI (2-Server Install Guide)

This guide installs a 2-server setup on **Ubuntu 24.04**:

- **Server 1**: **Open Notebook** (API **:5055** + UI **:8502**) + **SurrealDB** + **Ollama** (**:11434**)
- **Server 2**: **Open-Nodebook UI** (Flask/Gunicorn **:5000**) + **PostgreSQL** (local)

It is written to be **copy/paste friendly**.

---

## Conventions and placeholders

Replace these placeholders everywhere:

- `SERVER1_IP` = IP/hostname of the Open Notebook + Ollama server
- `SERVER2_IP` = IP/hostname of the Open-Nodebook UI + Postgres server
- `{{YOUR_LINUX_USER}}` = Linux username used to run services
- `{{YOUR_GIT_URL}}` = Git remote URL for this repo

Secrets (do **not** commit these):

- `{{OPENAI_API_KEY}}`
- `{{GOOGLE_API_KEY}}`
- `{{SET_A_STRONG_PASSWORD}}`

---

## 0) Network and ports checklist

### Server 1 must accept inbound

- `5055/tcp` — Open Notebook API
- `8502/tcp` — Open Notebook UI
- `11434/tcp` — Ollama API (recommend: allow only from Server 2)

### Server 2 must accept inbound

- `5000/tcp` — Open-Nodebook UI

### Postgres

- `5432/tcp` should remain **local-only** on Server 2 (recommended).

---

## 1) Server 1: Install Docker + Ollama + Open Notebook

### 1.1 Install OS packages and Docker

```bash
sudo apt update
sudo apt -y upgrade

sudo apt -y install ca-certificates curl git ufw

# Docker (Ubuntu repo version is fine for most installs)
sudo apt -y install docker.io docker-compose-plugin
sudo systemctl enable --now docker

# Let your user run docker without sudo (log out/in afterwards)
sudo usermod -aG docker "$USER"
```

### 1.2 Configure UFW firewall (recommended)

```bash
sudo ufw allow OpenSSH

# Open Notebook API + UI
sudo ufw allow 5055/tcp
sudo ufw allow 8502/tcp

# Ollama: allow only from Server 2
sudo ufw allow from SERVER2_IP to any port 11434 proto tcp

sudo ufw enable
sudo ufw status
```

### 1.3 Install Ollama and bind to `0.0.0.0:11434`

Install Ollama:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Configure Ollama to listen on all interfaces:

```bash
sudo systemctl edit ollama
```

In the editor, add:

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

Apply changes:

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama
sudo systemctl status ollama --no-pager
```

Quick check:

```bash
curl -s http://127.0.0.1:11434/api/tags
```

### 1.4 Pull recommended Ollama models

Pick based on your hardware:

- Chat:
  - `llama3.1:8b` (solid default)
  - `qwen2.5:7b` (fast)
  - `qwen2.5:14b` (better, needs more RAM/VRAM)
- Embeddings:
  - `nomic-embed-text`
  - `mxbai-embed-large`

Example:

```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

### 1.5 Deploy Open Notebook via Docker Compose

Create a deployment directory:

```bash
sudo mkdir -p /opt/open-notebook
sudo chown -R "$USER:$USER" /opt/open-notebook
cd /opt/open-notebook
```

Create `docker-compose.yml`:

```yaml
services:
  surrealdb:
    image: surrealdb/surrealdb:v2
    restart: always
    user: root
    volumes:
      - ./surreal_data:/mydata
    environment:
      - SURREAL_EXPERIMENTAL_GRAPHQL=true
    ports:
      - "8000:8000"
    command: start --log info --user root --pass root rocksdb:/mydata/mydatabase.db

  open_notebook:
    image: lfnovo/open_notebook:v1-latest
    restart: always
    depends_on:
      - surrealdb
    ports:
      - "5055:5055"
      - "8502:8502"
    env_file:
      - ./docker.env
    volumes:
      - ./notebook_data:/app/data
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

Create `docker.env`:

```bash
cat > docker.env <<'ENV'
# Browser-facing API URL (used by the frontend)
API_URL=http://SERVER1_IP:5055

# SurrealDB connection (Compose service name is surrealdb)
SURREAL_URL="ws://surrealdb/rpc:8000"
SURREAL_USER="root"
SURREAL_PASSWORD="root"
SURREAL_NAMESPACE="open_notebook"
SURREAL_DATABASE="open_notebook"

# Point Open Notebook (in Docker) to Ollama running on the host
OLLAMA_API_BASE="http://host.docker.internal:11434"

# Optional but recommended if exposed
OPEN_NOTEBOOK_PASSWORD={{SET_A_STRONG_PASSWORD}}

# Optional cloud providers (set only if you use them)
OPENAI_API_KEY={{OPENAI_API_KEY}}
GOOGLE_API_KEY={{GOOGLE_API_KEY}}
ENV
```

Start services:

```bash
docker compose up -d
docker compose ps
```

### 1.6 Validate Server 1

From Server 2 (or your laptop):

```bash
curl -s http://SERVER1_IP:5055/health
```

Open in browser:

- Open Notebook UI: `http://SERVER1_IP:8502`

---

## 2) Getting API keys (OpenAI + Google)

### 2.1 OpenAI API key

1. Sign into the OpenAI API platform
2. Go to **API keys**
3. Click **Create new secret key**
4. Copy it once and store it securely

### 2.2 Google Gemini API key

1. Open **Google AI Studio**
2. Create/select a project
3. Create an **API key**
4. Use it as `GOOGLE_API_KEY`

### 2.3 Google OAuth (only for UI login)

The UI supports Google OAuth login and needs an **OAuth Client ID** and **Client Secret**
created in Google Cloud Console (**Credentials → OAuth client**).

These are entered in the UI’s **Google Setup** page and are stored in the UI database.

---

## 3) Server 2: Install Postgres + Open-Nodebook UI (Flask)

### 3.1 Install OS packages

```bash
sudo apt update
sudo apt -y upgrade

sudo apt -y install \
  git python3 python3-venv python3-pip \
  build-essential python3-dev libpq-dev \
  postgresql postgresql-contrib \
  ufw
```

### 3.2 Firewall (UFW)

```bash
sudo ufw allow OpenSSH
sudo ufw allow 5000/tcp
sudo ufw enable
sudo ufw status
```

### 3.3 Set up PostgreSQL database and user

```bash
sudo -u postgres psql
```

Inside `psql`:

```sql
CREATE USER node_admin WITH PASSWORD 'CHANGE_ME_STRONG';
CREATE DATABASE nodebook_db OWNER node_admin;
GRANT ALL PRIVILEGES ON DATABASE nodebook_db TO node_admin;
\q
```

### 3.4 Get the code onto Server 2

```bash
sudo mkdir -p /opt/ainotebook_kb
sudo chown -R "$USER:$USER" /opt/ainotebook_kb
cd /opt/ainotebook_kb

# First time:
git clone {{YOUR_GIT_URL}} .

# Later updates:
git pull
```

### 3.5 Create `open-nodebook-ui/requirements.txt`

Create `open-nodebook-ui/requirements.txt`:

```txt
flask
flask-sqlalchemy
flask-login
authlib
requests
pyyaml
gunicorn
psycopg2-binary
```

### 3.6 Create venv and install dependencies

```bash
cd /opt/ainotebook_kb/open-nodebook-ui

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.7 Configure environment for the UI

Create `/etc/open-nodebook-ui.env`:

```bash
sudo tee /etc/open-nodebook-ui.env >/dev/null <<'EOF_ENV'
DATABASE_URL=postgresql://node_admin:CHANGE_ME_STRONG@localhost/nodebook_db
SECRET_KEY=CHANGE_ME_TO_A_LONG_RANDOM_SECRET

# Point the UI chatbot to Ollama running on Server 1
OLLAMA_API_BASE=http://SERVER1_IP:11434
EOF_ENV

sudo chmod 600 /etc/open-nodebook-ui.env
```

### 3.8 Create systemd service for the UI

Create `/etc/systemd/system/open-nodebook-ui.service`:

```ini
[Unit]
Description=Gunicorn instance for Open-Nodebook UI
After=network.target postgresql.service
Requires=postgresql.service

[Service]
User={{YOUR_LINUX_USER}}
Group={{YOUR_LINUX_USER}}
WorkingDirectory=/opt/ainotebook_kb/open-nodebook-ui

EnvironmentFile=/etc/open-nodebook-ui.env
Environment="PATH=/opt/ainotebook_kb/open-nodebook-ui/venv/bin"

ExecStart=/opt/ainotebook_kb/open-nodebook-ui/venv/bin/gunicorn \
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

### 3.9 Validate Server 2

```bash
curl -s http://127.0.0.1:5000/ | head
```

Open in browser:

- Open-Nodebook UI: `http://SERVER2_IP:5000`

---

## 4) Make the UI talk to Open Notebook (Server 1)

### 4.1 Add the Open Notebook node in the UI

In the Open-Nodebook UI:

1. Log in
2. Go to **Nodes**
3. Create a node:
   - `ip_address = SERVER1_IP`
   - `ui_host = SERVER1_IP:8502` (or a hostname if you have DNS)
4. Save

The UI will check:

- `http://SERVER1_IP:5055/health`
- and link to `http://SERVER1_IP:8502`

### 4.2 Ensure Open Notebook has an Ollama model configured

The UI chatbot flow is:

1. Calls Open Notebook:
   - `GET http://SERVER1_IP:5055/api/models/defaults`
   - `GET http://SERVER1_IP:5055/api/models`
2. Picks an Ollama model (`provider == "ollama"`)
3. Streams generation from Ollama:
   - `POST http://SERVER1_IP:11434/api/generate`

If the UI says **“No Ollama model configured in Open Notebook.”**, you must configure an Ollama model inside Open Notebook and set it as the default.

---

## 5) Recommended Ollama model choices (what to use where)

### On Server 1 (Ollama)

Pull models you want available locally:

- Chat / KB answering:
  - `llama3.1:8b`
  - `qwen2.5:7b`
  - `qwen2.5:14b`
- Embeddings:
  - `nomic-embed-text`
  - `mxbai-embed-large`

### In Open Notebook settings (Server 1 UI)

- Set default **chat model** → your chosen Ollama LLM
- Set default **embedding model** → one of the embedding models

### In Open-Nodebook UI (Server 2)

- Set `OLLAMA_API_BASE=http://SERVER1_IP:11434`
- The UI will prefer whatever **Open Notebook** marks as default.

---

## 6) Troubleshooting (common failures)

### UI can’t connect to Postgres

- Check Postgres:
  ```bash
  sudo systemctl status postgresql --no-pager
  ```
- Confirm `DATABASE_URL` is correct:
  - `postgresql://node_admin:<password>@localhost/nodebook_db`

### UI can’t reach Open Notebook

From Server 2:

```bash
curl -v http://SERVER1_IP:5055/health
```

If it fails:
- Check Server 1 firewall / security group rules
- Check Open Notebook container is running: `docker compose ps`

### Open Notebook container can’t reach Ollama

- Ensure `extra_hosts: host.docker.internal:host-gateway` exists in compose
- Ensure `OLLAMA_API_BASE=http://host.docker.internal:11434` in `docker.env`
- Ensure Ollama listens on `0.0.0.0:11434`

### Ollama exposed publicly (unsafe)

- Restrict inbound `11434/tcp` to Server 2 only (UFW / security groups)

---

## Appendix A: Optional test workflow (remote devtest)

If you need to test Python code in a separate environment:

1. Push changes to a `devtest` branch
2. SSH to the test host
3. Pull repo into `~/code/`
4. Create venv, install requirements, run tests
5. Clean up (stop services, remove folder)

Example:

```bash
# local
git checkout -b devtest
git push -u origin devtest

# on test host
ssh david@100.116.246.164
mkdir -p ~/code
cd ~/code

git clone {{YOUR_GIT_URL}} ainotebook_kb
cd ainotebook_kb

git checkout devtest

authbind --deep || true
python3 -m venv venv
source venv/bin/activate
pip3 install -r open-nodebook-ui/requirements.txt

# run your tests here
# (replace with your actual test command)
# pytest

# cleanup
cd ~/code
rm -rf ainotebook_kb
```
