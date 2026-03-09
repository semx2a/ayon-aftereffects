from __future__ import annotations

import os
import platform

from ayon_core.lib import Logger, StringTemplate
from ayon_core.pipeline.context_tools import (
    get_current_context_template_data,
    get_current_project_settings,
)

log = Logger.get_logger("ayon_aftereffects.scripts")


def resolve_scripts() -> list[str]:
    """Resolve active script paths from launch context settings.

    Args:
        None

    Returns:
        Ordered list of existing absolute script paths.
    """

    current_os = platform.system().lower()

    # load configuration of houdini shelves
    project_settings = get_current_project_settings()
    scripts_config = project_settings["aftereffects"]["scripts"]
    paths = scripts_config["paths"]

    if not paths:
        log.debug("No scripts found in project settings.")
        return []

    resolved_paths: list[str] = []
    for path in paths:
        if not path.get("active", True):
            continue

        raw_path = path["path"][current_os]
        if not raw_path:
            continue

        path = resolve_path(raw_path)
        if not path:
            continue

        resolved_paths.append(path)

    return resolved_paths


def resolve_path(path):
    try:
        # Get template data from context_tools
        template_data = get_current_context_template_data()

        # Add environment variables
        template_data.update(os.environ)

        project_name = template_data["project"]["name"]
        anatomy = Anatomy(project_name)
        template_data["root"] = anatomy.roots

        # Format template
        result = StringTemplate.format_template(path, template_data)

        if result.solved:
            path = result.normalized()
            return anatomy.path_remapper(path) or path
    except Exception as e:
        raise e

    return path
