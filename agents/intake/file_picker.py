from pathlib import Path

EXACT_NAMES = {
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
    "go.mod",
    "cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "gemfile",
    "composer.json",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "makefile",
    "manage.py",
    "angular.json",
    "next.config.js",
    "next.config.mjs",
    "next.config.ts",
    "vite.config.js",
    "vite.config.ts",
    "nuxt.config.js",
    "nuxt.config.ts",
    "mix.exs",
    "pubspec.yaml",
    "cmakelists.txt",
}

BLOCKED_NAMES = {".env", ".env.local", ".env.production", "credentials.json", "id_rsa"}
MAX_FILES = 12
MAX_CHARS = 6000


def is_stack_signal(rel_path: str) -> bool:
    name = Path(rel_path).name.lower()
    if name in BLOCKED_NAMES:
        return False
    if name.startswith(".env") and name != ".env.example":
        return False
    if name in EXACT_NAMES:
        return True
    if name.endswith(".csproj") or name.endswith(".sln"):
        return True
    return False


def pick_stack_files(file_rows, workspace_path: str):
    root = Path(workspace_path)
    chosen = []
    for row in file_rows:
        if row["label"] in {"vendored", "generated", "test"}:
            continue
        if not is_stack_signal(row["path"]):
            continue
        abs_path = row.get("abs_path") or (root / row["path"])
        try:
            text = Path(abs_path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        chosen.append({"path": row["path"], "content": text[:MAX_CHARS]})
        if len(chosen) >= MAX_FILES:
            break
    return chosen


def pack_files(chosen) -> str:
    blocks = []
    for item in chosen:
        blocks.append(f"### {item['path']}\n{item['content']}")
    return "\n\n".join(blocks)
