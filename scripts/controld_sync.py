#!/usr/bin/env python3
"""
Stage 1 — File sync.

Downloads the target JSON files from the hagezi/dns-blocklists upstream
repository, compares them against the local copies, commits any changes,
and signals downstream steps via GITHUB_OUTPUT.

Customisation: edit TARGET_FILES to control which files are downloaded.
The list here should match the keys in FILE_MAPPINGS in controld_api_push.py.
"""

import os
import sys
import time
import shutil
import subprocess
import difflib
from pathlib import Path
from typing import List, Tuple, Optional

import requests


# ── User configuration ────────────────────────────────────────────────────────

UPSTREAM_API_URL = (
    "https://api.github.com/repos/hagezi/dns-blocklists/contents/controld"
)

# Files to download from the upstream controld/ directory.
# Remove any files you don't want to track; add new filenames as hagezi
# publishes them.  Must match the keys in FILE_MAPPINGS in controld_api_push.py.
TARGET_FILES: List[str] = [
    "apple-private-relay-allow-folder.json",
    "meta-tracker-allow-folder.json",
    "microsoft-allow-folder.json",
    "native-tracker-apple-folder.json",
    "native-tracker-microsoft-folder.json",
    "spam-tlds-folder.json",
]

# ── Internal constants ────────────────────────────────────────────────────────

MAX_ATTEMPTS  = 5
RETRY_DELAY   = 60   # seconds between download retry attempts
TEMP_DIR      = Path("temp_controld")
TARGET_DIR    = Path("controld")


# ── Sync class ────────────────────────────────────────────────────────────────

class ControldSync:

    # ── Git helpers ───────────────────────────────────────────────────────────

    def setup_git(self) -> None:
        """Configure git identity for the commit made by this workflow."""
        subprocess.run(["git", "config", "user.name",  "GitHub Actions"], check=True)
        subprocess.run(["git", "config", "user.email", "actions@github.com"], check=True)

    def commit_and_push(self, github_token: str, repo_name: str) -> None:
        """Stage, commit, and push changes in TARGET_DIR."""
        subprocess.run(["git", "add", str(TARGET_DIR)], check=True)
        subprocess.run(
            ["git", "commit", "-m", "Sync controld folder from upstream"],
            check=True,
        )
        remote_url = f"https://x-access-token:{github_token}@github.com/{repo_name}.git"
        subprocess.run(["git", "remote", "set-url", "origin", remote_url], check=True)
        subprocess.run(["git", "push", "origin", "main"], check=True)
        print("Changes pushed to repository")

    # ── Temp dir helpers ──────────────────────────────────────────────────────

    def cleanup_temp(self) -> None:
        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR)

    # ── Download ──────────────────────────────────────────────────────────────

    def download_files(self) -> bool:
        """
        Download TARGET_FILES from upstream with retry logic.
        Returns True on success, False after all attempts are exhausted.
        """
        for attempt in range(1, MAX_ATTEMPTS + 1):
            print(f"Download attempt #{attempt}")
            try:
                self.cleanup_temp()
                TEMP_DIR.mkdir(exist_ok=True)

                # List all files in the upstream controld/ directory
                response = requests.get(UPSTREAM_API_URL, timeout=30)
                response.raise_for_status()

                # Download only the files we care about
                upstream_files = {
                    f["name"]: f["download_url"]
                    for f in response.json()
                    if f.get("type") == "file" and f.get("name") in TARGET_FILES
                }

                for filename in TARGET_FILES:
                    url = upstream_files.get(filename)
                    if not url:
                        raise ValueError(f"File not found in upstream: {filename}")
                    file_response = requests.get(url, timeout=30)
                    file_response.raise_for_status()
                    (TEMP_DIR / filename).write_bytes(file_response.content)

                print("Download successful.")
                return True

            except requests.RequestException as exc:
                print(f"Network error on attempt {attempt}: {exc}")
            except Exception as exc:
                print(f"Unexpected error on attempt {attempt}: {exc}")

            if attempt < MAX_ATTEMPTS:
                print(f"Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)

        print(f"All {MAX_ATTEMPTS} download attempts failed.")
        return False

    # ── Diff / sync ───────────────────────────────────────────────────────────

    def get_file_diff(
        self,
        existing: Optional[Path],
        incoming: Path,
    ) -> Tuple[str, List[str]]:
        """
        Returns (raw_unified_diff, emoji_formatted_lines).
        If `existing` is None (new file) every line is treated as an addition.
        """
        if existing is None or not existing.exists():
            lines = incoming.read_text(encoding="utf-8").splitlines()
            emoji_lines = [f"✅ {line}" for line in lines]
            return "\n".join(f"+ {l}" for l in lines), emoji_lines

        old_lines = existing.read_text(encoding="utf-8").splitlines(keepends=True)
        new_lines = incoming.read_text(encoding="utf-8").splitlines(keepends=True)

        diff = list(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=str(existing), tofile=str(incoming),
            lineterm="",
        ))

        emoji_lines = []
        for line in diff:
            if line.startswith("+") and not line.startswith("+++"):
                emoji_lines.append(f"✅ {line[1:]}")
            elif line.startswith("-") and not line.startswith("---"):
                emoji_lines.append(f"❌ {line[1:]}")

        return "".join(diff), emoji_lines

    def sync_files(self) -> Tuple[bool, str]:
        """
        Copy changed files from TEMP_DIR into TARGET_DIR.
        Returns (any_changes, pretty_diff_output).
        Exits with an error message if an expected file is missing from upstream.
        """
        TARGET_DIR.mkdir(exist_ok=True)
        changed: List[str] = []
        pretty_output = ""

        for filename in TARGET_FILES:
            temp_file   = TEMP_DIR   / filename
            target_file = TARGET_DIR / filename

            if not temp_file.exists():
                print(f"ERROR: Expected file '{filename}' was not downloaded.")
                return False, ""

            diff_text, emoji_diff = self.get_file_diff(
                target_file if target_file.exists() else None,
                temp_file,
            )

            if diff_text:
                shutil.copy2(temp_file, target_file)
                changed.append(filename)
                if emoji_diff:
                    pretty_output += f"[{filename}]\n"
                    pretty_output += "\n".join(emoji_diff)
                    pretty_output += "\n\n"

        return bool(changed), pretty_output

    # ── Orchestration ─────────────────────────────────────────────────────────

    def run(self, github_token: str, repo_name: str) -> None:
        """End-to-end sync: download → diff → commit."""
        try:
            print("Starting controld sync process...")
            self.setup_git()

            if not self.download_files():
                sys.exit(1)

            has_changes, diff_output = self.sync_files()

            github_output_path = os.environ.get("GITHUB_OUTPUT", "")

            if has_changes:
                print("Changes detected — committing and pushing...")
                self.commit_and_push(github_token, repo_name)

                if github_output_path:
                    with open(github_output_path, "a") as fh:
                        fh.write("changed=true\n")
                        fh.write("diff_output<<EOF\n")
                        fh.write(diff_output)
                        fh.write("\nEOF\n")

                print("Sync completed with changes.")
            else:
                print("No changes detected.")

                if github_output_path:
                    with open(github_output_path, "a") as fh:
                        fh.write("changed=false\n")

        except Exception as exc:
            print(f"Sync failed: {exc}")
            sys.exit(1)
        finally:
            self.cleanup_temp()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    github_token = os.getenv("GITHUB_TOKEN", "").strip()
    repo_name    = os.getenv("GITHUB_REPOSITORY", "").strip()

    if not github_token or not repo_name:
        print("ERROR: GITHUB_TOKEN and GITHUB_REPOSITORY must be set.")
        sys.exit(1)

    ControldSync().run(github_token, repo_name)


if __name__ == "__main__":
    main()
