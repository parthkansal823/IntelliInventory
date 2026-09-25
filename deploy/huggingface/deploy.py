"""Create / update the Hugging Face Spaces for IntelliInventory (run by .github/workflows/deploy.yml).

Needs only HF_TOKEN (a Hugging Face "write" token). Everything else is optional:

  Demo link (always):   <you>/intelliinventory-demo   - public, sample shop, Parth / Ananya logins
  Real shop (optional): <you>/intelliinventory-shop   - private, only when SHOP_DATABASE_URL is set
      SHOP_DATABASE_URL   Neon Postgres URL (free) - your data lives here
      SHOP_ADMIN_EMAIL    your login email
      SHOP_ADMIN_PASSWORD your login password
      SHOP_SECRET_KEY     optional; generated once when the Space is first created

  HF_DEMO_SPACE / HF_SHOP_SPACE override the Space names (e.g. "yourname/my-dukaan").
  GIT_SHA pins the exact commit to build (the one that passed CI).

    python deploy/huggingface/deploy.py            # deploy
    python deploy/huggingface/deploy.py --dry-run  # print what would happen
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).parent


def space_url(repo_id: str) -> str:
    owner, name = repo_id.split("/")
    return f"https://{re.sub(r'[^a-z0-9]+', '-', f'{owner}-{name}'.lower()).strip('-')}.hf.space"


def dockerfile(sha: str | None) -> bytes:
    text = (HERE / "Dockerfile").read_text()
    if sha:
        text = text.replace("ARG REF=main", f"ARG REF={sha}")
    return text.encode()


def plan(user: str, env: dict) -> list[dict]:
    spaces = [
        {
            "repo_id": env.get("HF_DEMO_SPACE") or f"{user}/intelliinventory-demo",
            "private": False,
            "variables": {"DEMO_MODE": "true"},
            "secrets": {},
        }
    ]
    if env.get("SHOP_DATABASE_URL"):
        missing = [k for k in ("SHOP_ADMIN_EMAIL", "SHOP_ADMIN_PASSWORD") if not env.get(k)]
        if missing:
            raise SystemExit(f"Real-shop Space needs these GitHub secrets too: {', '.join(missing)}")
        shop = {
            "repo_id": env.get("HF_SHOP_SPACE") or f"{user}/intelliinventory-shop",
            "private": True,
            "variables": {"DEMO_MODE": "false"},
            "secrets": {
                "DATABASE_URL": env["SHOP_DATABASE_URL"],
                "ADMIN_EMAIL": env["SHOP_ADMIN_EMAIL"],
                "ADMIN_PASSWORD": env["SHOP_ADMIN_PASSWORD"],
            },
        }
        if env.get("SHOP_SECRET_KEY"):
            shop["secrets"]["SECRET_KEY"] = env["SHOP_SECRET_KEY"]
        spaces.append(shop)
    for s in spaces:
        s["variables"]["PUBLIC_URL"] = space_url(s["repo_id"])
    return spaces


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    env = dict(os.environ)
    token = env.get("HF_TOKEN")
    if not token:
        print("::notice::HF_TOKEN secret is not set - skipping deploy. See docs/TUTORIAL.md section 15.")
        return 0

    if args.dry_run:
        user = env.get("HF_USER", "you")
        api = None
    else:
        from huggingface_hub import HfApi

        api = HfApi(token=token)
        user = api.whoami()["name"]

    sha = env.get("GIT_SHA")
    summary = ["## 🚀 IntelliInventory deployed", "", "| Space | Link | Visibility |", "|---|---|---|"]
    for space in plan(user, env):
        repo_id = space["repo_id"]
        print(f"→ {repo_id} ({'private' if space['private'] else 'public'})")
        if api is None:
            print(f"  would set variables {sorted(space['variables'])} and secrets {sorted(space['secrets'])}")
        else:
            new = not api.repo_exists(repo_id, repo_type="space")
            api.create_repo(repo_id, repo_type="space", space_sdk="docker", private=space["private"], exist_ok=True)
            if new and "SECRET_KEY" not in space["secrets"]:
                # login tokens are signed with this; created once so redeploys don't log everyone out
                space["secrets"]["SECRET_KEY"] = secrets.token_urlsafe(48)
                space["secrets"]["INTEGRATION_TOKEN"] = secrets.token_urlsafe(32)
            for key, value in space["variables"].items():
                api.add_space_variable(repo_id, key, value)
            for key, value in space["secrets"].items():
                api.add_space_secret(repo_id, key, value)
            # Uploading a changed Dockerfile (new commit SHA) makes the Space rebuild with that exact code.
            api.upload_file(
                path_or_fileobj=(HERE / "README.md").read_bytes(),
                path_in_repo="README.md",
                repo_id=repo_id,
                repo_type="space",
                commit_message="Update Space card",
            )
            api.upload_file(
                path_or_fileobj=dockerfile(sha),
                path_in_repo="Dockerfile",
                repo_id=repo_id,
                repo_type="space",
                commit_message=f"Deploy {sha[:7] if sha else 'main'}",
            )
            if not sha:
                api.restart_space(repo_id, factory_reboot=True)
        url = space_url(repo_id)
        print(f"  {url}")
        summary.append(f"| `{repo_id}` | {url} | {'private' if space['private'] else 'public'} |")

    summary += ["", "First build takes ~10-15 minutes (the Hermes model is downloaded). Later builds are faster."]
    if path := env.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a") as fh:
            fh.write("\n".join(summary) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
