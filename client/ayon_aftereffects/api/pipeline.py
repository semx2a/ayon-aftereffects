import os

from qtpy import QtWidgets

import pyblish.api

from ayon_core.lib import Logger, register_event_callback
from ayon_core.pipeline import (
    register_loader_plugin_path,
    register_creator_plugin_path,
    register_workfile_build_plugin_path,
    registered_host,
    AYON_CONTAINER_ID,
    AVALON_INSTANCE_ID,
    AYON_INSTANCE_ID,
)
from ayon_core.pipeline.load import any_outdated_containers
from ayon_core.pipeline.workfile import WorkfileLockMixin
from ayon_core.host import (
    HostBase,
    IWorkfileHost,
    ILoadHost,
    IPublishHost
)
from ayon_core.tools.utils import get_ayon_qt_app
from ayon_aftereffects import AFTEREFFECTS_ADDON_ROOT
from ayon_aftereffects.launch_utils import WORKFILE_LOCK_OVERRIDE_ENV

from .launch_logic import get_stub
from .scripts import run_scripts
from .ws_stub import ConnectionNotEstablishedYet

log = Logger.get_logger(__name__)


PLUGINS_DIR = os.path.join(AFTEREFFECTS_ADDON_ROOT, "plugins")
PUBLISH_PATH = os.path.join(PLUGINS_DIR, "publish")
LOAD_PATH = os.path.join(PLUGINS_DIR, "load")
CREATE_PATH = os.path.join(PLUGINS_DIR, "create")
WORKFILE_BUILD_PATH = os.path.join(PLUGINS_DIR, "workfile_build")


class AfterEffectsHost(
    HostBase, WorkfileLockMixin, IWorkfileHost, ILoadHost, IPublishHost
):
    # 'WorkfileLockMixin' has to come before 'IWorkfileHost' so that the
    #   locking hooks win the method resolution order over the interface
    #   defaults. Releasing the lock is wired in 'ProcessLauncher.exit'.
    name = "aftereffects"

    def __init__(self):
        self._stub = None
        super(AfterEffectsHost, self).__init__()

    @property
    def stub(self):
        """
            Handle pulling stub from PS to run operations on host
        Returns:
            (AEServerStub) or None
        """
        if self._stub:
            return self._stub

        try:
            stub = get_stub()  # only after Photoshop is up
        except ConnectionNotEstablishedYet:
            log.debug("Not connected yet, ignoring")
            return

        self._stub = stub
        return self._stub

    def install(self):
        log.info("Installing AYON After Effects integration...")

        pyblish.api.register_host("aftereffects")
        pyblish.api.register_plugin_path(PUBLISH_PATH)

        register_loader_plugin_path(LOAD_PATH)
        register_creator_plugin_path(CREATE_PATH)
        register_workfile_build_plugin_path(WORKFILE_BUILD_PATH)

        register_event_callback("application.launched", on_application_launch)
        register_event_callback("workfile.opened", on_workfile_opened)

    def get_workfile_extensions(self):
        return [".aep"]

    def save_workfile(self, dst_path=None):
        self.stub.saveAs(dst_path, True)

    def open_workfile(self, filepath):
        self.stub.open(filepath)

        return True

    def get_current_workfile(self):
        try:
            full_name = get_stub().get_active_document_full_name()
            if full_name and full_name != "null":
                return os.path.normpath(full_name).replace("\\", "/")
        except ValueError:
            log.debug("Nothing opened")
            pass

        return None

    def get_containers(self):
        return ls()

    def get_context_data(self):
        meta = self.stub.get_metadata()
        for item in meta:
            if item.get("id") == "publish_context":
                item.pop("id")
                return item

        return {}

    def update_context_data(self, data, changes):
        item = data
        item["id"] = "publish_context"
        self.stub.imprint(item["id"], item)

    # created instances section
    def list_instances(self):
        """List all created instances from current workfile which
        will be published.

        Pulls from File > File Info

        For Scene Inventory (Manage...)

        Returns:
            (list) of dictionaries matching instances format
        """
        stub = self.stub
        if not stub:
            return []

        instances = []
        layers_meta = stub.get_metadata()

        for instance in layers_meta:
            if instance.get("id") in {
                AYON_INSTANCE_ID, AVALON_INSTANCE_ID
            }:
                instances.append(instance)
        return instances

    def remove_instance(self, instance):
        """Remove instance from current workfile metadata.

        Updates metadata of current file in File > File Info and removes
        icon highlight on group layer.

        For Scene Inventory

        Args:
            instance (dict): instance representation from Scene Inventory model
        """
        stub = self.stub

        if not stub:
            return

        inst_id = instance.get("instance_id") or instance.get("uuid")  # legacy
        if not inst_id:
            log.warning("No instance identifier for {}".format(instance))
            return

        stub.remove_instance(inst_id)

        if instance.get("members"):
            item = stub.get_item(instance["members"][0])
            if item:
                stub.rename_item(item.id,
                                 item.name.replace(stub.PUBLISH_ICON, ''))


def on_workfile_opened(event=None):
    """Handle a workfile that was just opened.

    Args:
        event (Optional[Event]): Event carrying the workfile data. Not
            passed by callers that emit the event without it.
    """
    acquire_workfile_lock(event)

    try:
        run_scripts(auto=True)
    except Exception:
        log.exception("Automatic script execution failed.")


def acquire_workfile_lock(event=None):
    """Lock the opened workfile for this session.

    A workfile opened through the Workfiles tool is already locked by
    'WorkfileLockMixin._after_workfile_open'. This covers the launcher
    path, where After Effects opens the '.aep' natively from a launch
    argument and 'open_workfile_with_context' never runs.

    Args:
        event (Optional[Event]): Event carrying the workfile data.
    """
    try:
        host = registered_host()
        if not isinstance(host, WorkfileLockMixin):
            return

        event_data = getattr(event, "data", None) or {}
        filepath = event_data.get("filepath") or host.get_current_workfile()
        if not filepath:
            return

        project_name = event_data.get("project_name")

        # Popped unconditionally so it is honoured exactly once, for the
        #   workfile the launch started with.
        override_path = os.environ.pop(WORKFILE_LOCK_OVERRIDE_ENV, "")
        lock_ignored = bool(override_path) and (
            os.path.normpath(override_path) == os.path.normpath(filepath)
        )

        lock_data = host.get_workfile_lock_holder(
            filepath, project_name=project_name
        )
        if lock_data is not None and not lock_ignored:
            # After Effects already has the workfile open at this point,
            #   so refusing is not on the table anymore. All we can do is
            #   ask, and leave the lock with its owner when the artist
            #   decides against taking the workfile over.
            if not host.confirm_locked_workfile(filepath):
                log.warning(
                    "Workfile '%s' stays locked by %s on %s.",
                    filepath,
                    lock_data.get("username"),
                    lock_data.get("hostname"),
                )
                return

        host.acquire_workfile_lock(filepath, project_name=project_name)
    except Exception:
        log.warning("Failed to lock the opened workfile.", exc_info=True)


def on_application_launch():
    """Triggered after start of app"""
    check_inventory()


def ls():
    """Yields containers from active AfterEffects document.

    This is the host-equivalent of api.ls(), but instead of listing
    assets on disk, it lists assets already loaded in AE; once loaded
    they are called 'containers'. Used in Manage tool.

    Containers could be on multiple levels, single images/videos/was as a
    FootageItem, or multiple items - backgrounds (folder with automatically
    created composition and all imported layers).

    Yields:
        dict: container

    """
    try:
        stub = get_stub()  # only after AfterEffects is up
    except ConnectionNotEstablishedYet:
        log.warning("Not connected yet, ignoring")
        return

    layers_meta = stub.get_metadata()
    for item in stub.get_items(comps=True,
                               folders=True,
                               footages=True):
        data = stub.read(item, layers_meta)
        # Skip non-tagged layers.
        if not data:
            continue

        # Filter to only containers.
        if "container" not in data.get("id", ""):
            continue

        required = ["id", "name", "namespace", "loader", "representation"]
        missing = [key for key in required if key not in data]
        if missing:
            log.warning("Container '%s' is missing required keys: %s",
                        item, missing)
            return

        # Append transient data
        data["objectName"] = item.name.replace(stub.LOADED_ICON, '')
        data["layer"] = item
        yield data


def check_inventory():
    """Checks loaded containers if they are of highest version"""
    if not any_outdated_containers():
        return

    # Warn about outdated containers.
    _app = get_ayon_qt_app()

    message_box = QtWidgets.QMessageBox()
    message_box.setIcon(QtWidgets.QMessageBox.Warning)
    msg = "There are outdated containers in the scene."
    message_box.setText(msg)
    message_box.exec_()


def containerise(name,
                 namespace,
                 comp,
                 context,
                 loader=None,
                 suffix="_CON"):
    """
    Containerisation enables a tracking of version, author and origin
    for loaded assets.

    Creates dictionary payloads that gets saved into file metadata. Each
    container contains of who loaded (loader) and members (single or multiple
    in case of background).

    Arguments:
        name (str): Name of resulting assembly
        namespace (str): Namespace under which to host container
        comp (AEItem): Composition to containerise
        context (dict): Asset information
        loader (str, optional): Name of loader used to produce this container.
        suffix (str, optional): Suffix of container, defaults to `_CON`.

    Returns:
        container (str): Name of container assembly
    """
    data = {
        "schema": "ayon:container-3.0",
        "id": AYON_CONTAINER_ID,
        "name": name,
        "namespace": namespace,
        "loader": str(loader),
        "representation": context["representation"]["id"],
        "members": comp.members or [comp.id]
    }

    stub = get_stub()
    stub.imprint(comp.id, data)

    return comp


def cache_and_get_instances(creator):
    """Cache instances in shared data.

    Storing all instances as a list as legacy instances might be still present.
    Args:
        creator (Creator): Plugin which would like to get instances from host.
    Returns:
        List[]: list of all instances stored in metadata
    """
    shared_key = "ayon.aftereffects.instances"
    if shared_key not in creator.collection_shared_data:
        creator.collection_shared_data[shared_key] = \
            creator.host.list_instances()
    return creator.collection_shared_data[shared_key]
