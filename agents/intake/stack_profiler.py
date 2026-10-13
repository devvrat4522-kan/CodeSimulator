from agents.intake.file_picker import pack_files, pick_stack_files
from agents.llm import LLMError, complete_json
from agents.prompts import STACK_PROFILER_SYSTEM, STACK_PROFILER_USER


def profile_stack(file_rows, workspace_path: str) -> dict:
    chosen = pick_stack_files(file_rows, workspace_path)
    if not chosen:
        return {
            "languages": [],
            "backend": None,
            "frontend": None,
            "databases": [],
            "likely_run_commands": [],
            "evidence": [],
            "notes": "no stack signal files found",
        }
    user = STACK_PROFILER_USER.format(file_pack=pack_files(chosen))
    try:
        profile = complete_json(STACK_PROFILER_SYSTEM, user)
    except LLMError as exc:
        return {
            "languages": sorted({row["language"] for row in file_rows if row.get("language")}),
            "backend": None,
            "frontend": None,
            "databases": [],
            "likely_run_commands": [],
            "evidence": [item["path"] for item in chosen],
            "notes": f"llm failed: {exc}",
        }
    profile["files_sent"] = [item["path"] for item in chosen]
    return profile
