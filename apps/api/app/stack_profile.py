from pathlib import Path

from app.llm import LlmError, complete
from app.prompts import STACK_PROFILE_SYSTEM, STACK_PROFILE_USER

SKIP_NAMES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".env.staging",
    "credentials.json",
    "secrets.yaml",
    "id_rsa",
}

SKIP_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}

STACK_NAMES = {
    "readme",
    "readme.md",
    "readme.rst",
    "readme.txt",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "pipfile",
    "setup.py",
    "setup.cfg",
    "environment.yml",
    "go.mod",
    "cargo.toml",
    "pom.xml",
    "build.gradle",
    "gemfile",
    "composer.json",
    "mix.exs",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "makefile",
    "procfile",
    "manage.py",
    "angular.json",
    "nest-cli.json",
}

STACK_PREFIXES = (
    "vite.config.",
    "next.config.",
    "nuxt.config.",
    "astro.config.",
    "webpack.config.",
)

MAX_FILES = 12
MAX_CHARS = 4000


def _is_stack_file(rel_path: str):
    name = Path(rel_path).name.lower()
    if name in SKIP_NAMES or name.startswith(".env"):
        return False
    if Path(rel_path).suffix.lower() in SKIP_SUFFIXES:
        return False
    if name in STACK_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in STACK_PREFIXES)


def pick_stack_files(file_rows, secret_paths):
    secret_paths = set(secret_paths)
    candidates = []
    for row in file_rows:
        if row["label"] in {"vendored", "generated"}:
            continue
        if row["path"] in secret_paths:
            continue
        if not _is_stack_file(row["path"]):
            continue
        depth = row["path"].count("/")
        name = Path(row["path"]).name.lower()
        rank = 0 if name.startswith("readme") else 1
        candidates.append((rank, depth, row["path"], row["abs_path"]))
    candidates.sort()
    chosen = []
    for _, _, rel, abs_path in candidates[:MAX_FILES]:
        try:
            text = abs_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        chosen.append({"path": rel, "content": text[:MAX_CHARS]})
    return chosen


def build_stack_profile(file_rows, secret_paths):
    picked = pick_stack_files(file_rows, secret_paths)
    if not picked:
        return {
            "languages": [],
            "backend": None,
            "frontend": None,
            "database": None,
            "likely_run": [],
            "entry_points": [],
            "evidence": [],
            "summary": "No stack-related files were found.",
        }
    packed = "\n\n".join(
        f"--- {item['path']} ---\n{item['content']}" for item in picked
    )
    try:
        profile = complete(
            STACK_PROFILE_SYSTEM,
            STACK_PROFILE_USER.format(files=packed),
            json_mode=True,
        )
    except LlmError as exc:
        return {
            "languages": [],
            "backend": None,
            "frontend": None,
            "database": None,
            "likely_run": [],
            "entry_points": [],
            "evidence": [item["path"] for item in picked],
            "summary": None,
            "error": str(exc),
        }
    if not isinstance(profile, dict):
        return {"error": "invalid profile", "evidence": [item["path"] for item in picked]}
    profile["files_sent"] = [item["path"] for item in picked]
    return profile
