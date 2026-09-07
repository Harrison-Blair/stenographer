# SPDX-License-Identifier: GPL-3.0-or-later
"""Native widgets, with all persistence, probing and setup on worker threads."""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import json
import logging
import threading
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from stenographer.config import Config
from stenographer.settings import ConfigDocument
from stenographer_desktop.charts import WordTrend
from stenographer_desktop.icons import NAVIGATION
from stenographer_desktop.services import (
    DesktopServices,
    comparison_rows,
    edited_config,
    flatten,
    histogram_rows,
)
from stenographer_desktop.theme import TOKENS, apply_theme, navigation_icon

logger = logging.getLogger(__name__)


class Tasks(QObject):
    """Daemon workers cannot keep the desktop process alive after its window closes."""

    completed = Signal(str, int, object, object)
    progress = Signal(str)

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.generations: dict[str, int] = {}
        self.callbacks: dict[str, object] = {}
        self.completed.connect(self._complete)
        self.closed = False
        self.running: set[str] = set()

    def submit(self, key: str, operation, callback) -> None:
        if key in self.running:
            callback(None, RuntimeError("This operation is already running."))
            return
        self.running.add(key)
        generation = self.generations.get(key, 0) + 1
        self.generations[key] = generation
        self.callbacks[key] = callback

        def work() -> None:
            result = error = None
            try:
                result = operation()
            except Exception as exc:
                error = exc
                # User settings and model errors may contain private text.
                logger.error(
                    "desktop: operation_failed operation=%s error=%s", key, type(exc).__name__
                )
            if not self.closed:
                with contextlib.suppress(RuntimeError):
                    self.completed.emit(key, generation, result, error)

        threading.Thread(target=work, name=f"desktop-{key}", daemon=True).start()

    def _complete(self, key: str, generation: int, result, error) -> None:
        self.running.discard(key)
        if not self.closed and self.generations.get(key) == generation:
            self.callbacks[key](result, error)


class BindingDialog(QDialog):
    """Capture only focused key events while the daemon maintenance lease is held."""

    def __init__(
        self, platform, parent: QWidget, cancellation: threading.Event | None = None
    ) -> None:
        super().__init__(parent)
        self.lease_timer = QTimer(self)
        if cancellation is not None:
            self.lease_timer.setInterval(25)
            self.lease_timer.timeout.connect(
                lambda: self.reject() if cancellation.is_set() else None
            )
            self.lease_timer.start()
        self.platform = platform
        self.binding = ""
        self.names: list[str] = []
        self.held: set[str] = set()
        self.setWindowTitle("Capture shortcut")
        layout = QVBoxLayout(self)
        self.label = QLabel("Press your shortcut here, then release. Escape cancels.")
        layout.addWidget(self.label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        focused = isinstance(watched, QWidget) and (watched is self or self.isAncestorOf(watched))
        if focused and event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        if focused and event.type() == QEvent.Type.KeyPress:
            self.keyPressEvent(event)
            return True
        if focused and event.type() == QEvent.Type.KeyRelease:
            self.keyReleaseEvent(event)
            return True
        return super().eventFilter(watched, event)

    def done(self, result: int) -> None:
        self.lease_timer.stop()
        QApplication.instance().removeEventFilter(self)
        super().done(result)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        if event.isAutoRepeat():
            return
        name = self.platform.focused_key_name(
            event.key(), event.nativeVirtualKey(), event.nativeScanCode()
        )
        if name:
            self.held.add(name)
        if name and name not in self.names:
            self.names.append(name)
            self.label.setText(" + ".join(self.names))
        event.accept()

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if not event.isAutoRepeat():
            name = self.platform.focused_key_name(
                event.key(), event.nativeVirtualKey(), event.nativeScanCode()
            )
            self.held.discard(name)
            if self.names and not self.held:
                self.binding = "+".join(self.names)
                self.accept()
        event.accept()


class Window(QMainWindow):
    """Settings and historical analytics remain usable with no daemon process."""

    def __init__(self, services: DesktopServices) -> None:
        super().__init__()
        # Tests build the window directly, so the theme is applied here as well
        # as in run(); the guard makes the second call a no-op.
        apply_theme(QApplication.instance())
        self.services = services
        self.tasks = Tasks(self)
        self.tasks.progress.connect(self._message)
        self.document: ConfigDocument | None = None
        self.editors: dict[str, QWidget] = {}
        self.rows: list[dict] = []
        self.analytics_loaded = False
        self._maintenance = None
        self._status_pending = False
        self.setWindowTitle("Stenographer")
        self.resize(1080, 760)
        asset_root = files("stenographer") / "assets"
        icon = QIcon(str(asset_root / "icons" / "stenographer.png"))
        self.setWindowIcon(icon)
        root = QWidget()
        self.setCentralWidget(root)
        horizontal = QHBoxLayout(root)
        horizontal.setContentsMargins(0, 0, 0, 0)
        horizontal.setSpacing(0)
        horizontal.addWidget(self._rail(icon))
        rail_line = QFrame()
        rail_line.setObjectName("railLine")
        rail_line.setFixedWidth(1)
        horizontal.addWidget(rail_line)
        content = QVBoxLayout()
        content.setContentsMargins(32, 20, 32, 20)
        content.setSpacing(12)
        content.addLayout(self._header())
        rule = QFrame()
        rule.setObjectName("rule")
        rule.setFixedHeight(1)
        content.addWidget(rule)
        self.pages = QStackedWidget()
        content.addWidget(self.pages, 1)
        horizontal.addLayout(content, 1)
        self.navigation.currentRowChanged.connect(self._navigate)
        self._overview_page()
        self._analytics_page()
        self._settings_page()
        self._service_page()
        self._diagnostics_page()
        self.navigation.setCurrentRow(0)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().showMessage("Loading local settings and analytics…")
        self.tasks.submit(
            "settings_load", lambda: ConfigDocument.load(services.config_path), self._loaded
        )
        self.refresh_analytics()
        self.refresh_status()
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start()

    def _rail(self, icon: QIcon) -> QWidget:
        """The 96 px icon rail: quill on top, one icon-and-label item per page."""
        rail = QWidget()
        rail.setObjectName("railFrame")
        rail.setFixedWidth(TOKENS.rail_width)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(0, 12, 0, 12)
        layout.setSpacing(8)
        quill = QLabel()
        quill.setObjectName("quill")
        quill.setPixmap(icon.pixmap(QSize(TOKENS.quill_px, TOKENS.quill_px)))
        quill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(quill)
        item_size = QSize(TOKENS.rail_width, TOKENS.rail_item)
        self.navigation = QListWidget()
        self.navigation.setObjectName("rail")
        self.navigation.setAccessibleName("Navigation")
        # IconMode draws the icon above a centred label; without the grid,
        # uniform sizes and top-to-bottom flow the items would flow sideways.
        self.navigation.setViewMode(QListWidget.ViewMode.IconMode)
        self.navigation.setFlow(QListWidget.Flow.TopToBottom)
        self.navigation.setWrapping(False)
        self.navigation.setMovement(QListWidget.Movement.Static)
        self.navigation.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.navigation.setUniformItemSizes(True)
        self.navigation.setGridSize(item_size)
        self.navigation.setIconSize(QSize(TOKENS.icon_px, TOKENS.icon_px))
        self.navigation.setSpacing(0)
        self.navigation.setFixedWidth(TOKENS.rail_width)
        self.navigation.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.addItems(NAVIGATION)
        for row, name in enumerate(NAVIGATION):
            item = self.navigation.item(row)
            item.setIcon(navigation_icon(name))
            item.setSizeHint(item_size)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.navigation, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch()
        return rail

    def _header(self) -> QHBoxLayout:
        """Brand and page title on the left, the daemon status dot and text on the right."""
        header = QHBoxLayout()
        header.setSpacing(12)
        brand = QLabel("Stenographer")
        brand.setProperty("role", "brand")
        header.addWidget(brand, 0, Qt.AlignmentFlag.AlignBaseline)
        self.page_title = QLabel(NAVIGATION[0])
        self.page_title.setProperty("role", "title")
        header.addWidget(self.page_title, 0, Qt.AlignmentFlag.AlignBaseline)
        header.addStretch()
        self.status_dot = QLabel()
        self.status_dot.setProperty("role", "dot")
        self.status_dot.setAccessibleName("Daemon status indicator")
        header.addWidget(self.status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        self.daemon_status = QLabel("Checking daemon status…")
        self.daemon_status.setProperty("role", "muted")
        header.addWidget(self.daemon_status, 0, Qt.AlignmentFlag.AlignVCenter)
        self._set_dot(False)
        return header

    def _navigate(self, row: int) -> None:
        self.pages.setCurrentIndex(row)
        self.page_title.setText(NAVIGATION[row])

    def _set_dot(self, on: bool) -> None:
        """Re-polish so a property change after show() repaints the dot."""
        self.status_dot.setProperty("state", "" if on else "off")
        self.status_dot.style().unpolish(self.status_dot)
        self.status_dot.style().polish(self.status_dot)

    def _caption(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "caption")
        label.setWordWrap(True)
        return label

    def _page(self, title: str) -> QVBoxLayout:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        self.pages.addWidget(page)
        return layout

    def _button(self, layout, text: str, callback) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def _table(self, headings: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headings))
        table.setHorizontalHeaderLabels(headings)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(False)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _fill(self, table: QTableWidget, rows) -> None:
        table.setRowCount(len(rows))
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(str(value)))
        table.resizeColumnsToContents()

    def _overview_page(self) -> None:
        layout = self._page("Overview")
        layout.addWidget(self._caption("Lifetime dictation totals"))
        self.headline = QLabel("0 recognized words   ·   00:00:00 recognized audio")
        self.headline.setProperty("role", "headline")
        self.headline.setWordWrap(True)
        layout.addWidget(self.headline)
        self.totals = self._table(["Measurement", "Value"])
        self.totals.setMaximumHeight(190)
        layout.addWidget(self.totals)
        period = QHBoxLayout()
        period.addWidget(QLabel("Recent trend period (days)"))
        self.trend_days = QSpinBox()
        self.trend_days.setRange(1, 3650)
        self.trend_days.setValue(30)
        period.addWidget(self.trend_days)
        self._button(period, "Refresh", self.refresh_analytics)
        layout.addLayout(period)
        self.trend_chart = WordTrend()
        layout.addWidget(self.trend_chart)
        self.trend = self._table(["Date (local)", "Utterances", "Words", "ASR audio (s)"])
        self.trend.setMaximumHeight(150)
        layout.addWidget(self.trend)
        self.collection_health = QLabel("Collection health: checking…")
        self.collection_health.setWordWrap(True)
        layout.addWidget(self.collection_health)

    def _analytics_page(self) -> None:
        layout = self._page("Analytics")
        filter_form = QFormLayout()
        self.filters: dict[str, QLineEdit | QComboBox] = {}
        source = QComboBox()
        source.addItems(["hotkey", "file", "all"])
        self.filters["source"] = source
        filter_form.addRow("Source", source)
        for name, label in [
            ("since", "From date (local YYYY-MM-DD)"),
            ("until", "Through date (local YYYY-MM-DD)"),
            ("model", "Model"),
            ("app_version", "App version"),
            ("device", "Microphone"),
            ("outcome", "Outcome"),
        ]:
            editor = QLineEdit()
            if name == "since":
                editor.setText((dt.date.today() - dt.timedelta(days=30)).isoformat())
            editor.setClearButtonEnabled(True)
            self.filters[name] = editor
            filter_form.addRow(label, editor)
        layout.addLayout(filter_form)
        actions = QHBoxLayout()
        self._button(actions, "Apply filters", self.refresh_analytics)
        self._button(actions, "Export JSON", lambda: self.export("json"))
        self._button(actions, "Export CSV", lambda: self.export("csv"))
        self._button(actions, "Delete matching records…", self.preview_delete)
        self._button(actions, "Reset analytics…", self.preview_reset)
        layout.addLayout(actions)
        tabs = QTabWidget()
        self.metrics = self._table(["Metric", "Samples", "Missing", "Average", "p95", "p99"])
        self.daily = self._table(["Daily measurement", "Value"])
        self.outcomes = self._table(["Outcome", "Count"])
        self.records = self._table(["Started (UTC)", "Outcome", "Recognized words", "Audio (s)"])
        self.records.cellDoubleClicked.connect(self.record_detail)
        for title, widget in [
            ("Latency and coverage", self.metrics),
            ("Trends", self.daily),
            ("Reliability", self.outcomes),
            ("Utterances", self.records),
        ]:
            tabs.addTab(widget, title)
        self.compare_group = QComboBox()
        self.compare_group.addItems(["model", "app_version", "device", "compute_type"])
        self.compare_metric = QComboBox()
        self.compare_metric.addItems(
            ["stop_to_ready_ms", "decode_ms", "capture_s", "recognized_words"]
        )
        comparison_page = QWidget()
        compare_layout = QVBoxLayout(comparison_page)
        compare_layout.addWidget(
            self._caption("Compare matching utterances by context and measurement")
        )
        compare_layout.addWidget(self.compare_group)
        compare_layout.addWidget(self.compare_metric)
        self.comparisons = self._table(["Group", "Samples", "Missing", "Average", "p95", "p99"])
        compare_layout.addWidget(self.comparisons)
        self.histogram = self._table(["Measurement interval", "Utterances"])
        compare_layout.addWidget(self.histogram)
        tabs.addTab(comparison_page, "Comparisons and distribution")
        self.compare_group.currentTextChanged.connect(self.refresh_comparison)
        self.compare_metric.currentTextChanged.connect(self.refresh_comparison)
        layout.addWidget(tabs)
        layout.addWidget(
            self._caption("Percentiles use matching utterances. Unavailable values remain unknown.")
        )

    def _settings_page(self) -> None:
        layout = self._page("Settings")
        self.running_state = QLabel("Running configuration: checking…")
        layout.addWidget(self.running_state)
        self.saved_state = QLabel("Loading saved settings…")
        self.saved_state.setWordWrap(True)
        layout.addWidget(self.saved_state)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.form_widget = QWidget()
        self.form = QFormLayout(self.form_widget)
        scroll.setWidget(self.form_widget)
        layout.addWidget(scroll)
        actions = QHBoxLayout()
        self.save_button = self._button(actions, "Save", self.save_settings)
        self.save_button.setEnabled(False)
        self._button(actions, "Apply while idle", lambda: self.service_action("apply"))
        self._button(
            actions,
            "Reload saved",
            lambda: self.tasks.submit(
                "settings_load",
                lambda: ConfigDocument.load(self.services.config_path),
                self._loaded,
            ),
        )
        layout.addLayout(actions)
        setup = QHBoxLayout()
        self._button(setup, "Capture shortcut…", self.capture_binding)
        self._button(setup, "Choose microphone…", self.choose_microphone)
        self._button(setup, "Calibrate spectrum…", self.calibrate)
        layout.addLayout(setup)
        extras = QHBoxLayout()
        self._button(extras, "Preview sounds", self.preview_sound)
        self._button(extras, "Download model…", self.download_model)
        layout.addLayout(extras)

    def _service_page(self) -> None:
        layout = self._page("Service")
        self.service_detail = QLabel("Checking service availability…")
        self.service_detail.setWordWrap(True)
        layout.addWidget(self.service_detail)
        for action, text in [
            ("start", "Start"),
            ("stop", "Stop while idle"),
            ("restart", "Restart while idle"),
            ("enable", "Launch at login"),
            ("disable", "Disable launch at login"),
        ]:
            self._button(
                layout, text, lambda checked=False, action=action: self.service_action(action)
            )
        layout.addStretch()
        self.tasks.submit(
            "service_status", self.services.platform.service_status, self._service_status
        )

    def _diagnostics_page(self) -> None:
        layout = self._page("Diagnostics")
        self._button(layout, "Refresh capabilities", self.probe)
        self.diagnostics = self._table(["Capability / diagnostic", "Value"])
        layout.addWidget(self.diagnostics)
        self._button(layout, "Open diagnostic log folder", self.open_logs)
        layout.addWidget(
            self._caption(
                "Logs contain technical diagnostics. Analytics retain no transcript or audio."
            )
        )

    def _message(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def _result(self, result, error) -> None:
        self._message(str(error) if error else str(result))

    def _loaded(self, document, error) -> None:
        if error:
            self.saved_state.setText(f"Cannot load settings: {error}. Correct the file and reload.")
            self.save_button.setEnabled(False)
            return
        self.document = document
        while self.form.rowCount():
            self.form.removeRow(0)
        self.editors.clear()
        enums = {
            "hotkey.mode": ["hybrid", "hold", "toggle"],
            "asr.compute_type": ["int8", "int8_float16", "float16", "float32", "default"],
            "feedback.log_level": ["debug", "info", "warning", "error"],
        }
        for section, values in dataclasses.asdict(document.config).items():
            section_label = QLabel(section.capitalize())
            section_label.setProperty("role", "section")
            self.form.addRow(section_label)
            for key, value in values.items():
                dotted = f"{section}.{key}"
                if isinstance(value, bool):
                    editor = QCheckBox()
                    editor.setChecked(value)
                    editor.toggled.connect(self._dirty)
                elif dotted in enums:
                    editor = QComboBox()
                    editor.addItems(enums[dotted])
                    editor.setCurrentText(value)
                    editor.currentTextChanged.connect(self._dirty)
                else:
                    text = (
                        ""
                        if value is None
                        else json.dumps(value)
                        if isinstance(value, tuple)
                        else str(value)
                    )
                    editor = QLineEdit(text)
                    editor.textEdited.connect(self._dirty)
                editor.setAccessibleName(dotted)
                editor.setToolTip(dotted)
                self.editors[dotted] = editor
                self.form.addRow(key.replace("_", " ").capitalize(), editor)
        self.save_button.setEnabled(True)
        self.saved_state.setText(
            "Saved configuration loaded. Save writes the file. "
            "Apply while idle restarts the daemon."
        )

    def _dirty(self, *_args) -> None:
        self.saved_state.setText(
            "Unsaved edits. Save validates and preserves existing comments and unknown settings."
        )

    def reviewed_config(self) -> Config:
        if self.document is None:
            raise ValueError("Load valid settings first.")
        values = {}
        for key, editor in self.editors.items():
            values[key] = (
                editor.isChecked()
                if isinstance(editor, QCheckBox)
                else editor.currentText()
                if isinstance(editor, QComboBox)
                else editor.text()
            )
        return edited_config(self.document, values)

    def save_settings(self) -> None:
        try:
            config = self.reviewed_config()
        except Exception as exc:
            self.saved_state.setText(str(exc))
            return
        document = self.document
        self.save_button.setEnabled(False)

        def save():
            document.save(config)
            return ConfigDocument.load(self.services.config_path)

        self.tasks.submit("settings_save", save, self._saved)

    def _saved(self, document, error) -> None:
        self.save_button.setEnabled(True)
        if error:
            self.saved_state.setText(str(error))
        else:
            self.document = document
            self.saved_state.setText(
                "Saved. Running settings change only after Apply while idle is accepted."
            )

    def _filters(self):
        from stenographer.analytics import Filters

        values = {}
        for key, editor in self.filters.items():
            value = editor.currentText() if isinstance(editor, QComboBox) else editor.text().strip()
            if key in {"since", "until"} and value:
                from stenographer.analytics.metrics import local_date_bound

                value = local_date_bound(value, end=key == "until")
            values[key] = None if value in {"", "all"} else value
        return Filters(**values)

    def refresh_analytics(self) -> None:
        try:
            filters = self._filters()
        except ValueError as exc:
            self._message(str(exc))
            return
        days = self.trend_days.value()

        def read():
            from stenographer.analytics import Filters

            store = self.services.store()
            since = (dt.datetime.now().astimezone() - dt.timedelta(days=days)).astimezone(dt.UTC)
            return (
                store.report(),
                store.report(Filters(since=since.isoformat())),
                store.report(filters),
                store.records(filters),
            )

        self.tasks.submit("analytics", read, self._analytics)

    def _analytics(self, result, error) -> None:
        if error:
            self.collection_health.setText(f"Analytics unavailable: {error}")
            return
        self.analytics_loaded = True
        lifetime, recent, report, self.rows = result
        totals = dict(lifetime.get("totals", {}))
        audio_seconds = int(totals.get("asr_audio_s", 0))
        totals["Recognized audio (hh:mm:ss)"] = (
            f"{audio_seconds // 3600:02d}:{audio_seconds // 60 % 60:02d}:{audio_seconds % 60:02d}"
        )
        self.headline.setText(
            f"{totals.get('recognized_words', 0):,} recognized words   ·   "
            f"{totals['Recognized audio (hh:mm:ss)']} recognized audio"
        )
        self._fill(self.totals, [(key.replace("_", " "), value) for key, value in flatten(totals)])
        daily = recent.get("daily", [])
        self.trend_chart.set_points(daily)
        self._fill(
            self.trend,
            [
                (
                    point["date"],
                    point["utterances"],
                    point["recognized_words"],
                    point["asr_audio_s"],
                )
                for point in daily
            ],
        )
        self._fill(
            self.metrics,
            [
                (
                    key,
                    *(
                        "Unavailable" if stats[item] is None else stats[item]
                        for item in ("count", "missing", "average", "p95", "p99")
                    ),
                )
                for key, stats in report.get("metrics", {}).items()
            ],
        )
        self.refresh_comparison()
        self._fill(self.daily, flatten(report.get("daily", {})))
        self._fill(self.outcomes, flatten(report.get("outcomes", {})))
        self._fill(
            self.records,
            [
                (
                    row.get("started_at", ""),
                    row.get("outcome", "incomplete"),
                    row["metrics"].get("recognized_words", "Unavailable"),
                    row["metrics"].get("asr_audio_s", "Unavailable"),
                )
                for row in self.rows
            ],
        )
        self.collection_health.setText(
            "Collection health: "
            + "; ".join(f"{key}: {value}" for key, value in flatten(report.get("health", {})))
        )
        self._message("Local analytics refreshed.")

    def refresh_comparison(self, *_args) -> None:
        metric = self.compare_metric.currentText()
        self._fill(
            self.comparisons,
            [
                tuple("Unavailable" if value is None else value for value in row)
                for row in comparison_rows(self.rows, self.compare_group.currentText(), metric)
            ],
        )
        self._fill(self.histogram, histogram_rows(self.rows, metric))

    def refresh_status(self) -> None:
        if self._status_pending:
            return
        self._status_pending = True
        self.tasks.submit("status", self.services.status, self._status)

    def _status(self, result, error) -> None:
        self._status_pending = False
        if error:
            self.daemon_status.setText("Daemon status unavailable")
            self._set_dot(False)
            return
        status = result.get("status", {})
        self.daemon_status.setText(f"Daemon: {status.get('lifecycle', 'unavailable')}")
        self._set_dot(True)
        if self.document and status.get("running_config"):
            from stenographer.control import config_fingerprint

            matches = status["running_config"] == config_fingerprint(self.document.config)
            self.running_state.setText(
                "Saved settings match the running daemon."
                if matches
                else "Saved settings differ from the running daemon."
            )
        else:
            self.running_state.setText("Running configuration unavailable while daemon is stopped.")

    def _service_status(self, result, error) -> None:
        self.service_detail.setText(
            str(error)
            if error
            else "; ".join(f"{key}: {value}" for key, value in flatten(dataclasses.asdict(result)))
        )

    def service_action(self, action: str) -> None:
        self.tasks.submit(
            "service_action", lambda: self.services.service_action(action), self._result
        )

    def record_detail(self, row: int, _column: int) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Numeric utterance detail and checkpoint timeline")
        dialog.resize(700, 600)
        layout = QVBoxLayout(dialog)
        detail = QTextEdit()
        detail.setReadOnly(True)
        detail.setPlainText(json.dumps(self.rows[row], indent=2, default=str))
        layout.addWidget(detail)
        utterance_id = self.rows[row]["id"]

        def loaded(timeline, error):
            if not error and dialog.isVisible():
                detail.append("\nCheckpoint timeline\n" + json.dumps(timeline, indent=2))

        self.tasks.submit("timeline", lambda: self.services.store().timeline(utterance_id), loaded)
        dialog.exec()

    def export(self, kind: str) -> None:
        try:
            filters = self._filters()
        except ValueError as exc:
            self._message(str(exc))
            return
        name, _ = QFileDialog.getSaveFileName(self, "Export analytics", f"analytics.{kind}")
        if not name:
            return

        def write():
            store = self.services.store()
            data = store.export_json(filters) if kind == "json" else store.export_csv(filters)
            Path(name).write_text(data, encoding="utf-8")
            return "Analytics exported."

        self.tasks.submit("export", write, self._result)

    def preview_delete(self) -> None:
        try:
            filters = self._filters()
        except ValueError as exc:
            self._message(str(exc))
            return

        def confirm(count, error):
            if error:
                self._result(None, error)
            elif (
                count
                and QMessageBox.question(
                    self,
                    "Delete analytics",
                    f"Permanently delete {count} matching utterance records?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                == QMessageBox.StandardButton.Yes
            ):
                self.tasks.submit("delete", lambda: self.services.store().delete(filters), deleted)
            else:
                self._message("No records deleted.")

        def deleted(count, error):
            self._result(f"Deleted {count} records.", error)
            self.refresh_analytics()

        self.tasks.submit(
            "delete_preview", lambda: self.services.store().preview_delete(filters), confirm
        )

    def preview_reset(self) -> None:
        from stenographer.analytics import Filters

        filters = Filters(source=None)

        def confirm(count, error):
            if error:
                self._result(None, error)
                return
            if (
                QMessageBox.question(
                    self,
                    "Reset analytics",
                    f"Permanently delete all {count} utterance records from every source?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                == QMessageBox.StandardButton.Yes
            ):
                self.tasks.submit("reset", lambda: self.services.store().reset(), completed)

        def completed(count, error):
            self._result(f"Deleted {count} records.", error)
            self.refresh_analytics()

        self.tasks.submit(
            "reset_preview", lambda: self.services.store().preview_delete(filters), confirm
        )

    def capture_binding(self) -> None:
        if self.document is None:
            return
        lease = self.services.maintenance("shortcut")

        def ready(cancellation, error):
            if error:
                self._result(None, error)
                return
            self._maintenance = lease
            dialog = BindingDialog(self.services.platform, self, cancellation)
            if not cancellation.is_set():
                accepted = dialog.exec() == QDialog.DialogCode.Accepted
                if accepted and not cancellation.is_set():
                    self.editors["hotkey.binding"].setText(dialog.binding)
                    self._dirty()
            dialog.lease_timer.stop()
            if cancellation.is_set():
                self._message("Shortcut capture ended because its maintenance lease was lost.")
            self._maintenance = None
            self.tasks.submit(
                "maintenance_end", lambda: lease.__exit__(None, None, None), self._result
            )

        self.tasks.submit("maintenance_begin", lambda: lease.__enter__(), ready)

    def choose_microphone(self) -> None:
        from stenographer.audio_probe import input_device_choices, query_devices

        def choose(query, error):
            if error or query.error:
                self._message(str(error or query.error))
                return
            dialog = QDialog(self)
            dialog.setWindowTitle("Microphone")
            layout = QVBoxLayout(dialog)
            choices = QComboBox()
            choices.addItem("System default", "")
            for value, label in input_device_choices(query.devices):
                choices.addItem(label, value)
            layout.addWidget(choices)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if dialog.exec() == QDialog.DialogCode.Accepted and self.document:
                self.editors["audio.input_device"].setText(choices.currentData())
                self._dirty()

        self.tasks.submit("devices", query_devices, choose)

    def calibrate(self) -> None:
        try:
            cfg = self.reviewed_config()
        except Exception as exc:
            self._result(None, exc)
            return
        if (
            QMessageBox.question(
                self,
                "Calibrate spectrum",
                "Record five seconds of room silence, then three seconds of your voice?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        def capture():
            from stenographer.calibration import calibrate_spectrum_profile

            with self.services.maintenance("calibration") as cancellation:
                return calibrate_spectrum_profile(
                    cfg.audio.input_device,
                    cancellation=cancellation,
                    on_countdown=lambda seconds: self.tasks.progress.emit(
                        f"Stay quiet. Recording begins in {seconds} seconds."
                        if seconds
                        else "Recording room silence…"
                    ),
                    on_voice_prompt=lambda: self.tasks.progress.emit(
                        "Speak normally now for three seconds…"
                    ),
                )

        def completed(profile, error):
            if error:
                self._result(None, error)
            else:
                self.editors["feedback.spectrum_floor_dbfs"].setText(json.dumps(profile))
                self._dirty()
                self._message("Calibration complete. Review and save the new spectrum floor.")

        self.tasks.submit("calibration", capture, completed)

    def preview_sound(self) -> None:
        try:
            cfg = self.reviewed_config()
        except Exception as exc:
            self._result(None, exc)
            return
        self.tasks.submit("sound", lambda: self.services.preview(cfg), self._result)

    def download_model(self) -> None:
        try:
            cfg = self.reviewed_config()
        except Exception as exc:
            self._result(None, exc)
            return
        if (
            QMessageBox.question(
                self,
                "Download model",
                f"Download {cfg.asr.model} from its model repository? This uses the network.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        def download():
            from stenographer.transcribe.model import download_model

            download_model(cfg.asr.model)
            return "Model download complete."

        self.tasks.submit("model_download", download, self._result)

    def probe(self) -> None:
        def read():
            from stenographer.capabilities import probe

            return probe(Config.load(self.services.config_path))

        self.tasks.submit(
            "diagnostics",
            read,
            lambda result, error: (
                self._result(None, error)
                if error
                else self._fill(self.diagnostics, flatten(dataclasses.asdict(result)))
            ),
        )

    def open_logs(self) -> None:
        import os

        from PySide6.QtCore import QUrl

        directory = self.services.platform.state_dir(os.environ, Path.home())
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def closeEvent(self, event) -> None:  # noqa: N802
        self.timer.stop()
        self.tasks.closed = True
        self.services.close()
        event.accept()


def run(config_path: Path, database_path: Path | None = None, *, smoke: bool = False) -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Stenographer")
    app.setOrganizationName("Stenographer")
    apply_theme(app)
    window = Window(DesktopServices(config_path, database_path))
    window.show()
    if smoke:
        import time

        deadline = time.monotonic() + 10
        smoke_timer = QTimer(window)
        smoke_timer.setInterval(50)

        smoke_saved = False

        def verify():
            nonlocal smoke_saved
            if time.monotonic() >= deadline:
                window.close()
                app.exit(1)
                return
            if window.document is not None and window.analytics_loaded:
                window.navigation.setCurrentRow(2)
                if not smoke_saved:
                    smoke_saved = True
                    window.editors["feedback.mute"].setChecked(True)
                    window.save_settings()
                    return
                if window.save_button.isEnabled() and config_path.exists():
                    good = Config.load(config_path).feedback.mute and not window.grab().isNull()
                    window.close()
                    app.exit(0 if good else 1)

        smoke_timer.timeout.connect(verify)
        smoke_timer.start()
    return app.exec()
