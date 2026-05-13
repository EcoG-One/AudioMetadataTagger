"""GUI Dialogs for file selection, metadata preview, and search results."""

import os
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QFileDialog,
    QLabel,
    QTableView,
    QStandardItemModel,
    QTabWidget,
    QWidget,
    QTextEdit,
    QPlainTextEdit,
    QProgressBar,
    QMessageBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from pathlib import Path
from config import SUPPORTED_EXTENSIONS
import logging

logger = logging.getLogger(__name__)


class FileSelectorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Audio Folder")
        self.resize(400, 150)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose the root folder containing your audio files:"))
        btn = QPushButton("Browse...")
        btn.clicked.connect(self._pick_folder)
        self.path_label = QLabel()
        self.path_label.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(self.path_label)
        layout.addWidget(btn)

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.path_label.setText(folder)
            self.path_label.setStyleSheet("color: green; font-weight: bold;")

    def get_path(self):
        return self.path_label.text()


class MetadataPreviewDialog(QDialog):
    def __init__(self, artist: str, album: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm/Correct Metadata")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Detected Artist & Album (Edit if needed):"))
        self.artist_edit = QTextEdit()
        self.artist_edit.setPlainText(artist)
        self.album_edit = QTextEdit()
        self.album_edit.setPlainText(album)
        layout.addWidget(self.artist_edit)
        layout.addWidget(self.album_edit)
        btn_box = QHBoxLayout()
        self.btn_ok = QPushButton("Confirm & Search")
        self.btn_cancel = QPushButton("Cancel")
        btn_box.addWidget(self.btn_ok)
        btn_box.addWidget(self.btn_cancel)
        layout.addLayout(btn_box)
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

    def get_metadata(self):
        return (
            self.artist_edit.toPlainText().strip(),
            self.album_edit.toPlainText().strip(),
        )


class SearchResultsDialog(QDialog):
    def __init__(self, results: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search Results")
        self.resize(600, 400)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Select the correct release:"))

        self.table = QTableView()
        self.model = QStandardItemModel()
        self.model.setHorizontalHeaderLabels(["ID", "Title", "Artist", "Year", "Image"])
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        layout.addWidget(self.table)

        for r in results:
            row = [
                QStandardItem(str(r["id"])),
                QStandardItem(r["title"]),
                QStandardItem(r["artist"]),
                QStandardItem(str(r["year"]) if r["year"] else ""),
                QStandardItem(r.get("image_url", "No Cover")),
            ]
            self.model.appendRow(row)

        btn_box = QHBoxLayout()
        self.btn_ok = QPushButton("Select")
        self.btn_retry = QPushButton("Retry Search")
        self.btn_cancel = QPushButton("Cancel")
        btn_box.addWidget(self.btn_ok)
        btn_box.addWidget(self.btn_retry)
        btn_box.addWidget(self.btn_cancel)
        layout.addLayout(btn_box)

        self.btn_ok.clicked.connect(self.accept)
        self.btn_retry.clicked.connect(lambda: self.reject("retry"))
        self.btn_cancel.clicked.connect(self.reject)

    def get_selected_result(self):
        sel = self.table.selectionModel().selection()
        if sel.indexes():
            row = sel.indexes()[0].row()
            return (
                self.model.item(row, 0).text(),
                self.model.item(row, 1).text(),
                self.model.item(row, 2).text(),
                self.model.item(row, 3).text(),
                self.model.item(row, 4).text(),
            )
        return None
