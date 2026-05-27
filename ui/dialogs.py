"""GUI Dialogs for file selection, metadata preview, and search results."""
import os
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog, 
                             QLabel, QTableView, QTabWidget, QWidget,
                             QTextEdit, QPlainTextEdit, QProgressBar, QMessageBox,
                             QFormLayout, QSpinBox, QDoubleSpinBox, QCheckBox,
                             QDialogButtonBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QStandardItemModel, QStandardItem
from pathlib import Path
from config import SUPPORTED_EXTENSIONS
import logging

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """Dialog for editing persisted application settings."""

    def __init__(self, app_settings, parent=None):
        super().__init__(parent)
        self.app_settings = app_settings
        self.setWindowTitle("Settings")
        self.resize(420, 260)

        self.app_settings.reload()

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.fuzzy_threshold = QSpinBox()
        self.fuzzy_threshold.setRange(0, 100)
        self.fuzzy_threshold.setSuffix("%")
        self.fuzzy_threshold.setMaximumWidth(80)
        self.fuzzy_threshold.setValue(self._int_setting('fuzzy_threshold', 75, 0, 100))
        form.addRow("Fuzzy match threshold", self.fuzzy_threshold)

        self.default_page_size = QSpinBox()
        self.default_page_size.setRange(1, 50)
        self.default_page_size.setMaximumWidth(80)
        self.default_page_size.setValue(self._int_setting('default_page_size', 50, 1, 50))
        form.addRow("Discogs page size", self.default_page_size)

        self.max_search_retries = QSpinBox()
        self.max_search_retries.setRange(0, 10)
        self.max_search_retries.setMaximumWidth(80)
        self.max_search_retries.setValue(self._int_setting('max_search_retries', 3, 0, 10))
        form.addRow("Max search retries", self.max_search_retries)

        self.api_rate_limit_delay = QDoubleSpinBox()
        self.api_rate_limit_delay.setRange(0.0, 60.0)
        self.api_rate_limit_delay.setDecimals(2)
        self.api_rate_limit_delay.setSingleStep(0.1)
        self.api_rate_limit_delay.setSuffix(" s")
        self.api_rate_limit_delay.setMaximumWidth(100)
        self.api_rate_limit_delay.setValue(
            self._float_setting('api_rate_limit_delay', 0.2, 0.0, 60.0)
        )
        form.addRow("API rate limit delay", self.api_rate_limit_delay)

        self.embed_artwork = QCheckBox("Embed artwork when tagging")
        self.embed_artwork.setChecked(self._bool_setting('embed_artwork', True))
        form.addRow("", self.embed_artwork)

        self.validate_tags = QCheckBox("Validate tags before writing")
        self.validate_tags.setChecked(self._bool_setting('validate_tags', True))
        form.addRow("", self.validate_tags)

        self.overwrite_existing_tags = QCheckBox("Overwrite existing tags")
        self.overwrite_existing_tags.setChecked(
            self._bool_setting('overwrite_existing_tags', False)
        )
        form.addRow("", self.overwrite_existing_tags)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._apply_theme()

    def _int_setting(self, key, default, min_value, max_value):
        try:
            value = int(self.app_settings.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(min_value, min(max_value, value))

    def _float_setting(self, key, default, min_value, max_value):
        try:
            value = float(self.app_settings.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(min_value, min(max_value, value))

    def _bool_setting(self, key, default):
        value = self.app_settings.get(key, default)
        return value if isinstance(value, bool) else default

    def _save(self):
        self.app_settings.update({
            'fuzzy_threshold': self.fuzzy_threshold.value(),
            'default_page_size': self.default_page_size.value(),
            'max_search_retries': self.max_search_retries.value(),
            'api_rate_limit_delay': self.api_rate_limit_delay.value(),
            'embed_artwork': self.embed_artwork.isChecked(),
            'validate_tags': self.validate_tags.isChecked(),
            'overwrite_existing_tags': self.overwrite_existing_tags.isChecked(),
        })
        self.accept()

    def _apply_theme(self):
        self.setStyleSheet("""
            QDialog { background-color: #2b2b2b; color: #ffffff; }
            QVBoxLayout { background-color: #2b2b2b; color: #ffffff; }
            QDialogButtonBox { border: 1px solid #555; background: #333; }
            QCheckBox { background: #444; color: #ccc; padding: 8px; }
            QPushButton { background: #0078d4; color: white; border: none; padding: 8px; border-radius: 4px; }
            QPushButton:hover { background: #0063b1; }
            QFormLayout { color: white; background: #3a3a3a; border: 1px solid #555; alternate-background-color: #444; }
            QSpinBox, QDoubleSpinBox { background: #333; color: #ddd; border: 1px solid #555; }
            QMessageBox { background: #2b2b2b; color: #fff; }
        """)

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
        return self.artist_edit.toPlainText().strip(), self.album_edit.toPlainText().strip()

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
                QStandardItem(str(r['id'])),
                QStandardItem(r['title']),
                QStandardItem(r['artist']),
                QStandardItem(str(r['year']) if r['year'] else ""),
                QStandardItem(r.get('image_url', 'No Cover'))
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
            return self.model.item(row, 0).text(), self.model.item(row, 1).text(), self.model.item(row, 2).text(), self.model.item(row, 3).text(), self.model.item(row, 4).text()
        return None


class DiscogsVerifierDialog(QDialog):
    """Dialog to get the OAUTH_VERIFIER code from the user."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Discogs Authentication")
        self.resize(400, 150)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Please authorize the app in your browser, then paste the VERIFIER code below:"
            )
        )

        self.txt = QPlainTextEdit()
        self.txt.setPlaceholderText("Paste the 7-digit code here...")
        layout.addWidget(self.txt)

        btn_ok = QPushButton("Confirm")
        layout.addWidget(btn_ok)

        # Connect button to accept the dialog
        btn_ok.clicked.connect(self.accept)

    def get_verifier_code(self):
        return self.txt.toPlainText().strip()
