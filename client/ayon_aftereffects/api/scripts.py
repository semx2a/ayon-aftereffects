from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any, Optional

from ayon_core.lib import Logger, StringTemplate
from ayon_core.pipeline.template_data import get_template_data

log = Logger.get_logger("ayon_aftereffects.scripts")


def resolve_scripts_paths(
    data: dict[str, Any],
    launch_env: dict[str, str],
) -> list[str]:
    """Resolve active script paths from launch context settings.

    Args:
        data: Launch context data dictionary.
        launch_env: Launch environment dictionary.

    Returns:
        Ordered list of existing absolute script paths.
    """
    profiles = _get_script_profiles(data)
    if not profiles:
        log.debug("No script profiles found in project settings.")
        return []

    current_platform = platform.system().lower()
    template_data = _get_template_data(
        data=data,
        launch_env=launch_env,
        host_name="aftereffects",
    )
    resolved_paths: list[str] = []

    for profile in profiles:
        if not profile.get("active", True):
            continue

        raw_path = (profile.get("path") or {}).get(current_platform)
        if not raw_path:
            continue

        path = _resolve_path(raw_path, template_data)
        if not path:
            continue

        resolved_paths.append(path)

    return _filter_existing_paths(resolved_paths)


def _get_script_profiles(
    data: dict[str, Any],
) -> Optional[list[dict[str, Any]]]:
    """Return script profiles from aftereffects project settings."""
    project_settings = data.get("project_settings")
    if not project_settings:
        return None

    aftereffects_settings = project_settings.get("aftereffects")
    script_list = aftereffects_settings.get("script_list")
    return script_list.get("profiles")


def _get_template_data(
    data: dict[str, Any],
    launch_env: dict[str, str],
    host_name: str,
) -> dict[str, Any]:
    """Build template context for script path formatting."""
    template_data: dict[str, Any] = dict(launch_env)
    template_data["platform"] = platform.system().lower()

    workdir_data = data.get("workdir_data")
    if workdir_data:
        template_data.update(workdir_data)
    else:
        project_entity = data.get("project_entity")
        folder_entity = data.get("folder_entity")
        task_entity = data.get("task_entity")
        if project_entity and folder_entity and task_entity:
            generated = get_template_data(
                project_entity,
                folder_entity,
                task_entity,
                host_name,
                data.get("project_settings"),
            )
            template_data.update(generated)

    anatomy = data.get("anatomy")
    if anatomy is not None:
        template_data["root"] = anatomy.roots

    return template_data


def _resolve_path(
    raw_path: str,
    template_data: dict[str, Any],
) -> Optional[str]:
    """Resolve one configured script path."""
    if "{" in raw_path:
        result = StringTemplate.format_template(raw_path, template_data)
        if not result.solved:
            log.warning("Could not resolve script template path: %s", raw_path)
            return None
        raw_path = str(result.normalized())

    return os.path.normpath(os.path.expandvars(os.path.expanduser(raw_path)))


def _filter_existing_paths(paths: list[str]) -> list[str]:
    """Keep unique existing paths while preserving order."""
    output: list[str] = []
    seen: set[str] = set()

    for path in paths:
        script_path = Path(path).expanduser()
        key = _normalize_path(str(script_path))
        if key in seen:
            continue

        if not script_path.exists():
            log.warning("Script path does not exist: %s", script_path)
            continue

        seen.add(key)
        output.append(str(script_path))

    return output


def _normalize_path(path: str) -> str:
    """Normalize filesystem path for comparison."""
    return os.path.normcase(os.path.realpath(os.path.normpath(path)))
