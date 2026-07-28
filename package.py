name = "aftereffects"
title = "AfterEffects"
version = "0.3.6+dev"
app_host_name = "aftereffects"
client_dir = "ayon_aftereffects"
project_can_override_addon_version = True

ayon_server_version = ">=1.1.2"
ayon_required_addons = {
    # 'WorkfileLockMixin', 'resolve_launch_workfile_path' and the
    #   'CheckWorkfileLock' prelaunch hook.
    "core": ">=1.9.9",
}
ayon_compatible_addons = {
    "deadline": ">=0.7.0",
}
