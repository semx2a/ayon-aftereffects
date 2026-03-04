from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from ayon_aftereffects.api.ws_stub import ConnectionNotEstablishedYet, get_stub
from ayon_applications import LaunchTypes, PostLaunchHook


class RunJsxAfterWorkfileHook(PostLaunchHook):
    """Run a JSX file after the expected workfile is loaded in AE."""

    app_groups = {"aftereffects"}
    launch_types = {LaunchTypes.local}
    order = 100

    timeout_seconds: int = 90
    poll_interval_seconds: float = 0.5

    def execute(self) -> None:
        """Wait for workfile load and then execute JSX through websocket."""
        jsx_path = self._get_jsx_path()
        if jsx_path is None:
            self.log.debug("No JSX path configured. Skipping.")
            return

        expected_workfile = self._get_expected_workfile()
        if expected_workfile is None:
            self.log.debug("No expected workfile path. Skipping.")
            return

        if not self._wait_for_workfile(expected_workfile):
            self.log.warning(
                "Workfile was not loaded within %s seconds: %s",
                self.timeout_seconds,
                expected_workfile,
            )
            return

        get_stub().run_jsx_file(str(jsx_path))
        self.log.info("Executed post-launch JSX via websocket: %s", jsx_path)

    def _get_jsx_path(self) -> Optional[Path]:
        """Resolve JSX path from launch data or env.

        Returns:
            Resolved path when valid, else None.
        """
        raw_path = self.data.get(
            "post_launch_jsx_path"
        ) or self.launch_context.env.get("AYON_AFTEREFFECTS_POST_LAUNCH_JSX")
        if not raw_path:
            return None

        jsx_path = Path(raw_path).expanduser()
        if not jsx_path.exists():
            self.log.warning("JSX path does not exist: %s", jsx_path)
            return None
        return jsx_path

    def _get_expected_workfile(self) -> Optional[str]:
        """Get expected workfile path that should be loaded before JSX.

        Returns:
            Workfile path when available, else None.
        """
        if not self.data.get("start_last_workfile"):
            return None

        path = self.data.get("last_workfile_path")
        if not path or not os.path.exists(path):
            return None
        return path

    def _wait_for_workfile(self, expected_workfile: str) -> bool:
        """Wait until expected workfile is active in AE.

        Args:
            expected_workfile: Path expected to be loaded in AE.

        Returns:
            True if loaded before timeout, otherwise False.
        """
        expected = self._normalize_path(expected_workfile)
        deadline = time.monotonic() + self.timeout_seconds

        while time.monotonic() < deadline:
            process = self.launch_context.process
            if process and process.poll() is not None:
                return False

            active = self._get_active_workfile()
            if active and self._normalize_path(active) == expected:
                return True

            time.sleep(self.poll_interval_seconds)

        return False

    def _get_active_workfile(self) -> Optional[str]:
        """Get active workfile path from connected AE.

        Returns:
            Active workfile path if available.
        """
        try:
            return get_stub().get_active_document_full_name()
        except ConnectionNotEstablishedYet:
            return None
        except Exception as exc:
            self.log.debug("Could not query active workfile yet: %s", exc)
            return None

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize path for safe comparisons.

        Args:
            path: Any filesystem path.

        Returns:
            Normalized absolute path.
        """
        return os.path.normcase(os.path.realpath(os.path.normpath(path)))
