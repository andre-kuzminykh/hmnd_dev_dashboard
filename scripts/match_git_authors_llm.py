"""LLM-assisted matcher: maps git_authors → users.id using GPT.

The deterministic matcher in `data/sources/git_csv.py` handles
email-exact / name-exact / local-part-of-email cases. This script
catches the rest:

  - 'olsi'             → Oleg Sinavski
  - 'apar'             → Andy Park (apar@skl.vc)
  - 'Andy Park'        → 'Andy' (AI side abbreviated)
  - 'Sam Pfeiffer'     → 'sapf@thehumanoid.ai'

Single batched prompt sent to OpenAI (model from HMND_MATCHER_MODEL,
default gpt-4o-mini). Output is a JSON map. We only update rows whose
current `user_id` is NULL (already-matched rows are left as-is).

Run on the VM after `scripts/extract_git_stats` + reset:

    docker compose exec -e OPENAI_API_KEYS=... \\
      dashboard python -m scripts.match_git_authors_llm

Read-only by default. Pass --apply to write the matches into the DB.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import requests

from data.db import get_conn


PROMPT = """You are matching Git authors to AI-users in a developer team.

Each Git author has a name (sometimes alias, lowercase, abbreviated) and one or more emails.
Each AI-user has a canonical full_name and a primary email.
The same person may appear with different name spellings and personal vs work emails.

Return ONLY a JSON object mapping `git_author_name` → `ai_user_id` (integer).
If a Git author has no plausible match, set the value to null.
Do not invent ai_user_ids — only use those listed.

Heuristics to apply:
- email local-part match across domains: "apar@gmail.com" likely matches "apar@thehumanoid.ai"
- transliteration / abbreviation: "olsi" ≈ "Oleg Sinavski", "sapf" ≈ "Sam Pfeiffer"
- name-token overlap: "Andy Park" matches "Andy", "Park", "apar"
- if multiple candidates, prefer same first-letter-of-email matching first-letter-of-first-name

AI USERS:
{ai_users}

GIT AUTHORS (only the ones NOT already matched):
{git_authors}

Output ONLY the JSON object. No prose."""


def _model() -> str:
    return os.environ.get("HMND_MATCHER_MODEL", "gpt-4o-mini")


def _openai_key() -> str | None:
    """Pick an admin/project key from OPENAI_API_KEYS (Artem first)."""
    raw = os.environ.get("OPENAI_API_KEYS") or ""
    if raw:
        try:
            items = json.loads(raw)
            for it in items:
                if (it.get("label") or "").lower() == "artem" and it.get("key"):
                    return it["key"]
            for it in items:
                if it.get("key"):
                    return it["key"]
        except json.JSONDecodeError:
            pass
    return os.environ.get("OPENAI_API_KEY") or None


def _gather() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with get_conn() as conn:
        ai_users = [dict(r) for r in conn.execute(
            "SELECT id, full_name, email FROM users WHERE is_active = 1"
        ).fetchall()]
        unmatched = [dict(r) for r in conn.execute(
            "SELECT id, name, emails FROM git_authors WHERE user_id IS NULL"
        ).fetchall()]
    return ai_users, unmatched


def _call_llm(ai_users: list[dict], git_authors: list[dict]) -> dict[str, int | None]:
    key = _openai_key()
    if not key:
        print("ERROR: no OPENAI_API_KEYS / OPENAI_API_KEY env set", file=sys.stderr)
        sys.exit(2)

    ai_lines = "\n".join(
        f"  {u['id']:>4} {u['full_name']!s:<32} <{u.get('email') or ''}>"
        for u in ai_users
    )
    git_lines = "\n".join(
        f"  {a['name']!s:<32} <{(a.get('emails') or '').replace(';', ', ')}>"
        for a in git_authors
    )
    prompt = PROMPT.format(ai_users=ai_lines, git_authors=git_lines)

    print(f"→ calling {_model()} with {len(ai_users)} ai users × "
          f"{len(git_authors)} unmatched git authors")

    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        json={
            "model": _model(),
            "messages": [
                {"role": "system",
                 "content": "You are a careful entity-resolution assistant. "
                            "Reply with valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        },
        timeout=120,
    )
    if r.status_code != 200:
        print(f"ERROR {r.status_code}: {r.text[:400]}", file=sys.stderr)
        sys.exit(3)
    body = r.json()
    content = body["choices"][0]["message"]["content"]
    try:
        mapping = json.loads(content)
    except json.JSONDecodeError as e:
        print(f"ERROR parsing JSON from model: {e}\nRaw:\n{content[:600]}",
              file=sys.stderr)
        sys.exit(4)
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Write matches to git_authors.user_id. Without "
                             "this flag, the script only prints the proposed "
                             "mapping for review.")
    args = parser.parse_args()

    ai_users, git_authors = _gather()
    print(f"  {len(ai_users)} AI users · {len(git_authors)} unmatched git authors")
    if not git_authors:
        print("Nothing to match — every git author already linked.")
        return 0

    mapping = _call_llm(ai_users, git_authors)
    ai_by_id = {u["id"]: u for u in ai_users}

    matched = 0
    for git_name, ai_id in mapping.items():
        if ai_id is None:
            print(f"  {git_name:<32}  → (no match)")
            continue
        ai = ai_by_id.get(int(ai_id))
        if not ai:
            print(f"  {git_name:<32}  → bad ai_id={ai_id}, skipping")
            continue
        print(f"  {git_name:<32}  → {ai_id:>4}  {ai['full_name']}  <{ai.get('email') or ''}>")
        matched += 1

    print(f"\n{matched} / {len(git_authors)} git authors got a candidate match.")

    if not args.apply:
        print("\nDry run. Re-run with --apply to write to DB.")
        return 0

    with get_conn() as conn:
        for git_name, ai_id in mapping.items():
            if ai_id is None:
                continue
            try:
                ai_id_int = int(ai_id)
            except (TypeError, ValueError):
                continue
            if ai_id_int not in ai_by_id:
                continue
            conn.execute(
                "UPDATE git_authors SET user_id = ? WHERE name = ?",
                (ai_id_int, git_name),
            )
            # Also propagate to git_author_repo_stats (per-repo rollup)
            conn.execute(
                "UPDATE git_author_repo_stats SET user_id = ? WHERE name = ?",
                (ai_id_int, git_name),
            )
        conn.commit()
    print(f"✓ wrote {matched} matches to DB. Refresh the dashboard tab.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
