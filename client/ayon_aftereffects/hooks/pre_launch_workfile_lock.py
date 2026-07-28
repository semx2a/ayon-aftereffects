from __future__ import annotations

from ayon_applications import PreLaunchHook, LaunchTypes
from ayon_core.pipeline.workfile import (
    get_workfile_lock_data,
    is_workfile_lock_enabled,
    is_workfile_locked,
)
from ayon_aftereffects.launch_utils import (
    WORKFILE_LOCK_OVERRIDE_ENV,
    resolve_workfile_path,
)


class CheckWorkfileLock(PreLaunchHook):
    """Check the workfile lock before After Effects opens the workfile.

    After Effects receives the workfile as a launch argument and opens it
    natively, so 'open_workfile_with_context' - and the lock check that
    'WorkfileLockMixin' does there - never runs for a launcher-opened
    workfile. This hook is that check for the launcher path.

    A locked workfile is dropped from the launch context rather than
    aborting the launch, so After Effects still starts, just without a
    workfile. The artist can then pick a different one in the Workfiles
    tool.

    Nothing here is specific to After Effects - every host that opens its
    workfile from a launch argument has the same gap. Worth moving to
    ayon-core next to the mixin.
    """

    app_groups = {"aftereffects"}

    # Before every hook that turns the workfile into a launch argument:
    #   'AddLastWorkfileToLaunchArgs' (ayon-core, order 10) and
    #   'AEPrelaunchHook' (order 20). Both decide from 'workfile_path' and
    #   'start_last_workfile', so clearing those is enough to keep the
    #   workfile out of the launch - as long as this runs first. The data
    #   it reads is ready well before: 'GlobalHostDataHook' is order -100
    #   and 'CopyTemplateWorkfile' order 0.
    order = 9
    launch_types = {LaunchTypes.local}

    def execute(self):
        try:
            self._inner_execute()
        except Exception:
            # A lock must never be the reason a launch fails.
            self.log.warning(
                "Workfile lock check failed, launching anyway.",
                exc_info=True,
            )

    def _inner_execute(self) -> None:
        workfile_path = resolve_workfile_path(self.data)
        if not workfile_path:
            return

        project_name = self.data.get("project_name")
        if not project_name:
            return

        if not is_workfile_lock_enabled(
            self.host_name,
            project_name,
            self.data.get("project_settings"),
        ):
            return

        if not is_workfile_locked(workfile_path):
            return

        try:
            lock_data = get_workfile_lock_data(workfile_path)
        except Exception:
            # A broken sidecar must not keep an artist out of a workfile.
            self.log.warning(
                "Could not read the workfile lock of '%s'."
                " Treating the workfile as unlocked.",
                workfile_path,
                exc_info=True,
            )
            return

        if self._confirm_locked_workfile(workfile_path):
            # "Ignore lock" means taking the workfile over. The lock file
            #   is deliberately left alone here - it may belong to a
            #   session that is still running - and the answer is handed
            #   to the After Effects session instead, which overwrites the
            #   lock once the workfile is open. Without this the artist
            #   would be asked about the same lock a second time, by
            #   'on_workfile_opened'.
            self.launch_context.env[WORKFILE_LOCK_OVERRIDE_ENV] = (
                workfile_path
            )
            return

        self.log.info(
            "Workfile '%s' is locked by %s on %s."
            " Starting After Effects without it.",
            workfile_path,
            lock_data.get("username"),
            lock_data.get("hostname"),
        )
        self.data["workfile_path"] = None
        self.data["start_last_workfile"] = False

    def _confirm_locked_workfile(self, workfile_path: str) -> bool:
        """Ask the artist whether to open the locked workfile.

        Deliberately not routed through
        'WorkfileLockMixin.confirm_locked_workfile': there is no host
        instance in the launcher process, and building one would pull the
        whole websocket stack into a launch hook. A host that overrides
        that method is therefore not honoured here.

        Args:
            workfile_path (str): Path to the locked workfile.

        Returns:
            bool: Launch After Effects with the workfile.

        """
        from ayon_core.tools.utils import get_ayon_qt_app
        from ayon_core.tools.workfiles.lock_dialog import WorkfileLockDialog

        # The hook runs before the After Effects session exists, so there
        #   is no Qt application around to show a dialog in yet.
        get_ayon_qt_app()

        dialog = WorkfileLockDialog(workfile_path)
        return bool(dialog.exec_())
