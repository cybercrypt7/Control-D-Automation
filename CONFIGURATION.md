# Configuration guide

This document covers every value you need to change to make this workflow work for your own Control D account.

---

## Files to edit

| File | What to change |
|------|----------------|
| `scripts/controld_api_push.py` | `FILE_MAPPINGS` — which upstream files map to which of your profiles/folders |
| `scripts/controld_sync.py` | `TARGET_FILES` — which upstream files to download (should match `FILE_MAPPINGS` keys) |

---

## `FILE_MAPPINGS` in `controld_api_push.py`

This is the primary configuration. It tells Stage 2 which Control D folder to push each JSON file's domains into.

### Format

```python
FILE_MAPPINGS: Dict[str, List[Tuple[str, str]]] = {
    "upstream-filename.json": [
        ("Your Profile Name", "Your Folder Name"),
    ],
}
```

Each entry maps one upstream filename to a list of `(profile_name, folder_name)` pairs. One file can sync to multiple profiles simultaneously — just add more pairs to the list.

### How to find your profile and folder names

1. Log into the [Control D dashboard](https://controld.com/dashboard)
2. Go to **Profiles** in the left sidebar
3. The profile name is shown at the top of each profile — **copy it exactly, it is case-sensitive**
4. Inside a profile, open the folder list on the left — **copy the folder name exactly**

### Example

```python
FILE_MAPPINGS: Dict[str, List[Tuple[str, str]]] = {
    # Sync Apple Private Relay list to one profile
    "apple-private-relay-allow-folder.json": [
        ("Home", "Apple Private Relay Block"),
    ],

    # Sync spam TLDs to two profiles at once
    "spam-tlds-folder.json": [
        ("Home",   "Blocked TLDs"),
        ("Travel", "Blocked TLDs"),
    ],
}
```

### Available upstream files

The hagezi repo publishes a large number of Control D-compatible JSON files covering everything from tracker allow-lists to spam TLDs. Browse the full list here:

**[hagezi/dns-blocklists — controld/](https://github.com/hagezi/dns-blocklists/tree/main/controld)**

Add any filename from that directory to `TARGET_FILES` and `FILE_MAPPINGS` to start syncing it. This workflow is not limited to any particular subset — use whatever files suit your setup.

### Processing order and cross-folder deduplication

Within a single profile, domains claimed by an **earlier** entry in `FILE_MAPPINGS` are excluded from **later** entries. This prevents the same domain appearing in both an allow folder and a block folder at the same time.

**Practical rule:** put allow-folders before block-folders in `FILE_MAPPINGS`.

---

## `TARGET_FILES` in `controld_sync.py`

This controls which files Stage 1 downloads from the upstream repo. It should match the keys you have in `FILE_MAPPINGS` — no more, no less.

```python
TARGET_FILES: List[str] = [
    "apple-private-relay-allow-folder.json",
    "spam-tlds-folder.json",
    # add or remove filenames here
]
```

If a filename is in `FILE_MAPPINGS` but not in `TARGET_FILES`, Stage 2 will fail to find the file and skip it with an error.

---

## Schedule

The workflow runs at 05:00 and 17:00 UTC by default. To change this, edit `.github/workflows/sync-controld.yml`:

```yaml
on:
  schedule:
    - cron: '0 5  * * *'   # 05:00 UTC
    - cron: '0 17 * * *'   # 17:00 UTC
```

Standard cron syntax applies. [crontab.guru](https://crontab.guru) is useful for building expressions.

> **Once configuration is complete**, uncomment the `schedule` cron lines in `.github/workflows/sync-controld.yml` to enable automatic runs. The lines are commented out by default so the workflow does not run on a schedule before you have finished setting up your `FILE_MAPPINGS`, `TARGET_FILES`, and GitHub secrets.

---

## Required GitHub secrets

Set these under **Settings → Secrets and variables → Actions**:

#### 🔑 Required Secrets

| Secret | Value | Description |
|--------|-------|-------------|
| `GITHUB_TOKEN` | *(auto-provided)* | Provided automatically by GitHub Actions |
| `CTRLD_API_TOKEN` | Your Control D API token | Requires **write** permissions. Found in the Control D dashboard under **API**. |

#### ✉️ Email Notification Secrets (optional)

When changes are detected, the workflow can send an email report. Omit any to skip email:

| Secret | Value | Description |
|--------|-------|-------------|
| `EMAIL_SERVER` | `smtp.gmail.com` | Gmail SMTP server |
| `EMAIL_PORT` | `465` | Gmail implicit TLS port |
| `EMAIL_USERNAME` | Your Gmail address | e.g. `you@gmail.com` |
| `EMAIL_PASSWORD` | Your Gmail App Password | Generate one at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) — **not** your regular Gmail password |
| `EMAIL_FROM` | Your Gmail address | Sender address |
| `EMAIL_TO` | Your Gmail address | Where sync notifications are sent |

If `EMAIL_SERVER`, `EMAIL_FROM`, or `EMAIL_TO` is missing, the email step is skipped silently.

---

## First run behaviour

On the very first run, the `controld/` directory does not exist yet. Stage 1 will create it and commit all downloaded files as new. Stage 2 will then push all domains in those files to the configured folders — treat this as an initial population, not an incremental diff.

If you already have domains in your Control D folders that are not in the upstream files, they will be removed during the first run (Stage 2 always reconciles to the exact desired state). Make sure your folder contents align with what you expect before the first run, or review the Stage 2 log output carefully.

---

## `requirements.txt` — Python dependencies

`requests` is used by both scripts to make HTTP calls — Stage 1 uses it to download JSON files from the hagezi upstream repo, and Stage 2 uses it to call the Control D API.

Dependencies are managed with **[pip-tools](https://pip-tools.readthedocs.io)**:

| File | Purpose |
|------|---------|
| `requirements.in` | Human-edited source — list only direct dependencies here |
| `requirements.txt` | Auto-generated lock file — all packages pinned by version **and** SHA-256 hash |

The workflow installs with `pip install --require-hashes -r requirements.txt`, which means pip will refuse to install any package whose hash does not match. This prevents a compromised or tampered package on PyPI from being silently installed.

### Updating a dependency

1. Edit `requirements.in` (change the version pin or add/remove a package).
2. Regenerate the lock file:
   ```bash
   pip install pip-tools
   pip-compile --generate-hashes requirements.in -o requirements.txt
   ```
3. Commit both `requirements.in` and `requirements.txt`.
4. Update the version entry in the [dependency reference](#-dependency--action-version-reference) below.

> 💡 **Privacy & security note:** This repo runs entirely within your own GitHub Actions environment. Your API token and email credentials never leave your account. For maximum privacy and security it is recommended to keep your fork **private** — this prevents your profile names, folder names, and workflow configuration from being publicly visible.

---

## 📦 Dependency & action version reference

The entries below document every pinned external dependency used by this repo. Check these periodically and update the pins when new versions are released. Commit hashes are used for Actions (instead of tags) to prevent supply-chain attacks where a tag is silently moved to a different commit.

### Python packages

Versions below reflect the current `requirements.in` pin. All transitive
dependencies are locked with SHA-256 hashes in `requirements.txt` — run
`pip-compile --generate-hashes` after any change (see above).

```yaml
# - package: "requests"
#   url: "https://pypi.org/project/requests/"
#   version: "2.33.1"
#   date: "2026-03-30"
#   transitive-deps: "certifi, charset-normalizer, idna, urllib3"
```

### GitHub Actions

```yaml
# - action: "actions/checkout"
#   url: "https://github.com/actions/checkout/releases"
#   version: "6.0.2"
#   date: "2026-01-09"
#   commit: "de0fac2e4500dabe0009e67214ff5f5447ce83dd"

# - action: "actions/setup-python"
#   url: "https://github.com/actions/setup-python/releases"
#   python-releases: "https://www.python.org/downloads/source/"
#   version: "v6.2.0"
#   date: "2026-01-21"
#   commit: "a309ff8b426b58ec0e2a45f0f869d46889d02405"
#   with:
#     python-version: "3.14"
```

To update an action: find the new release tag and its corresponding full commit hash on the action's GitHub releases page, update the `uses:` line in `.github/workflows/sync-controld.yml` to the new commit hash, and update the entry above.
