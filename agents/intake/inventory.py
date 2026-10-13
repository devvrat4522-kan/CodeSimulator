import hashlib
import re
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".tox"}

LANG_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".sql": "sql",
    ".sh": "shell",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
}

CONFIG_NAMES = {
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "makefile",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "cargo.toml",
    "pom.xml",
    ".env",
    ".env.example",
}

SECRET_PATTERNS = [
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----")),
    ("github_token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("generic_secret", re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]")),
]


def classify(rel_path: Path):
    parts = {p.lower() for p in rel_path.parts}
    name = rel_path.name.lower()
    if "node_modules" in parts or "vendor" in parts or ".venv" in parts or "venv" in parts:
        return "vendored"
    if "dist" in parts or "build" in parts or name.endswith(".min.js"):
        return "generated"
    if (
        "test" in parts
        or "tests" in parts
        or name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    ):
        return "test"
    if name in CONFIG_NAMES or name.endswith((".yml", ".yaml", ".toml", ".ini", ".cfg", ".env")):
        return "config"
    if rel_path.suffix.lower() in LANG_BY_EXT:
        return "source"
    return "other"


def language_of(rel_path: Path):
    return LANG_BY_EXT.get(rel_path.suffix.lower())


def mask(value: str):
    if len(value) <= 6:
        return "***"
    return value[:2] + "***" + value[-2:]


def walk_files(workspace_path: str):
    root = Path(workspace_path)
    rows = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root)
        data = path.read_bytes()
        rows.append(
            {
                "path": rel.as_posix(),
                "size_bytes": len(data),
                "content_hash": hashlib.sha256(data).hexdigest(),
                "language": language_of(rel),
                "label": classify(rel),
                "abs_path": path,
            }
        )
    return rows


def scan_secrets(file_rows):
    findings = []
    for row in file_rows:
        if row["label"] in {"vendored", "generated"}:
            continue
        try:
            text = row["abs_path"].read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in SECRET_PATTERNS:
                match = pattern.search(line)
                if match:
                    findings.append(
                        {
                            "file_path": row["path"],
                            "line_no": line_no,
                            "kind": kind,
                            "masked": mask(match.group(0)),
                        }
                    )
    return findings


def run_intake(conn, job_id, workspace_path):
    files = walk_files(workspace_path)
    findings = scan_secrets(files)
    for row in files:
        conn.execute(
            """
            INSERT INTO files (job_id, path, size_bytes, content_hash, language, label)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (job_id, row["path"], row["size_bytes"], row["content_hash"], row["language"], row["label"]),
        )
    for finding in findings:
        conn.execute(
            """
            INSERT INTO secret_findings (job_id, file_path, line_no, kind, masked)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (job_id, finding["file_path"], finding["line_no"], finding["kind"], finding["masked"]),
        )
    return {"file_count": len(files), "secret_count": len(findings), "files": files}
