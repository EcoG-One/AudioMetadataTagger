"""Main Application Window & Workflow Controller."""

import sys
import os
import json
import time
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
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
import mutagen
import logging
import webbrowser
from config import FUZZY_THRESHOLD, DEFAULT_VALIDATE_TAGS
from auth import OAuthAuthenticator
from scanner import scan_folder, AudioFile
from metadata import fuzzy_match_track, write_metadata
from discogs_client import DiscogsClient
from ui.dialogs import (
    FileSelectorDialog,
    MetadataPreviewDialog,
    SearchResultsDialog,
    DiscogsVerifierDialog,
)
import settings
import logging_util

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

        # Tabs
        self.tabs = QTabWidget()
        self.tab_files = QWidget()
        self.tab_results = QWidget()
        self.tab_progress = QWidget()
        self.tabs.addTab(self.tab_files, "Files")
        self.tabs.addTab(self.tab_results, "Search Results")
        self.tabs.addTab(self.tab_progress, "Progress")
        main_layout.addWidget(self.tabs)

        # File Tab
        file_layout = QVBoxLayout(self.tab_files)
        self.btn_select = QPushButton("Select Folder")
        self.btn_scan = QPushButton("Scan & Preview")
        self.btn_search = QPushButton("Search Discogs")
        self.btn_match = QPushButton("Fuzzy Match & Tag")
        self.btn_start_auth = QPushButton("Authenticate Discogs")
        btn_h = QHBoxLayout()

        btn_h.addWidget(self.btn_select)
        btn_h.addWidget(self.btn_scan)
        btn_h.addWidget(self.btn_search)
        btn_h.addWidget(self.btn_match)
        btn_h.addWidget(self.btn_start_auth)
        file_layout.addLayout(btn_h)

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

        # Results Tab
        res_layout = QVBoxLayout(self.tab_results)
        self.tbl_results = QTableView()
        self.model_results = QStandardItemModel()
        self.model_results.setHorizontalHeaderLabels(
            ["Release ID", "Title", "Artist", "Year", "Image URL"]
        )
        self.tbl_results.setModel(self.model_results)
        res_layout.addWidget(self.tbl_results)

        # Progress Tab
        prog_layout = QVBoxLayout(self.tab_progress)
        self.lbl_status = QLabel("Ready")
        self.lbl_progress_info = QLabel("")
        self.bar_progress = QProgressBar()
        self.bar_progress.setValue(0)
        self.txt_errors = QTextEdit()
        self.txt_errors.setReadOnly(True)
        prog_layout.addWidget(self.lbl_status)
        prog_layout.addWidget(self.lbl_progress_info)
        prog_layout.addWidget(self.bar_progress)
        prog_layout.addWidget(self.txt_errors)

        # Connect signals
        self.btn_select.clicked.connect(self._on_select_folder)
        self.btn_scan.clicked.connect(self._on_scan)
        self.btn_start_auth = QPushButton("Authenticate Discogs")
        btn_h.addWidget(self.btn_start_auth)
        self.btn_start_auth.clicked.connect(self._on_authenticate_discogs)

    def _on_authenticate_discogs(self):
        """Trigger the authentication flow."""
        self.btn_start_auth.setEnabled(False)
        self.lbl_status.setText("Initiating Discogs authentication...")

        try:
            # 1. Get Request Token (Logic only)
            url = self.authenticator.get_authorization_url()
            print(f"Auth URL: {url}")

            # 2. Open Browser (Main Thread)
            import webbrowser

            webbrowser.open(url)

            # 3. Get Verifier (Main Thread)
            dlg = DiscogsVerifierDialog(self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                verifier = dlg.get_verifier_code()

                self.lbl_status.setText("Exchanging code for token...")

                # 4. Exchange Code for Session (Logic only)
                try:
                    authenticated_session = (
                        self.authenticator.get_authenticated_session(verifier)
                    )
                    self.discogs_client = DiscogsClient(authenticated_session)
                    self.lbl_status.setText("Discogs Authenticated successfully.")
                    QMessageBox.information(
                        self, "Success", "You are now connected to Discogs."
                    )
                except Exception as e:
                    self.lbl_status.setText("Authentication failed.")
                    QMessageBox.warning(self, "Error", f"Could not verify code: {e}")
            else:
                self.lbl_status.setText("Authentication cancelled.")
        except Exception as e:
            self.lbl_status.setText("Auth Error.")
            QMessageBox.warning(self, "Error", str(e))
        finally:
            self.btn_start_auth.setEnabled(True)

    def _do_auth(self):
        self.authenticator = OAuthAuthenticator()
        session = self.authenticator.get_oauth_session()
        return session

    def _on_auth_finished(self, success, session):
        self.btn_start_auth.setEnabled(True)
        if success and session:
            self.discogs_client = DiscogsClient(session)
            self.lbl_status.setText("Discogs Authenticated successfully.")
            QMessageBox.information(
                self, "Success", "You are now connected to Discogs."
            )
        else:
            self.lbl_status.setText("Authentication failed.")
            QMessageBox.warning(self, "Error", "Could not authenticate with Discogs.")

    def _setup_workers(self):
        self.worker_scan = WorkerThread(self._do_scan)
        self.worker_scan.finished.connect(self._on_scan_finished)

        self.worker_search = WorkerThread(self._do_search)
        self.worker_search.finished.connect(self._on_search_finished)

        self.worker_tag = WorkerThread(self._do_tag)
        self.worker_tag.progress.connect(self._update_progress)
        self.worker_tag.finished.connect(self._on_tag_finished)

    def _on_select_folder(self):
        dlg = FileSelectorDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            path = dlg.get_path()
            if path:
                self.lbl_status.setText(f"Selected: {path}")
                self.base_dir = Path(path)

    def _on_scan(self):
        if not hasattr(self, "base_dir"):
            QMessageBox.warning(self, "Warning", "Please select a folder first.")
            return
        self.tabs.setCurrentIndex(0)
        self.lbl_status.setText("Scanning...")
        self.bar_progress.setValue(0)
        self.worker_scan.start()

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
        self.btn_scan.setEnabled(True)

    def _on_search_discogs(self):
        if not self.files:
            QMessageBox.warning(self, "Warning", "Scan files first.")
            return

        first_tags = self.files[0].tags
        art = first_tags.get(
            "artist",
            (
                os.path.basename(self.base_dir.parent.name)
                if hasattr(self.base_dir.parent, "name")
                else ""
            ),
        )
        alb = first_tags.get("album", os.path.basename(self.base_dir.name))

        dlg = MetadataPreviewDialog(art, alb, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_art, new_alb = dlg.get_metadata()
            self.tabs.setCurrentIndex(1)
            self.lbl_status.setText("Searching Discogs...")
            self.worker_search.start(new_art, new_alb)

    def _do_search(self, art, alb):
        if not self.discogs_client:
            self.authenticator.exchange_verifier_for_token(
                QMessageBox.question(
                    self,
                    "OAuth",
                    "Paste the verifier code from the browser:\n\n",
                    QMessageBox.StandardButton.Ok,
                )
            )
            self.discogs_client = DiscogsClient(
                self.authenticator.get_authenticated_session()
            )

        results = []
        for p in range(1, 4):
            res = self.discogs_client.search_releases(art, alb, page=p)
            results.extend(res)
            if not res:
                break
        return results

    def _on_search_finished(self, success, data):
        if not success or not data:
            QMessageBox.warning(
                self, "Search Failed", "No results found. Check connection or query."
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

        # Fuzzy match
        matches = []
        unmatched = []
        for f in self.files:
            matched_title, score = fuzzy_match_track(
                f.filename, [t["title"] for t in sel_data["tracks"]], FUZZY_THRESHOLD
            )
            if matched_title:
                matches.append((f, matched_title))
            else:
                unmatched.append(f)

        if not matches:
            QMessageBox.warning(
                self, "Match Failed", "No tracks matched. Try a different release."
            )
            return

        # Tagging
        self.bar_progress.setValue(0)
        self.lbl_progress_info.setText(f"Tagging {len(matches)} files...")
        self.txt_errors.clear()
        self.worker_tag.start(matches, sel_data)

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

        for i, (file_obj, track_title) in enumerate(matches):
            tags = {
                "title": track_title,
                "artist": release_data["artist"],
                "album": release_data["title"],
                "tracknumber": str(file_obj.tags.get("tracknumber", i + 1)),
                "date": str(release_data["year"]) if release_data["year"] else "",
                "genre": release_data["genre"],
            }
            success = write_metadata(
                str(file_obj.path), tags, art_bytes, file_obj.format_name
            )
            self.progress.emit(
                int((i + 1) / total * 100), f"Tagged {file_obj.filename}"
            )
            if not success:
                errors.append(file_obj.path.name)

        return success if not errors else False, errors

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
    app = QApplication(sys.argv)
    settings.SETTINGS.init_defaults()
    window = MetadataTaggerWindow()
    window.show()
    sys.exit(app.exec())


# Fallback entry point
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication

    main()
