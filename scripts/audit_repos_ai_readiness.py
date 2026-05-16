"""Scan hmnd, hmnd-cloud, hmnd-sim for AI-codegen readiness signals.

For Report II — Technical Repository Audit & AI-Codegen Readiness.
Output is plain text; paste back to chat so I can write Report II with
real evidence (not made-up assumptions).

What it checks per repo:
  1. Top-level structure (max-depth 2 dirs)
  2. AI-agent instruction files (AGENTS.md, CLAUDE.md, .cursor/rules,
     .github/copilot-instructions.md, .aiderignore, etc.)
  3. Documentation structure (docs/, architecture/, ADR/, RFC/, specs/)
  4. Test structure (tests/, test/, __tests__/, by language)
  5. CI/CD configs (.github/workflows/, .gitlab-ci.yml, .circleci/)
  6. Build / package manifests (pyproject.toml, package.json, Cargo.toml,
     MODULE.bazel, pixi.toml, etc.)
  7. README quality (line count, presence of key sections)
  8. Generated / vendor code markers (third_party/, vendor/, generated/,
     *.lock files dominance)
  9. Language mix (top extensions by file count)

Repos are expected to be cloned next to this repo OR via HMND_REPO_BASE.

Usage:
    # If you cloned the 3 repos somewhere:
    HMND_REPO_BASE=/path/to/parent docker compose exec -T dashboard \\
        python -m scripts.audit_repos_ai_readiness

    # Or pass paths explicitly:
    docker compose exec -T -e HMND_REPO_PATH_HMND=/repos/hmnd \\
                          -e HMND_REPO_PATH_HMND_CLOUD=/repos/hmnd-cloud \\
                          -e HMND_REPO_PATH_HMND_SIM=/repos/hmnd-sim \\
        dashboard python -m scripts.audit_repos_ai_readiness

    # Or clone fresh (needs HMND_GITHUB_PAT in env):
    docker compose exec -T dashboard python -m scripts.audit_repos_ai_readiness --clone
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path


REPOS = ["hmnd", "hmnd-cloud", "hmnd-sim"]

# AI-agent instruction files we want to find
AGENT_INSTRUCTION_FILES = [
    "AGENTS.md", "CLAUDE.md", "GEMINI.md", "AI.md", "AI_AGENTS.md",
    ".cursor/rules", ".cursor/rules.md", ".cursorrules",
    ".github/copilot-instructions.md", ".github/instructions.md",
    ".aiderignore", ".aider.conf.yml",
    ".windsurfrules", ".roocode.md",
    "docs/ai/", "docs/agents/",
]

# Spec / docs dirs we want to find
DOC_DIRS = [
    "docs", "doc", "documentation",
    "architecture", "arch",
    "ADR", "adr", "docs/adr",
    "RFC", "rfc", "docs/rfc",
    "specs", "spec", "docs/specs",
    "design", "docs/design",
]

# Test dir / file patterns
TEST_PATTERNS = [
    "tests", "test", "__tests__", "spec",  # dirs
    "*_test.py", "test_*.py",  # python
    "*.test.ts", "*.test.tsx", "*.test.js",  # js/ts
    "*_test.go",  # go
    "*_test.cc", "*_test.cpp",  # cpp
]

# CI config locations
CI_FILES = [
    ".github/workflows",
    ".gitlab-ci.yml",
    ".circleci/config.yml",
    "azure-pipelines.yml",
    "Jenkinsfile",
    ".buildkite",
    ".drone.yml",
    ".woodpecker.yml",
]

# Vendor / generated code markers
VENDOR_DIRS = [
    "third_party", "vendor", "external", "generated", "gen",
    "node_modules", ".venv", "build", "dist", "target",
]

# Build / package manifests
MANIFESTS = [
    "pyproject.toml", "setup.py", "requirements.txt", "Pipfile",
    "package.json", "yarn.lock", "pnpm-lock.yaml",
    "Cargo.toml",
    "go.mod",
    "pom.xml", "build.gradle",
    "MODULE.bazel", "WORKSPACE", "BUILD",
    "pixi.toml", "pixi.lock",
    "conanfile.txt", "vcpkg.json",
    "CMakeLists.txt",
    "Dockerfile", "docker-compose.yml",
]


def _exists(repo: Path, rel: str) -> bool:
    return (repo / rel).exists()


def _find_file(repo: Path, name: str, max_results: int = 5) -> list[str]:
    """Find files matching `name` (case-insensitive) up to `max_results`."""
    try:
        out = subprocess.run(
            ["find", str(repo), "-maxdepth", "4", "-iname", name],
            capture_output=True, text=True, timeout=30,
        )
        files = [l for l in out.stdout.strip().split("\n") if l]
        return [str(Path(f).relative_to(repo)) for f in files[:max_results]]
    except Exception:
        return []


def _count_files(repo: Path, *patterns: str) -> int:
    """Count files matching any of the patterns. Each pattern is passed
    to `find -iname`.
    """
    total = 0
    for p in patterns:
        try:
            out = subprocess.run(
                ["find", str(repo), "-type", "f", "-iname", p],
                capture_output=True, text=True, timeout=30,
            )
            total += len([l for l in out.stdout.strip().split("\n") if l])
        except Exception:
            pass
    return total


def _top_level_dirs(repo: Path) -> list[str]:
    """List top-level directories (depth 1), excluding hidden."""
    try:
        return sorted(
            p.name for p in repo.iterdir()
            if p.is_dir() and not p.name.startswith(".") and p.name not in VENDOR_DIRS
        )
    except Exception:
        return []


def _hidden_top_level(repo: Path) -> list[str]:
    try:
        return sorted(
            p.name for p in repo.iterdir()
            if p.is_dir() and p.name.startswith(".")
        )
    except Exception:
        return []


def _file_count(repo: Path) -> int:
    try:
        out = subprocess.run(
            ["bash", "-c",
             f"find {repo} -type f -not -path '*/\\.git/*' -not -path '*/node_modules/*' "
             f"-not -path '*/.venv/*' -not -path '*/build/*' | wc -l"],
            capture_output=True, text=True, timeout=60,
        )
        return int(out.stdout.strip() or 0)
    except Exception:
        return 0


def _ext_breakdown(repo: Path, top_n: int = 10) -> list[tuple[str, int]]:
    """Top file extensions by count, excluding vendor/build dirs."""
    try:
        out = subprocess.run(
            ["bash", "-c",
             f"find {repo} -type f -not -path '*/\\.git/*' -not -path '*/node_modules/*' "
             f"-not -path '*/.venv/*' -not -path '*/build/*' -not -path '*/third_party/*' "
             f"-not -path '*/vendor/*' "
             f"| awk -F. 'NF>1 {{print tolower($NF)}}' | sort | uniq -c | sort -rn | head -{top_n}"],
            capture_output=True, text=True, timeout=60,
        )
        out_pairs = []
        for line in out.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                out_pairs.append((parts[1], int(parts[0])))
        return out_pairs
    except Exception:
        return []


def _readme_quality(repo: Path) -> dict:
    """Look at README and assess basic quality signals."""
    candidates = ["README.md", "README.rst", "README.txt", "README"]
    for c in candidates:
        p = repo / c
        if p.exists():
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
                lines = text.count("\n")
                has_install = "install" in text.lower() or "setup" in text.lower()
                has_usage = "usage" in text.lower() or "example" in text.lower() or "getting started" in text.lower()
                has_build = "build" in text.lower() or "make " in text.lower() or "bazel" in text.lower() or "pixi" in text.lower()
                has_test = "test" in text.lower()
                has_arch = "architect" in text.lower() or "design" in text.lower()
                return {
                    "file": c,
                    "lines": lines,
                    "has_install": has_install,
                    "has_usage": has_usage,
                    "has_build": has_build,
                    "has_test": has_test,
                    "has_arch": has_arch,
                }
            except Exception:
                pass
    return {"file": None, "lines": 0}


def _ci_present(repo: Path) -> list[str]:
    out = []
    for ci in CI_FILES:
        p = repo / ci
        if p.exists():
            if p.is_dir():
                # Count workflows
                try:
                    yml_count = sum(1 for f in p.iterdir() if f.suffix in (".yml", ".yaml"))
                    out.append(f"{ci}/ ({yml_count} workflows)")
                except Exception:
                    out.append(ci)
            else:
                out.append(ci)
    return out


def _manifests_present(repo: Path) -> list[str]:
    return [m for m in MANIFESTS if _exists(repo, m)]


def _audit_one_repo(name: str, path: Path) -> None:
    print(f"\n{'=' * 70}\n  REPO: {name}\n  PATH: {path}\n{'=' * 70}")
    if not path.exists():
        print(f"  ✗ PATH DOES NOT EXIST")
        return

    # 1. Top-level structure
    dirs = _top_level_dirs(path)
    hidden = _hidden_top_level(path)
    print(f"\n  Top-level dirs ({len(dirs)}):")
    for d in dirs[:30]:
        print(f"    {d}/")
    if len(dirs) > 30:
        print(f"    ... +{len(dirs)-30} more")
    print(f"  Hidden dirs: {', '.join(hidden) if hidden else '(none)'}")

    # 2. AI-agent instructions
    print(f"\n  AI-agent instruction files:")
    found_any = False
    for f in AGENT_INSTRUCTION_FILES:
        if _exists(path, f):
            print(f"    ✓ {f}")
            found_any = True
    if not found_any:
        print(f"    ✗ NONE found ({len(AGENT_INSTRUCTION_FILES)} checked)")

    # 3. Docs / specs
    print(f"\n  Documentation dirs present:")
    found_docs = []
    for d in DOC_DIRS:
        if _exists(path, d):
            try:
                n = sum(1 for _ in (path / d).rglob("*"))
            except Exception:
                n = 0
            found_docs.append((d, n))
            print(f"    ✓ {d}/  ({n} entries)")
    if not found_docs:
        print(f"    ✗ NONE found")

    # ADR/RFC presence
    adr_count = _count_files(path, "ADR-*", "adr-*", "*.adr.md")
    rfc_count = _count_files(path, "RFC-*", "rfc-*", "*.rfc.md")
    if adr_count or rfc_count:
        print(f"    ADRs: {adr_count}, RFCs: {rfc_count}")

    # 4. Tests
    print(f"\n  Test artefacts:")
    test_dirs_found = []
    for tp in ["tests", "test", "__tests__", "spec"]:
        if _exists(path, tp):
            try:
                n = sum(1 for _ in (path / tp).rglob("*.py") if _.is_file())
                n += sum(1 for _ in (path / tp).rglob("*.ts") if _.is_file())
                n += sum(1 for _ in (path / tp).rglob("*.js") if _.is_file())
                n += sum(1 for _ in (path / tp).rglob("*_test.cc") if _.is_file())
                n += sum(1 for _ in (path / tp).rglob("*_test.cpp") if _.is_file())
                n += sum(1 for _ in (path / tp).rglob("*_test.go") if _.is_file())
            except Exception:
                n = 0
            print(f"    ✓ {tp}/  ({n} test files)")
            test_dirs_found.append(tp)

    # Distributed tests (next to source)
    distributed = (
        _count_files(path, "*_test.py")
        + _count_files(path, "test_*.py")
        + _count_files(path, "*.test.ts")
        + _count_files(path, "*_test.cc")
        + _count_files(path, "*_test.cpp")
        + _count_files(path, "*_test.go")
    )
    print(f"    Distributed test files (next to source): {distributed}")

    # 5. CI/CD
    ci = _ci_present(path)
    print(f"\n  CI/CD:")
    if ci:
        for c in ci:
            print(f"    ✓ {c}")
    else:
        print(f"    ✗ NO CI configured")

    # 6. Build/package manifests
    mans = _manifests_present(path)
    print(f"\n  Build/package manifests ({len(mans)}):")
    for m in mans:
        print(f"    ✓ {m}")

    # 7. README quality
    rd = _readme_quality(path)
    print(f"\n  README:")
    if rd["file"]:
        print(f"    file={rd['file']}  lines={rd['lines']}")
        print(f"    sections — install:{rd['has_install']}  usage:{rd['has_usage']}  "
              f"build:{rd['has_build']}  test:{rd['has_test']}  arch:{rd['has_arch']}")
    else:
        print(f"    ✗ NO README")

    # 8. Vendor / generated code markers
    print(f"\n  Vendor / generated dirs present:")
    found_vendor = [v for v in VENDOR_DIRS if _exists(path, v)]
    if found_vendor:
        for v in found_vendor:
            print(f"    ! {v}/")
    else:
        print(f"    (none)")

    # 9. File count + extension breakdown
    fc = _file_count(path)
    print(f"\n  Total files (excl. .git/vendor): {fc:,}")
    print(f"  Top extensions:")
    for ext, n in _ext_breakdown(path):
        print(f"    .{ext:8s}  {n:>6,}")


def _resolve_repo_path(name: str) -> Path:
    """Pick a path for the repo from env or default to ~/hmnd_repos/<name>."""
    env_var = f"HMND_REPO_PATH_{name.upper().replace('-', '_')}"
    if env_var in os.environ:
        return Path(os.environ[env_var])
    base = os.environ.get("HMND_REPO_BASE", str(Path.home() / "hmnd_repos"))
    return Path(base) / name


def _clone_repos(target_dir: Path) -> None:
    """Clone the 3 repos using HMND_GITHUB_PAT into target_dir."""
    pat = os.environ.get("HMND_GITHUB_PAT") or os.environ.get("GITHUB_PAT")
    if not pat:
        print("ERROR: HMND_GITHUB_PAT or GITHUB_PAT env var required for --clone")
        sys.exit(1)
    target_dir.mkdir(parents=True, exist_ok=True)
    org = os.environ.get("HMND_GITHUB_ORG", "thehumanoid-com")
    for repo in REPOS:
        dst = target_dir / repo
        if dst.exists():
            print(f"  {repo}: already cloned at {dst}, skipping")
            continue
        url = f"https://{pat}@github.com/{org}/{repo}.git"
        print(f"  cloning {repo}...")
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dst)],
            check=True,
        )
        print(f"  ✓ {repo} cloned to {dst}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clone", action="store_true",
                        help="Shallow-clone the 3 repos before scanning "
                             "(needs HMND_GITHUB_PAT)")
    args = parser.parse_args()

    if args.clone:
        clone_dst = Path(os.environ.get("HMND_REPO_BASE",
                                         str(Path.home() / "hmnd_repos")))
        print(f"Cloning to {clone_dst}")
        _clone_repos(clone_dst)

    print(f"\n{'#' * 70}")
    print(f"#  Report II — AI-CODEGEN READINESS SCAN")
    print(f"#  Scanning {len(REPOS)} repos: {', '.join(REPOS)}")
    print(f"{'#' * 70}")

    for name in REPOS:
        path = _resolve_repo_path(name)
        _audit_one_repo(name, path)

    print(f"\n{'#' * 70}")
    print(f"#  END OF SCAN — paste the output back to chat")
    print(f"#  Report II writer will use this to assess each repo's")
    print(f"#  AI-codegen readiness against 6 criteria (agent instructions,")
    print(f"#  specs, tests, modules, CI/CD, safety-critical protection).")
    print(f"{'#' * 70}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
