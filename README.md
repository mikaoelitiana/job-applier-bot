# Job Applier

An AI agent that applies to jobs on your behalf. Send a job posting URL to a Telegram bot — the agent opens the page, reads the description, fills the application form, uploads your resume, submits, and logs the result to a Google Sheet.

## How it works

```
Telegram message (URL)
  → bot receives it
  → browser-use agent navigates to the URL
      → reads job description
      → finds the application form
      → fills all fields using your profile
      → uploads your resume PDF
      → submits the form
  → result is written to Google Sheets:  Company | Title | Status | Job Posting Link
  → bot replies with the outcome
```

**Stack:** [browser-use](https://github.com/browser-use/browser-use) · python-telegram-bot · gspread · Docker

---

## Prerequisites

- Docker and Docker Compose installed on your VPS (or local machine)
- An Anthropic (or OpenAI / Gemini) API key
- A Telegram bot token
- A Google Sheet with columns: `Company`, `Title`, `Status`, `Job Posting Link`
- A Google Cloud service account with Sheets access

---

## Setup

### 1. Clone the repo and create your `.env`

```bash
git clone <your-repo-url>
cd applier
cp .env.example .env
```

Edit `.env` and fill in all required values (see comments in the file).

### 2. Add your assets

Place your files in the `assets/` directory:

| File | Description |
|------|-------------|
| `assets/resume.pdf` | Your resume — uploaded to application forms |
| `assets/profile.json` | Your personal details used to fill forms |
| `assets/service_account.json` | Google service account key (optional — see step 4) |

Edit `assets/profile.json` with your real information. The template is pre-filled with placeholders.

> **Note:** `service_account.json` is only required if you use the file-based credential option (Option B in step 4). If you set `GOOGLE_SERVICE_ACCOUNT_JSON` in `.env`, you don't need this file at all.

### 3. Create a Telegram bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the token it gives you into `TELEGRAM_BOT_TOKEN` in your `.env`
4. Find your own Telegram user ID by messaging [@userinfobot](https://t.me/userinfobot)
5. Add your user ID to `ALLOWED_TELEGRAM_USER_IDS` in `.env` to restrict access to yourself

### 4. Set up Google Sheets access (service account)

A service account lets the bot write to your sheet without any OAuth browser flow — ideal for a headless VPS.

**Step 1 — Create a Google Cloud project**

1. Go to [https://console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or reuse an existing one)

**Step 2 — Enable the Google Sheets API**

1. In your project, go to **APIs & Services → Library**
2. Search for "Google Sheets API" and click **Enable**

**Step 3 — Create a service account**

1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → Service Account**
3. Give it any name (e.g. `job-applier`)
4. Skip the optional role/user steps and click **Done**

**Step 4 — Download the JSON key**

1. Click the service account you just created
2. Go to the **Keys** tab
3. Click **Add Key → Create new key → JSON**
4. The file downloads automatically to your computer

**Step 5 — Configure credentials**

You have two options for providing the key to the bot:

**Option A — Env var (recommended for VPS/CI)**

Minify the downloaded JSON to a single line and set it in `.env`:

```bash
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account","project_id":"..."}
```

A quick way to minify it:
```bash
cat ~/Downloads/your-key-file.json | python3 -m json.tool --compact
```

**Option B — File mount**

Save the downloaded file as `assets/service_account.json`. Leave `GOOGLE_SERVICE_ACCOUNT_JSON` unset and the bot will fall back to reading the file via `GOOGLE_SERVICE_ACCOUNT_FILE` (defaults to `assets/service_account.json`).

**Step 6 — Share your Google Sheet with the service account**

1. Open your Google Sheet
2. Click **Share**
3. Add the service account's email address (visible in the Credentials page — it looks like `job-applier@your-project.iam.gserviceaccount.com`)
4. Give it **Editor** access
5. Click **Send**

**Step 7 — Copy the Sheet ID**

From your sheet's URL:
```
https://docs.google.com/spreadsheets/d/THIS_IS_THE_SHEET_ID/edit
```
Paste this value into `GOOGLE_SHEET_ID` in your `.env`.

**Step 8 — Ensure your sheet has the correct header row**

The first row of your target tab must be exactly:
```
Company | Title | Status | Job Posting Link
```
The bot will create this header automatically if the sheet is empty.

### 5. Switching LLM providers

Change one variable in `.env`:

```bash
# Anthropic (default)
LLM_MODEL=anthropic/claude-sonnet-4-0

# OpenAI
LLM_MODEL=openai/gpt-4o

# Google Gemini
LLM_MODEL=gemini/gemini-flash-latest

# Local (Ollama — must be running and accessible from the container)
LLM_MODEL=ollama/llama3.1:8b
```

Set the corresponding API key variable for whichever provider you choose.

---

## Deployment

### Run with Docker Compose (recommended)

```bash
# Build and start
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

The container mounts the `assets/` directory at runtime — your personal files are never baked into the image.

### Run locally (without Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium

cp .env.example .env
# Edit .env, then:
python -m src.bot
```

---

## Usage

Once the bot is running, open Telegram and send it a job posting URL:

```
https://example.com/careers/senior-engineer-123
```

The bot will reply with a progress message, then update it with the outcome:

```
Application submitted!

Job: Senior Software Engineer
Company: Example Corp

Logged to Google Sheet.
```

Or if something went wrong:

```
Application failed.

Job: Senior Software Engineer
Company: Example Corp
Reason: Form requires login — no public application available.

Logged to Google Sheet.
```

---

## Project structure

```
applier/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── assets/
│   ├── profile.json          ← your personal details
│   ├── resume.pdf            ← your resume (add this yourself)
│   └── service_account.json  ← Google service account key (add this yourself)
└── src/
    ├── bot.py      ← Telegram bot entrypoint
    ├── agent.py    ← browser-use agent + task definition
    ├── sheets.py   ← Google Sheets writer
    └── config.py   ← settings loaded from .env
```

---

## Security notes

- `assets/resume.pdf` contains personal data — never commit it to git
- `assets/service_account.json` contains sensitive credentials — never commit it to git (prefer the `GOOGLE_SERVICE_ACCOUNT_JSON` env var on a VPS so no file needs to be transferred)
- Use `ALLOWED_TELEGRAM_USER_IDS` to restrict bot access to your own account
- Keep your `.env` file out of version control (it is in `.gitignore`)
