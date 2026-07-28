"""Helpers shared by the After Effects launch hooks.

Launch hooks are discovered and imported from their file path, not as a
package, so they cannot import each other. Anything that more than one
hook needs lives here instead.
"""
from __future__ import annotations

import os
from typing import Any, Optional

# Path of the workfile whose lock the artist chose to ignore in the
#   prelaunch dialog. Set by 'CheckWorkfileLock' and consumed once by
#   'on_workfile_opened', which would otherwise ask about the same lock a
#   second time. The panel cannot read AYON settings, and neither can the
#   hook reach into the session it is about to start - an env var is the
#   only channel between the two.
WORKFILE_LOCK_OVERRIDE_ENV = "AYON_AFTEREFFECTS_WORKFILE_LOCK_OVERRIDE"


def resolve_workfile_path(data: dict[str, Any]) -> Optional[str]:
    """Workfile that After Effects will be launched with.

    Args:
        data (dict[str, Any]): Launch context data.

    Returns:
        Optional[str]: Path to the workfile, or ``None`` when After
            Effects is launched without one.

    """
    workfile_path = data.get("workfile_path")
    if workfile_path:
        return workfile_path

    if not data.get("start_last_workfile"):
        return None

    workfile_path = data.get("last_workfile_path")
    if workfile_path and os.path.exists(workfile_path):
        return workfile_path
    return None
