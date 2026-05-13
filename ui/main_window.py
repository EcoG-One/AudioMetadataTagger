"""Main Application Window & Workflow Controller."""

import sys
import os
import json
import time
import logging
import webbrowser
from pathlib import Path
from PyQt6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QTableView,
    QStandardItemModel,
    QProgressBar,
    QLabel,
    QPushButton,
    QHeaderView,
    QMessageBox,
    QFileDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QPlainTextEdit,
    QDialog,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
import mutagen
import settings
import logging_util

# Import your modules
from config import FUZZY_THRESHOLD, DEFAULT_VALIDATE_TAGS, DISCOGS_USER_AGENT
from auth import OAuthAuthenticator
from scanner import scan_folder, AudioFile
from metadata import fuzzy_match_track, write_metadata
from discogs_client import DiscogsClient
from ui.dialogs import FileSelectorDialog, MetadataPreviewDialog, SearchResultsDialog

logger = logging.getLogger(__name__)


class WorkerThread(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, object)

    def __init__(self, task, *args, **kwargs):
        super().__init__()
        self.task = task
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            res = self.task(*self.args, **self.kwargs)
            self.finished.emit(True, res)
        except Exception as e:
            logger.error(f"Worker error: {e}")
            self.finished.emit(False, str(e))


class MetadataTaggerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Metadata Tagger")
        self.resize(900, 650)
        self.files: list = []
        self.discogs_client = None
        self.authenticator = OAuthAuthenticator()
        self._init_ui()
        self._setup_workers()
        self._apply_theme()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # --- Tabs ---
        self.tabs = QTabWidget()
        self.tab_files = QWidget()
        self.tab_results = QWidget()
        self.tab_progress = QWidget()
        self.tabs.addTab(self.tab_files, "Files")
        self.tabs.addTab(self.tab_results, "Search Results")
        self.tabs.addTab(self.tab_progress, "Progress")
        main_layout.addWidget(self.tabs)

        # --- File Tab ---
        file_layout = QVBoxLayout(self.tab_files)

        # Top Buttons
        self.btn_select = QPushButton("Select Folder")
        self.btn_scan = QPushButton("Scan & Preview")
        self.btn_search = QPushButton("Search Discogs")
        self.btn_match = QPushButton("Fuzzy Match & Tag")

        # New Auth Button
        self.btn_start_auth = QPushButton("Authenticate Discogs")

        btn_h = QHBoxLayout()
        btn_h.addWidget(self.btn_select)
        btn_h.addWidget(self.btn_scan)
        btn_h.addWidget(self.btn_search)
        btn_h.addWidget(self.btn_match)
        btn_h.addStretch()
        btn_h.addWidget(self.btn_start_auth)
        file_layout.addLayout(btn_h)

        self.lbl_status = QLabel("Ready")
        file_layout.addWidget(self.lbl_status)

        self.tbl_files = QTableView()
        self.tbl_files.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.tbl_files.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.model_files = QStandardItemModel()
        self.model_files.setHorizontalHeaderLabels(
            ["Filename", "Format", "Duration", "Artist", "Album"]
        )
        self.tbl_files.setModel(self.model_files)
        self.tbl_files.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        file_layout.addWidget(self.tbl_files)

        # --- Results Tab ---
        res_layout = QVBoxLayout(self.tab_results)
        res_layout.addWidget(
            QLabel("Select a release to view details and match tracks:")
        )

        self.tbl_results = QTableView()
        self.model_results = QStandardItemModel()
        self.model_results.setHorizontalHeaderLabels(
            ["ID", "Title", "Artist", "Year", "Cover"]
        )
        self.tbl_results.setModel(self.model_results)
        res_layout.addWidget(self.tbl_results)

        # Detail View
        self.txt_details = QTextEdit()
        self.txt_details.setReadOnly(True)
        self.txt_details.setMaximumHeight(150)
        res_layout.addWidget(self.txt_details)

        self.btn_load_details = QPushButton("Load Details for Selection")
        res_layout.addWidget(self.btn_load_details)

        # --- Progress Tab ---
        prog_layout = QVBoxLayout(self.tab_progress)
        self.bar_progress = QProgressBar()
        self.bar_progress.setValue(0)
        prog_layout.addWidget(self.bar_progress)

        self.txt_errors = QTextEdit()
        self.txt_errors.setReadOnly(True)
        prog_layout.addWidget(self.txt_errors)

        # --- Connections ---
        self.btn_select.clicked.connect(self._on_select_folder)
        self.btn_scan.clicked.connect(self._on_scan)
        self.btn_search.clicked.connect(self._on_search_discogs)
        self.btn_match.clicked.connect(self._on_match_and_tag)
        self.btn_start_auth.clicked.connect(self._on_authenticate_discogs)
        self.btn_load_details.clicked.connect(self._on_load_release_details)

    def _setup_workers(self):
        self.worker_scan = WorkerThread(self._do_scan)
        self.worker_scan.finished.connect(self._on_scan_finished)

        # Worker placeholders, actual init happens with args in call methods
        self.worker_search = None
        self.worker_tag = None

    # --- Auth Logic ---
    def _on_authenticate_discogs(self):
        """Trigger the authentication flow entirely in the Main Thread."""
        self.btn_start_auth.setEnabled(False)
        self.lbl_status.setText("Opening browser for Discogs authentication...")

        try:
            # 1. Get Request Token (Logic only)
            auth_url = self.authenticator.get_authorization_url()

            # 2. Open Browser
            webbrowser.open(auth_url)

            # 3. Get Verifier (GUI Dialog)
            dlg = QDialog()
            dlg.setWindowTitle("Discogs Verification")
            dlg.resize(400, 150)
            layout = QVBoxLayout(dlg)
            layout.addWidget(
                QLabel(
                    "Please authorize in your browser, then paste the VERIFIER code:"
                )
            )
            txt = QPlainTextEdit()
            txt.setPlaceholderText("Paste code here...")
            layout.addWidget(txt)
            btn_ok = QPushButton("Confirm")
            layout.addWidget(btn_ok)
            btn_ok.clicked.connect(dlg.accept)

            code = ""
            if dlg.exec() == QDialog.DialogCode.Accepted:
                code = txt.toPlainText().strip()

                self.lbl_status.setText("Exchanging code for token...")
                self.btn_start_auth.setEnabled(False)  # Disable again just in case

                # 4. Exchange Code for Session (Logic only)
                session = self.authenticator.get_authenticated_session(code)
                self.discogs_client = DiscogsClient(session)

                self.lbl_status.setText("Discogs Authenticated successfully.")
                QMessageBox.information(self, "Success", "Connected to Discogs.")
            else:
                self.lbl_status.setText("Authentication cancelled.")

        except Exception as e:
            self.lbl_status.setText("Auth Error.")
            QMessageBox.warning(self, "Error", str(e))
        finally:
            self.btn_start_auth.setEnabled(True)

    # --- File Logic ---
    def _on_select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.lbl_status.setText(f"Selected: {folder}")
            self.base_dir = Path(folder)

    def _on_scan(self):
        if not hasattr(self, "base_dir"):
            QMessageBox.warning(self, "Warning", "Please select a folder first.")
            return
        self.tabs.setCurrentIndex(0)
        self.lbl_status.setText("Scanning...")
        self.bar_progress.setValue(0)

        # Instantiate worker with task and arguments
        self.worker_scan = WorkerThread(self._do_scan)
        self.worker_scan.finished.connect(self._on_scan_finished)
        self.worker_scan.start()  # Call start without args

    def _do_scan(self):
        return scan_folder(self.base_dir)

    def _on_scan_finished(self, success, data):
        if not success:
            QMessageBox.critical(self, "Scan Error", data)
            return
        self.files, failed = data
        if not self.files:
            QMessageBox.information(self, "Info", "No valid audio files found.")
            return

        self.model_files.setRowCount(0)
        for f in self.files:
            row = [
                QStandardItem(str(f.filename)),
                QStandardItem(f.format_name),
                QStandardItem(f"{f.duration:.1f}s"),
                QStandardItem(f.tags.get("artist", "")),
                QStandardItem(f.tags.get("album", "")),
            ]
            self.model_files.appendRow(row)

        self.lbl_status.setText(f"Found {len(self.files)} files.")

    # --- Discogs Logic ---
    def _on_search_discogs(self):
        if not self.files:
            QMessageBox.warning(self, "Warning", "Scan files first.")
            return
        if not self.discogs_client:
            QMessageBox.warning(
                self, "Warning", "Please authenticate with Discogs first."
            )
            return

        # Get Artist/Album from first file or folder structure
        first_file = self.files[0]
        # Fallback logic from prompt
        art = first_file.tags.get(
            "artist",
            (
                self.base_dir.parent.name
                if hasattr(self.base_dir, "parent")
                else "Unknown"
            ),
        )
        alb = first_file.tags.get("album", self.base_dir.name)

        # Show confirmation dialog (simplified)
        self.lbl_status.setText("Searching Discogs...")
        self.tabs.setCurrentIndex(1)

        # Instantiate worker with arguments
        self.worker_search = WorkerThread(self._do_search, art, alb)
        self.worker_search.finished.connect(self._on_search_finished)
        self.worker_search.start()

    def _do_search(self, art, alb):
        if not self.discogs_client:
            raise Exception("Not authenticated")

        results = []
        for p in range(1, 3):  # Check first 2 pages
            res = self.discogs_client.search_releases(art, alb, page=p)
            results.extend(res)
            if not res:
                break
        return results

    def _on_search_finished(self, success, data):
        if not success or not data:
            QMessageBox.warning(
                self, "Search Failed", "No results found. Try different search terms."
            )
            return
        self.results_data = data
        self.model_results.setRowCount(0)
        for r in data:
            row = [
                QStandardItem(str(r["id"])),
                QStandardItem(r["title"]),
                QStandardItem(r["artist"]),
                QStandardItem(str(r["year"])),
                QStandardItem(r.get("image_url", "")),
            ]
            self.model_results.appendRow(row)
        self.lbl_status.setText(f"Found {len(data)} releases.")

    def _on_load_release_details(self):
        sel = self.tbl_results.selectionModel().selection()
        if not sel.indexes():
            return
        sel_row = sel.indexes()[0].row()
        res_id = self.results_data[sel_row]["id"]

        if not self.discogs_client:
            return

        self.lbl_status.setText("Loading details...")
        release = self.discogs_client.get_release(res_id)

        if release:
            txt = f"Title: {release['title']}\nArtist: {release['artist']}\nYear: {release['year']}\n\nTracks:\n"
            for t in release.get("tracks", []):
                txt += f"{t['position']}. {t['title']}\n"
            self.txt_details.setPlainText(txt)
            self.lbl_status.setText("Details loaded.")
        else:
            self.lbl_status.setText("Failed to load details.")

    # --- Tagging Logic ---
    def _on_match_and_tag(self):
        if not hasattr(self, "results_data") or not self.results_data:
            QMessageBox.warning(self, "Warning", "No search results available.")
            return

        sel = self.tbl_results.selectionModel().selection()
        if not sel.indexes():
            QMessageBox.information(self, "Info", "Please select a release first.")
            return

        sel_row = sel.indexes()[0].row()
        sel_data = self.results_data[sel_row]

        # Get track list for this release to match against
        # Note: We must ensure get_release is called to get the full tracklist if we haven't yet
        if not "tracks" in sel_data or not sel_data["tracks"]:
            if self.discogs_client:
                sel_data = self.discogs_client.get_release(sel_data["id"])
                # Update internal list too
                self.results_data[sel_row] = sel_data

        if not sel_data.get("tracks"):
            QMessageBox.warning(
                self, "Error", "Could not fetch tracklist for this release."
            )
            return

        matches = []
        for f in self.files:
            # Extract clean name
            clean_name = Path(f.filename).stem
            # Match against current release tracks
            matched_title, score = fuzzy_match_track(
                clean_name, [t["title"] for t in sel_data["tracks"]], FUZZY_THRESHOLD
            )

            if matched_title:
                matches.append((f, matched_title))
            else:
                # Optionally add to a separate unmatched list or just skip
                pass

        #   Corrected Tagging Start logic:
        if not matches:
            QMessageBox.warning(
                self, "Match Failed", "No tracks matched automatically."
            )
            return

        self.bar_progress.setValue(0)
        self.lbl_status.setText(f"Tagging {len(matches)} files...")
        self.txt_errors.clear()

        # Instantiate worker with arguments
        self.worker_tag = WorkerThread(self._do_tag, matches, sel_data)
        self.worker_tag.finished.connect(self._on_tag_finished)
        self.worker_tag.progress.connect(self._update_progress)
        self.worker_tag.start()

    def _do_tag(self, matches, release_data):
        total = len(matches)
        errors = []
        art_url = release_data.get("image_url", "")
        art_bytes = None
        if art_url and settings.SETTINGS.get("embed_artwork", True):
            import requests

            try:
                r = requests.get(art_url, timeout=10)
                art_bytes = r.content if r.status_code == 200 else None
            except:
                pass

        success_count = 0
        for i, (file_obj, track_title) in enumerate(matches):
            tags = {
                "title": track_title,
                "artist": release_data["artist"],
                "album": release_data["title"],
                "tracknumber": str(i + 1),  # Or try to find track number from release
                "date": str(release_data["year"]) if release_data["year"] else "",
                "genre": release_data["genre"],
            }
            success = write_metadata(
                str(file_obj.path), tags, art_bytes, file_obj.format_name
            )
            if success:
                success_count += 1
            else:
                errors.append(file_obj.path.name)

            self.progress.emit(
                int((i + 1) / total * 100), f"Tagged {file_obj.filename}"
            )

        return success_count == total, errors

    def _update_progress(self, val, msg):
        self.bar_progress.setValue(val)
        self.lbl_status.setText(msg)

    def _on_tag_finished(self, success, data):
        if success:
            QMessageBox.information(self, "Success", "Tagging completed successfully.")
        else:
            QMessageBox.warning(
                self, "Partial Success", f"Some files failed:\n{chr(10).join(data)}"
            )
        self.bar_progress.setValue(100)
        self.lbl_status.setText("Ready")

    def _apply_theme(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #2b2b2b; color: #ffffff; }
            QTabWidget::pane { border: 1px solid #555; background: #333; }
            QTabBar::tab { background: #444; color: #ccc; padding: 8px; }
            QTabBar::tab:selected { background: #2b2b2b; color: #fff; }
            QPushButton { background: #0078d4; color: white; border: none; padding: 8px; border-radius: 4px; }
            QPushButton:hover { background: #0063b1; }
            QTableView { background: #3a3a3a; border: 1px solid #555; alternate-background-color: #444; }
            QHeaderView::section { background: #2b2b2b; color: #fff; padding: 4px; }
            QTextEdit { background: #333; color: #ddd; border: 1px solid #555; }
            QLabel { color: #eee; }
        """)


def main():
    logging_util.setup_logging()
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    settings.SETTINGS.init_defaults()
    window = MetadataTaggerWindow()
    window.show()
    sys.exit(app.exec())
