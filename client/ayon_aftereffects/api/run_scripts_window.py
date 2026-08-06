from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor

from qtpy import QtCore, QtGui, QtWidgets

from ayon_core.style import get_app_icon_path, load_stylesheet

from .scripts import ScriptItem, ScriptRunResult, ScriptService

log = logging.getLogger(__name__)

# How long to keep waiting on After Effects before releasing the dialog.
# The call cannot be cancelled, so this bounds the wait, not the work.
RUN_TIMEOUT_SECONDS = 300.0
POLL_INTERVAL_MS = 100


class RunScriptsWindow(QtWidgets.QDialog):
    """Dialog for manually running configured After Effects scripts."""

    def __init__(
        self,
        service: ScriptService,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)

        self._service = service
        self._items_by_id: dict[str, ScriptItem] = {}

        # the dialog is cached and reused by AEHostToolsHelper, so the
        # executor outlives a close and must not be shut down there
        self._executor: ThreadPoolExecutor | None = None
        self._future: Future | None = None
        self._run_started_at = 0.0

        self.setWindowTitle("Run Scripts")
        self.setWindowIcon(QtGui.QIcon(get_app_icon_path()))
        self.resize(720, 420)

        self._scripts_view = QtWidgets.QTreeWidget(self)
        self._scripts_view.setColumnCount(3)
        self._scripts_view.setHeaderLabels(["Name", "Path", "Status"])
        self._scripts_view.setRootIsDecorated(False)
        self._scripts_view.setAlternatingRowColors(True)
        self._scripts_view.setUniformRowHeights(True)
        self._scripts_view.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self._scripts_view.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers
        )

        header = self._scripts_view.header()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)

        self._status_label = QtWidgets.QLabel(self)
        self._status_label.setWordWrap(True)

        buttons_widget = QtWidgets.QWidget(self)
        self._refresh_btn = QtWidgets.QPushButton("Refresh", buttons_widget)
        self._run_btn = QtWidgets.QPushButton("Run", buttons_widget)
        self._close_btn = QtWidgets.QPushButton("Close", buttons_widget)
        self._run_btn.setEnabled(False)

        buttons_layout = QtWidgets.QHBoxLayout(buttons_widget)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(10)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self._refresh_btn, 0)
        buttons_layout.addWidget(self._run_btn, 0)
        buttons_layout.addWidget(self._close_btn, 0)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        layout.addWidget(self._scripts_view, 1)
        layout.addWidget(self._status_label, 0)
        layout.addWidget(buttons_widget, 0)

        self._refresh_btn.clicked.connect(self.refresh)
        self._run_btn.clicked.connect(self._on_run_clicked)
        self._close_btn.clicked.connect(self.close)
        self._scripts_view.itemSelectionChanged.connect(
            self._on_selection_changed
        )
        self._scripts_view.itemDoubleClicked.connect(
            self._on_item_double_clicked
        )

        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._on_poll_run)

    def showEvent(self, event) -> None:
        """Apply the AYON stylesheet once the dialog is shown."""
        super().showEvent(event)
        self.setStyleSheet(load_stylesheet())

    def refresh(self) -> None:
        """Reload the manual scripts from settings."""
        self._items_by_id = {}
        self._scripts_view.clear()

        items = self._service.list_manual_items()
        if not items:
            self._status_label.setText("No manual scripts configured.")
            self._run_btn.setEnabled(False)
            return

        for item in items:
            self._items_by_id[item.script_id] = item
            status = "Ready" if item.exists else item.error or "Unavailable"
            tree_item = QtWidgets.QTreeWidgetItem(
                [item.name, item.path, status]
            )
            tree_item.setData(0, QtCore.Qt.UserRole, item.script_id)
            tree_item.setToolTip(1, item.path)
            tree_item.setToolTip(2, status)
            self._scripts_view.addTopLevelItem(tree_item)

        self._scripts_view.setCurrentItem(self._scripts_view.topLevelItem(0))
        self._status_label.setText("Select a script to run.")
        self._on_selection_changed()

    def _on_selection_changed(self) -> None:
        """Update UI state from the current selection."""
        item = self._get_selected_item()
        can_run = bool(item and item.exists)
        self._run_btn.setEnabled(can_run)

        if item is None:
            self._status_label.setText("Select a script to run.")
            return

        if item.exists:
            self._status_label.setText(f"Ready to run: {item.name}")
            return

        self._status_label.setText(
            item.error or "Selected script is unavailable."
        )

    def _on_item_double_clicked(self, *_args) -> None:
        """Run the selected script on double click when possible."""
        if self._run_btn.isEnabled():
            self._on_run_clicked()

    def _on_run_clicked(self) -> None:
        """Run the currently selected manual script."""
        if self._future is not None:
            return

        item = self._get_selected_item()
        if item is None:
            return

        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="ayon-ae-run-scripts"
            )

        self._set_running(True, f"Running {item.name}...")
        self._run_started_at = time.monotonic()
        self._future = self._executor.submit(self._service.run_item, item)
        self._poll_timer.start()

    def _on_poll_run(self) -> None:
        """Check on the running script without blocking the event loop."""
        future = self._future
        if future is None:
            self._poll_timer.stop()
            return

        if future.done():
            self._stop_waiting()
            self._status_label.setText(self._result_message(future))
            return

        if time.monotonic() - self._run_started_at < RUN_TIMEOUT_SECONDS:
            return

        # a blocked websocket call cannot be cancelled, so let it finish in
        # the background rather than hold the dialog hostage
        self._stop_waiting()
        self._status_label.setText(
            f"After Effects did not respond within "
            f"{int(RUN_TIMEOUT_SECONDS)}s. The script may still be running."
        )

    def _stop_waiting(self) -> None:
        """Stop polling and hand the dialog back to the artist."""
        self._poll_timer.stop()
        self._future = None
        self._set_running(False)

    @staticmethod
    def _result_message(future: Future) -> str:
        """Status message for a finished run."""
        try:
            result: ScriptRunResult = future.result()
        except Exception:
            log.warning("Script run failed", exc_info=True)
            return "Script run failed unexpectedly, see the log for details."

        return result.message

    def closeEvent(self, event) -> None:
        """Never block on a running script when the dialog is closed."""
        self._poll_timer.stop()
        self._future = None
        super().closeEvent(event)

    def _set_running(self, running: bool, message: str = "") -> None:
        """Disable input while a script runs."""
        self._run_btn.setEnabled(not running)
        self._refresh_btn.setEnabled(not running)
        self._scripts_view.setEnabled(not running)

        if running:
            self._status_label.setText(message)
            return

        self._on_selection_changed()

    def _get_selected_item(self) -> ScriptItem | None:
        """Return the currently selected script item."""
        selected_items = self._scripts_view.selectedItems()
        if not selected_items:
            return None

        script_id = selected_items[0].data(0, QtCore.Qt.UserRole)
        return self._items_by_id.get(script_id)
