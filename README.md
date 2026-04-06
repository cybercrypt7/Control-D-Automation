# 🚀 Control D x Hagezi-Sync

Automatically syncs DNS blocklist folders from [hagezi/dns-blocklists](https://github.com/hagezi/dns-blocklists) into your [Control D](https://controld.com) account via the Control D API.

Runs on a GitHub Actions schedule — no server required.

---

## 🔧 Features

- ✅ Automated twice-daily sync via cron (5 AM & 5 PM UTC)
- 🐍 Python-based sync script with retry logic
- 🔒 Pinned dependencies and commit-hash-locked Actions
- ✉️ Sends email with diff summary if files change
- 📁 Keeps the `controld/` folder in sync with upstream
- 🌐 Pushes domain changes to the Control D API automatically
- 🔄 Idempotent reconciliation — self-healing across retried or partial runs

---

## ⚙️ How It Works

The workflow runs twice daily (05:00 and 17:00 UTC) in two stages:

1. 📥 **Stage 1 — File sync** (`scripts/controld_sync.py`)  
   Downloads the target JSON files from the hagezi upstream repository, diffs them against the local copies, and commits any changes back to this repo. Sets a `changed` flag for the next stage.

2. 🌐 **Stage 2 — API push** (`scripts/controld_api_push.py`)  
   Runs only when Stage 1 detected changes. Reads the updated JSON files and reconciles each mapped Control D folder against the desired state — adding new domains and removing stale ones. The reconciliation is always against the **live API state**, so the script is idempotent and self-healing if a previous run was interrupted.

✉️ An email report is sent after Stage 2 summarising every domain added, removed, or skipped per profile and folder.

---

## 🚀 Quick Start

> 💡 **Privacy & security note:** This repo runs entirely within your own GitHub Actions environment. Your API token is used only for outbound requests to the Control D API, and email credentials only for outbound SMTP — neither is logged or persisted beyond the runner. For maximum privacy and security it is recommended to keep your fork **private** — this prevents your profile names, folder names, and workflow configuration from being publicly visible.

### 1. Fork this repo

### 2. Set the required secrets

Go to **Settings → Secrets and variables → Actions → New repository secret** and add the following:

#### 🔑 Required Secrets

| Secret | Value | Description |
|--------|-------|-------------|
| `GITHUB_TOKEN` | *(auto-provided)* | Provided automatically by GitHub Actions |
| `CTRLD_API_TOKEN` | Your Control D API token | Requires **write** permissions. Found in the Control D dashboard under **API**. |

#### ✉️ Email Notification Secrets (optional)

When changes are detected, the workflow can send an email report. Omit any to skip email:

| Secret | Value | Description |
|--------|-------|-------------|
| `EMAIL_SERVER` | `smtp.gmail.com` | Gmail SMTP server (port 465 implicit TLS is used automatically) |
| `EMAIL_USERNAME` | Your Gmail address | e.g. `you@gmail.com` |
| `EMAIL_PASSWORD` | Your Gmail App Password | Generate one at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) — **not** your regular Gmail password |
| `EMAIL_FROM` | Your Gmail address | Sender address |
| `EMAIL_TO` | Your Gmail address | Where sync notifications are sent |

Email is only sent when Stage 2 runs (i.e. files actually changed).

### 3. Configure your profile and folder mappings

Edit `scripts/controld_api_push.py` and update `FILE_MAPPINGS` to match your Control D profile and folder names. See [CONFIGURATION.md](CONFIGURATION.md) for full details.

Also update `TARGET_FILES` in `scripts/controld_sync.py` if you want to track a different subset of files.

### 4. Run manually to verify

Go to **Actions → Sync Control D folders from upstream → Run workflow** to trigger an immediate run and verify everything is working before waiting for the schedule.

---

## 📂 Repository Structure

```
.github/
  workflows/
    sync-controld.yml       # workflow orchestrator
scripts/
  controld_sync.py          # Stage 1: file sync
  controld_api_push.py      # Stage 2: Control D API push
requirements.txt            # pinned Python dependencies
controld/                   # synced JSON files (created on first run)
```

---

## 🌐 Upstream Source

All blocklist JSON files come from [hagezi/dns-blocklists](https://github.com/hagezi/dns-blocklists/tree/main/controld). Hat tip to hagezi for maintaining these lists.
