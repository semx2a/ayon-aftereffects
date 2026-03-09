from __future__ import annotations

import os
import platform

from ayon_core.lib import Logger, StringTemplate
from ayon_core.pipeline import Anatomy
from ayon_core.pipeline.context_tools import (
    get_current_context_template_data,
    get_current_project_settings,
)
from ayon_server.graphql.resolvers.common import resolve

from .ws_stub import ConnectionNotEstablishedYet, get_stub

log = Logger.get_logger("ayon_aftereffects.scripts")


def resolve_scripts() -> list[str]:
    """Resolve active post-launch JSX scripts from project settings.

    Returns:
        Ordered list of existing absolute JSX paths.
    """

    current_os = platform.system().lower()

    project_settings = get_current_project_settings()
    scripts_config = project_settings["aftereffects"]["scripts"]
    paths = scripts_config["paths"]

    if not paths:
        log.debug("No scripts found in project settings.")
        return []

    resolved_paths: list[str] = []
    for script_item in paths:
        if not script_item.get("active", True):
            continue

        raw_path = script_item["path"][current_os]
        if not raw_path:
            continue

        resolved_path = resolve_path(raw_path)
        if not resolved_path:
            continue

        if not resolved_path.lower().endswith(".jsx"):
            log.warning(
                f"Skipping unsupported post-launch script: {resolved_path}",
            )
            continue

        if not os.path.isfile(resolved_path):
            log.warning(
                f"Post-launch JSX script does not exist: {resolved_path}",
            )
            continue

        resolved_paths.append(resolved_path)

    return resolved_paths


def resolve_path(path):
    """Resolve a templated script path against current AYON context."""
    template_data = get_current_context_template_data()
    template_data.update(os.environ)

    project_name = template_data["project"]["name"]
    anatomy = Anatomy(project_name)
    template_data["root"] = anatomy.roots

    result = StringTemplate.format_template(path, template_data)
    if result.solved:
        path = result.normalized()
        return anatomy.path_remapper(path) or path

    return path


def run_scripts() -> None:
    """Run jsx scripts in the current AfterEffects host"""
    try:
        stub = get_stub()
    except ConnectionNotEstablishedYet:
        log.warning(
            "After Effects client is not connecte. Skipping jsx script launch."
        )

    resolved_scripts = resolve_scripts()
    for script in resolved_scripts:
        log.info(f"Running post-launch JSX sctipt: {script}")
        stub.run_jsx_file(script)
