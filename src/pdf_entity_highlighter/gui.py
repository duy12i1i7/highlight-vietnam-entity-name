from __future__ import annotations

import sys
import json
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pdf_entity_highlighter.batch import resolve_output_paths
from pdf_entity_highlighter.highlighter import DEFAULT_COLORS, HighlightResult, highlight_pdf
from pdf_entity_highlighter.ner import (
    UndertheseaEntityDetector,
    VnCoreNlpEntityDetector,
    default_vncorenlp_dir,
)
from pdf_entity_highlighter.validation import (
    ConfirmedEntityDetector,
    StrictEntityValidator,
    load_confirmed_entities,
)


APP_NAME = "PDF Entity Highlighter"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--self-test" in args:
        detector = UndertheseaEntityDetector()
        entities = detector.extract("Ông Nguyễn Văn A sống tại Hà Nội.", {"PER", "LOC"})
        print(json.dumps([entity.__dict__ for entity in entities], ensure_ascii=False))
        return 0
    if "--self-test-vncorenlp" in args:
        detector = VnCoreNlpEntityDetector(download=False)
        entities = detector.extract("Ông Nguyễn Văn A sống tại Hà Nội.", {"PER", "LOC"})
        print(json.dumps([entity.__dict__ for entity in entities], ensure_ascii=False))
        return 0

    app = QApplication(sys.argv if argv is None else argv)
    window = MainWindow()
    window.show()
    return app.exec()


class PdfListWidget(QListWidget):
    files_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".pdf")
        ]
        if paths:
            self.add_pdf_paths(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def add_pdf_paths(self, paths: list[Path]) -> None:
        existing = set(self.paths())
        added = False
        for path in paths:
            resolved = path.expanduser().resolve()
            if resolved in existing or resolved.suffix.lower() != ".pdf":
                continue
            item = QListWidgetItem(str(resolved))
            item.setData(Qt.ItemDataRole.UserRole, resolved)
            self.addItem(item)
            existing.add(resolved)
            added = True
        if added:
            self.files_changed.emit()

    def paths(self) -> list[Path]:
        return [self.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.count())]

    def remove_selected(self) -> None:
        for item in self.selectedItems():
            self.takeItem(self.row(item))
        self.files_changed.emit()

    def clear_files(self) -> None:
        self.clear()
        self.files_changed.emit()


class HighlightWorker(QObject):
    progress = Signal(int, int)
    log = Signal(str)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        output_paths: dict[Path, Path],
        labels: set[str],
        opacity: float,
        strict: bool,
        confirmed_only_path: Path | None,
        engine: str,
        vncorenlp_dir: Path,
        download_vncorenlp: bool,
    ) -> None:
        super().__init__()
        self.output_paths = output_paths
        self.labels = labels
        self.opacity = opacity
        self.strict = strict
        self.confirmed_only_path = confirmed_only_path
        self.engine = engine
        self.vncorenlp_dir = vncorenlp_dir
        self.download_vncorenlp = download_vncorenlp

    def run(self) -> None:
        try:
            validator = StrictEntityValidator() if self.strict else None
            if self.confirmed_only_path:
                self.log.emit("Loading confirmed entity list...")
                confirmed_entities = load_confirmed_entities(self.confirmed_only_path)
                if not confirmed_entities:
                    raise ValueError("Confirmed entity list is empty.")
                detector = ConfirmedEntityDetector(confirmed_entities)
                validator = None
                self.log.emit("Confirmed-only mode is enabled. NER candidates will not be used.")
            else:
                if self.engine == "vncorenlp":
                    self.log.emit("Loading VnCoreNLP model...")
                    detector = VnCoreNlpEntityDetector(
                        model_dir=self.vncorenlp_dir,
                        download=self.download_vncorenlp,
                    )
                else:
                    self.log.emit("Loading Underthesea NER model...")
                    detector = UndertheseaEntityDetector()
                if validator:
                    self.log.emit("Strict validation is enabled. Some valid entities may be skipped.")
            results: list[HighlightResult] = []
            total = len(self.output_paths)

            for index, (input_path, output_path) in enumerate(self.output_paths.items(), start=1):
                self.log.emit(f"Processing: {input_path.name}")
                result = highlight_pdf(
                    input_path=input_path,
                    output_path=output_path,
                    detector=detector,
                    labels=self.labels,
                    colors=DEFAULT_COLORS,
                    opacity=self.opacity,
                    validator=validator,
                )
                results.append(result)
                self.log.emit(
                    f"Saved: {output_path} "
                    f"({result.total_highlights} highlight(s), {result.pages_processed} page(s))"
                )
                if result.pages_without_text:
                    pages = ", ".join(str(page + 1) for page in result.pages_without_text)
                    self.log.emit(f"Warning: no extractable text on page(s): {pages}")
                if result.skipped:
                    self.log.emit(f"Skipped by validation: {len(result.skipped)} candidate(s)")
                self.progress.emit(index, total)

            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.thread: QThread | None = None
        self.worker: HighlightWorker | None = None

        self.setWindowTitle(APP_NAME)
        self.resize(920, 680)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        title = QLabel(APP_NAME)
        title.setObjectName("title")
        layout.addWidget(title)

        file_group = QGroupBox("PDF files")
        file_layout = QVBoxLayout(file_group)
        self.file_list = PdfListWidget()
        self.file_list.setMinimumHeight(180)
        self.file_list.files_changed.connect(self.update_output_hint)
        file_layout.addWidget(self.file_list)

        file_buttons = QHBoxLayout()
        self.add_button = QPushButton("Add PDFs")
        self.remove_button = QPushButton("Remove Selected")
        self.clear_button = QPushButton("Clear")
        self.add_button.clicked.connect(self.add_files)
        self.remove_button.clicked.connect(self.file_list.remove_selected)
        self.clear_button.clicked.connect(self.file_list.clear_files)
        file_buttons.addWidget(self.add_button)
        file_buttons.addWidget(self.remove_button)
        file_buttons.addWidget(self.clear_button)
        file_buttons.addStretch()
        file_layout.addLayout(file_buttons)
        layout.addWidget(file_group)

        options_frame = QFrame()
        options_layout = QGridLayout(options_frame)
        options_layout.setContentsMargins(0, 0, 0, 0)

        output_group = QGroupBox("Output")
        output_layout = QVBoxLayout(output_group)
        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Choose an output PDF for one file, or a folder for multiple files")
        self.browse_output_button = QPushButton("Browse")
        self.browse_output_button.clicked.connect(self.choose_output)
        output_row.addWidget(self.output_edit)
        output_row.addWidget(self.browse_output_button)
        output_layout.addLayout(output_row)
        self.output_hint = QLabel("")
        self.output_hint.setObjectName("hint")
        output_layout.addWidget(self.output_hint)
        options_layout.addWidget(output_group, 0, 0)

        entity_group = QGroupBox("Entities")
        entity_layout = QFormLayout(entity_group)
        self.label_checks: dict[str, QCheckBox] = {}
        for label, text, checked in [
            ("PER", "People", True),
            ("LOC", "Locations", True),
            ("ORG", "Organizations", False),
            ("MISC", "Miscellaneous", False),
        ]:
            checkbox = QCheckBox(text)
            checkbox.setChecked(checked)
            self.label_checks[label] = checkbox
            entity_layout.addRow(label, checkbox)

        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setRange(0.05, 1.0)
        self.opacity_spin.setSingleStep(0.05)
        self.opacity_spin.setValue(0.35)
        entity_layout.addRow("Opacity", self.opacity_spin)
        options_layout.addWidget(entity_group, 0, 1)
        options_layout.setColumnStretch(0, 3)
        options_layout.setColumnStretch(1, 1)
        layout.addWidget(options_frame)

        accuracy_group = QGroupBox("Accuracy")
        accuracy_layout = QGridLayout(accuracy_group)
        self.engine_combo = QComboBox()
        self.engine_combo.addItem("VnCoreNLP", "vncorenlp")
        self.engine_combo.addItem("Underthesea", "underthesea")
        self.strict_check = QCheckBox("Strict validation")
        self.strict_check.setChecked(True)
        self.vncorenlp_dir_edit = QLineEdit(str(default_vncorenlp_dir()))
        self.vncorenlp_dir_edit.setPlaceholderText("VnCoreNLP model folder")
        self.browse_vncorenlp_button = QPushButton("Browse")
        self.browse_vncorenlp_button.clicked.connect(self.choose_vncorenlp_dir)
        self.download_vncorenlp_check = QCheckBox("Download VnCoreNLP model if missing")
        self.download_vncorenlp_check.setChecked(True)
        self.confirmed_only_edit = QLineEdit()
        self.confirmed_only_edit.setPlaceholderText("Optional confirmed entity list")
        self.browse_confirmed_button = QPushButton("Browse")
        self.browse_confirmed_button.clicked.connect(self.choose_confirmed_list)
        accuracy_layout.addWidget(QLabel("NER engine"), 0, 0)
        accuracy_layout.addWidget(self.engine_combo, 0, 1)
        accuracy_layout.addWidget(self.strict_check, 1, 0, 1, 2)
        accuracy_layout.addWidget(self.vncorenlp_dir_edit, 2, 0)
        accuracy_layout.addWidget(self.browse_vncorenlp_button, 2, 1)
        accuracy_layout.addWidget(self.download_vncorenlp_check, 3, 0, 1, 2)
        accuracy_layout.addWidget(self.confirmed_only_edit, 4, 0)
        accuracy_layout.addWidget(self.browse_confirmed_button, 4, 1)
        layout.addWidget(accuracy_group)

        action_row = QHBoxLayout()
        self.start_button = QPushButton("Start Highlighting")
        self.start_button.clicked.connect(self.start_highlighting)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.progress_bar)
        layout.addLayout(action_row)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(150)
        layout.addWidget(self.log_view)

        self.setStyleSheet(
            """
            QLabel#title {
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#hint {
                color: #555;
            }
            QGroupBox {
                font-weight: 600;
            }
            QPushButton {
                min-height: 30px;
                padding-left: 12px;
                padding-right: 12px;
            }
            """
        )
        self.update_output_hint()

    def add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Select PDF files", "", "PDF files (*.pdf)")
        if files:
            self.file_list.add_pdf_paths([Path(file) for file in files])

    def choose_output(self) -> None:
        files = self.file_list.paths()
        if len(files) == 1:
            suggested = files[0].with_name(f"{files[0].stem}-highlighted.pdf")
            output, _ = QFileDialog.getSaveFileName(
                self,
                "Save highlighted PDF",
                str(suggested),
                "PDF files (*.pdf)",
            )
            if output:
                self.output_edit.setText(output)
            return

        directory = QFileDialog.getExistingDirectory(self, "Select output folder")
        if directory:
            self.output_edit.setText(directory)

    def choose_confirmed_list(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select confirmed entity list",
            "",
            "Text files (*.txt *.csv);;All files (*)",
        )
        if file_path:
            self.confirmed_only_edit.setText(file_path)

    def choose_vncorenlp_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select VnCoreNLP model folder")
        if directory:
            self.vncorenlp_dir_edit.setText(directory)

    def update_output_hint(self) -> None:
        count = self.file_list.count()
        if count == 0:
            self.output_hint.setText("Add one or more searchable PDF files, or drag them into the list.")
        elif count == 1:
            self.output_hint.setText("For one file, choose an exact output PDF path or choose a folder.")
        else:
            self.output_hint.setText("For multiple files, choose a folder. Output names end with -highlighted.pdf.")

    def selected_labels(self) -> set[str]:
        return {label for label, checkbox in self.label_checks.items() if checkbox.isChecked()}

    def start_highlighting(self) -> None:
        input_files = self.file_list.paths()
        output_text = self.output_edit.text().strip()
        labels = self.selected_labels()
        confirmed_only_text = self.confirmed_only_edit.text().strip()
        vncorenlp_dir_text = self.vncorenlp_dir_edit.text().strip()

        if not input_files:
            QMessageBox.warning(self, APP_NAME, "Select at least one PDF file.")
            return
        if not output_text:
            QMessageBox.warning(self, APP_NAME, "Choose where to save the highlighted output.")
            return
        if not labels:
            QMessageBox.warning(self, APP_NAME, "Choose at least one entity type.")
            return

        try:
            output_paths = resolve_output_paths(input_files, Path(output_text).expanduser().resolve())
        except ValueError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return

        self.set_running(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(len(output_paths))
        self.log_view.clear()
        confirmed_only_path = Path(confirmed_only_text).expanduser().resolve() if confirmed_only_text else None
        if confirmed_only_path and not confirmed_only_path.exists():
            QMessageBox.warning(self, APP_NAME, "Confirmed entity list does not exist.")
            self.set_running(False)
            return

        self.append_log(f"Selected labels: {', '.join(sorted(labels))}")
        engine = self.engine_combo.currentData()
        vncorenlp_dir = Path(vncorenlp_dir_text).expanduser().resolve() if vncorenlp_dir_text else default_vncorenlp_dir()

        self.thread = QThread()
        self.worker = HighlightWorker(
            output_paths,
            labels,
            self.opacity_spin.value(),
            self.strict_check.isChecked(),
            confirmed_only_path,
            str(engine),
            vncorenlp_dir,
            self.download_vncorenlp_check.isChecked(),
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.log.connect(self.append_log)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.clear_worker_refs)
        self.thread.start()

    def set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.add_button.setEnabled(not running)
        self.remove_button.setEnabled(not running)
        self.clear_button.setEnabled(not running)
        self.browse_output_button.setEnabled(not running)
        self.browse_confirmed_button.setEnabled(not running)
        self.confirmed_only_edit.setEnabled(not running)
        self.strict_check.setEnabled(not running)
        self.engine_combo.setEnabled(not running)
        self.vncorenlp_dir_edit.setEnabled(not running)
        self.browse_vncorenlp_button.setEnabled(not running)
        self.download_vncorenlp_check.setEnabled(not running)

    def append_log(self, message: str) -> None:
        self.log_view.append(message)

    def on_progress(self, current: int, total: int) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    def on_finished(self, results: list[HighlightResult]) -> None:
        total_highlights = sum(result.total_highlights for result in results)
        self.append_log(f"Done. Created {len(results)} file(s), {total_highlights} highlight(s).")
        self.set_running(False)
        QMessageBox.information(self, APP_NAME, "Highlighting completed.")

    def on_failed(self, message: str) -> None:
        self.append_log(f"Error: {message}")
        self.set_running(False)
        QMessageBox.critical(self, APP_NAME, message)

    def clear_worker_refs(self) -> None:
        self.thread = None
        self.worker = None

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.thread is not None and self.thread.isRunning():
            QMessageBox.warning(self, APP_NAME, "Wait for the current highlighting job to finish before closing.")
            event.ignore()
            return
        super().closeEvent(event)


if __name__ == "__main__":
    raise SystemExit(main())
