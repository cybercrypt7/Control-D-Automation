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
import base64
from pathlib import Path
from typing import List, Tuple, Optional
from urllib.parse import urlparse

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
        # Inject the token via http.extraheader stored in local git config so it
        # never appears in process arguments for the push (visible via /proc/<pid>/cmdline).
        # This mirrors the technique used by actions/checkout itself.
        # The git config call does receive the token in its argv, but capture_output=True
        # keeps it off stdout/stderr, and the CalledProcessError handler below ensures a
        # failure raises a sanitised RuntimeError (not the raw CalledProcessError whose
        # .cmd would contain the base64-encoded token).
        auth = base64.b64encode(f"x-access-token:{github_token}".encode()).decode()
        try:
            subprocess.run(
                [
                    "git", "config", "--local",
                    "http.https://github.com/.extraheader",
                    f"AUTHORIZATION: basic {auth}",
                ],
                check=True,
                capture_output=True,  # prevent git noise; also keeps args out of default output
            )
        except subprocess.CalledProcessError as exc:
            # Re-raise without the original exception so the CalledProcessError
            # (whose .cmd includes the base64-encoded token) is never printed to
            # workflow logs.  The raw exit code is still surfaced for diagnosis.
            raise RuntimeError(
                f"Failed to set git credential header (exit {exc.returncode})"
            ) from None
        try:
            remote_url = f"https://github.com/{repo_name}.git"
            subprocess.run(["git", "push", remote_url, "main"], check=True)
            print("Changes pushed to repository")
        finally:
            # Always scrub the credential from local config, even on push failure.
            subprocess.run(
                [
                    "git", "config", "--local", "--unset",
                    "http.https://github.com/.extraheader",
                ],
                check=False,
            )

    # ── Temp dir helpers ──────────────────────────────────────────────────────

    def cleanup_temp(self) -> None:
        if TEMP_DIR.exists():
            shutil.rmtree(TEMP_DIR)

    # ── Download ──────────────────────────────────────────────────────────────

    def download_files(self, github_token: str = "") -> bool:
        """
        Download TARGET_FILES from upstream with retry logic.
        Passing github_token uses the authenticated GitHub API rate limit
        (5 000 req/hr) instead of the shared unauthenticated limit (60 req/hr).
        Returns True on success, False after all attempts are exhausted.
        """
        api_headers = {}
        if github_token:
            api_headers["Authorization"] = f"Bearer {github_token}"

        for attempt in range(1, MAX_ATTEMPTS + 1):
            print(f"Download attempt #{attempt}")
            try:
                self.cleanup_temp()
                TEMP_DIR.mkdir(exist_ok=True)

                # List all files in the upstream controld/ directory
                response = requests.get(UPSTREAM_API_URL, headers=api_headers, timeout=30)
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
                    # Validate the download URL before fetching to prevent SSRF
                    # in case the GitHub API response is tampered with.
                    parsed = urlparse(url)
                    if parsed.scheme not in ("http", "https"):
                        raise ValueError(
                            f"Unexpected URL scheme for '{filename}': {parsed.scheme!r}"
                        )
                    if not parsed.netloc.endswith("githubusercontent.com"):
                        raise ValueError(
                            f"Unexpected URL host for '{filename}': {parsed.netloc!r}"
                        )
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

            if not self.download_files(github_token):
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
