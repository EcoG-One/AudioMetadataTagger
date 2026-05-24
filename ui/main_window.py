"""Main Application Window & Workflow Controller."""
import sys
import os
import logging
import webbrowser
from pathlib import Path
from PyQt6.QtWidgets import (QMainWindow, QTabWidget, QTableView, 
                             QProgressBar, QLabel, QPushButton, QHeaderView, QMessageBox,
                             QFileDialog, QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
                             QPlainTextEdit, QDialog)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QStandardItemModel, QStandardItem
import settings
import logging_util
from config import FUZZY_THRESHOLD, DEFAULT_VALIDATE_TAGS, DISCOGS_USER_AGENT
from auth import OAuthAuthenticator
from scanner import scan_folder, AudioFile
from metadata import fuzzy_match_track, write_tags
from discogs_client import DiscogsClient
from ui.dialogs import FileSelectorDialog, MetadataPreviewDialog, SearchResultsDialog

logger = logging.getLogger(__name__)

class WorkerThread(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, object)
    
    def __init__(self, task, *args, with_progress=False, progress_callback=None, **kwargs):
        super().__init__()
        self.task = task
        self.args = args
        self.with_progress = with_progress or progress_callback is not None
        self.progress_callback = progress_callback or self.progress
        self.kwargs = kwargs
        
    def run(self):
        try:
            if self.with_progress:
                res = self.task(self.progress_callback, *self.args, **self.kwargs)
            else:
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
        # Auto-authenticate on startup using persisted credentials
        self._auto_authenticate_discogs()

    def _auto_authenticate_discogs(self):
        """Attempts to automatically authenticate using stored tokens."""
        if not self.authenticator:
            return

        session = self.authenticator.restore_session()

        if session:
            self.discogs_client = DiscogsClient(session)
            self.lbl_status.setText("Discogs Session Restored.")
            self.lbl_status.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.lbl_status.setText(
                "Discogs not authenticated. Click 'Authenticate Discogs' to login."
            )
            self.lbl_status.setStyleSheet("color: orange;")

    def _on_authenticate_discogs(self):
        """Handles manual authentication flow (falls back if token invalid/expired)."""
        self.btn_start_auth.setEnabled(False)
        self.lbl_status.setText("Opening browser for Discogs authentication...")

        try:
            auth_url = self.authenticator.get_authorization_url()
            webbrowser.open(auth_url)

            dlg = QDialog(self)
            dlg.setWindowTitle("Discogs Verification Code")
            layout = QVBoxLayout()
            lbl = QLabel("Visit the URL above, authorize, and paste the code here:")
            txt = QLineEdit()
            txt.setPlaceholderText("Paste code here...")
            btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)

            layout.addWidget(lbl)
            layout.addWidget(txt)
            layout.addWidget(btns)
            dlg.setLayout(layout)

            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)

            if dlg.exec() == QDialog.Accepted:
                code = txt.toPlainText().strip()
                if not code:
                    QMessageBox.warning(
                        self, "Missing Code", "Verification code cannot be empty."
                    )
                    return

                self.lbl_status.setText("Exchanging code for token...")

                session = self.authenticator.get_authenticated_session(code)
                self.discogs_client = DiscogsClient(session)

                self.lbl_status.setText("Discogs Authenticated successfully.")
                self.lbl_status.setStyleSheet("color: green; font-weight: bold;")
                QMessageBox.information(
                    self,
                    "Success",
                    "Connected to Discogs. Your token is now saved locally.",
                )
        except Exception as e:
            QMessageBox.critical(self, "Authentication Error", str(e))
        finally:
            self.btn_start_auth.setEnabled(True)

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
            ["Artist", "Album", "Filename", "Format", "Duration"]
        )
        self.tbl_files.setModel(self.model_files)
        self.tbl_files.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tbl_files.setColumnWidth(0, 150)
        self.tbl_files.setColumnWidth(1, 200)
        self.tbl_files.setColumnWidth(2, 350)
        self.tbl_files.setColumnWidth(3, 50)
        self.tbl_files.setColumnWidth(4, 60)
        file_layout.addWidget(self.tbl_files)

        # --- Results Tab ---
        res_layout = QVBoxLayout(self.tab_results)
        res_layout.addWidget(QLabel("Select a release to view details and match tracks:"))

        self.tbl_results = QTableView()
        self.model_results = QStandardItemModel()
        self.model_results.setHorizontalHeaderLabels(
            ["ID", "Album", "Artist", "Year", "Cover"]
        )
        self.tbl_results.setModel(self.model_results)
        self.tbl_results.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.tbl_results.setColumnWidth(0, 80)
        self.tbl_results.setColumnWidth(1, 200)
        self.tbl_results.setColumnWidth(2, 150)
        self.tbl_results.setColumnWidth(3, 50)
        self.tbl_results.setColumnWidth(4, 450)
        res_layout.addWidget(self.tbl_results)

        # Selected Release View
        self.rel_box = QHBoxLayout()

        # Release Album Art
        self.album_art = QLabel()
        self.album_art.setFixedSize(256, 256)
        self.album_art.setScaledContents(True)
        self.album_art.setPixmap(
            QPixmap("ui.images/default_album_art.png")
        )  # Replace with actual cover image loading
        self.rel_box.addWidget(self.album_art)

        # Detail View
        self.txt_details = QTextEdit()
        self.txt_details.setReadOnly(True)
        self.txt_details.setMaximumHeight(256)
        self.rel_box.addWidget(self.txt_details)

        res_layout.addLayout(self.rel_box)

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
        # self.btn_load_details.clicked.connect(self._on_load_release_details)
        self._connect_results_selection_handler()

    def _connect_results_selection_handler(self):
        """Load release details automatically when the selected result row changes."""
        selection_model = self.tbl_results.selectionModel()
        if selection_model is not None:
            selection_model.currentRowChanged.connect(self._on_results_row_selected)

    def _on_results_row_selected(self, current, previous):
        if not current.isValid():
            return
        if not hasattr(self, "results_data"):
            return
        if current.row() < 0 or current.row() >= len(self.results_data):
            return

        self._on_load_release_details(current.row())

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
            layout.addWidget(QLabel("Please authorize in your browser, then paste the VERIFIER code:"))
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
                self.btn_start_auth.setEnabled(False) # Disable again just in case

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
            self._on_scan()

    def _on_scan(self):
        if not hasattr(self, 'base_dir'):
            QMessageBox.warning(self, "Warning", "Please select a folder first.")
            return
        self.tabs.setCurrentIndex(0)
        self.lbl_status.setText("Scanning...")
        self.bar_progress.setValue(0)

        # Instantiate worker with task and arguments
        self.worker_scan = WorkerThread(self._do_scan)
        self.worker_scan.finished.connect(self._on_scan_finished)
        self.worker_scan.start() # Call start without args

    def _do_scan(self):
        return scan_folder(self.base_dir)

    def _on_scan_finished(self, success, data):
        if not success:
            QMessageBox.critical(self, "Scan Error", data)
            return
        self.files, self.failed = data
        if not self.files:
            QMessageBox.information(self, "Info", "No valid audio files found.")
            return

        self.model_files.setRowCount(0)
        for f in self.files:
            min = round(f.duration.value) // 60
            sec = round(f.duration.value) % 60

            row = [
                QStandardItem(
                    f.tags.get("albumartist", "") or f.tags.get("artist", "")
                ),
                QStandardItem(f.tags.get("album", "")),
                QStandardItem(str(f.filename)),
                QStandardItem(f.format_name),
                QStandardItem(f"{min}:{sec}"),
            ]
            self.model_files.appendRow(row)

        self.lbl_status.setText(f"Found {len(self.files)} files. Select one for search based on selection's Artist and Album. (Double Click to edit tags directly)")
        sel = self.tbl_files.selectionModel().selection()

    # --- Discogs Logic ---
    def _on_search_discogs(self):
        if not self.files and not self.failed:
            QMessageBox.warning(self, "Warning", "Scan files first.")
            return
        if not self.discogs_client:
            QMessageBox.warning(self, "Warning", "Please authenticate with Discogs first.")
            return

        # Get Artist/Album from selected file or folder structure
        sel = self.tbl_files.selectionModel().selection()
        if not sel.indexes():
            sel_row = 0  # Default to first file if none selected
        else:
            sel_row = sel.indexes()[0].row()
        art = self.model_files.item(sel_row, 0).text()  # Artist column
        alb = self.model_files.item(sel_row, 1).text()  # Album column

        # Show confirmation dialog with editable fields
        '''dlg = MetadataPreviewDialog(art, alb, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_art, new_alb = dlg.get_metadata()
            self.tabs.setCurrentIndex(1)
            self.lbl_status.setText("Searching Discogs...")
            self.worker_search.start(new_art, new_alb) '''

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
        for p in range(1, 3): # Check first 2 pages
            res = self.discogs_client.search_releases(art, alb, page=p)
            results.extend(res)
            if not res: break
        return results

    def _on_search_finished(self, success, data):
        if not success or not data:
            QMessageBox.warning(self, "Search Failed", "No results found. Try different search terms.")
            return
        self.results_data = data
        self.model_results.setRowCount(0)
        for r in data:
            title = r["title"].split(" - ")[-1].strip()  # Album title (after "Artist - Album")
            artist = r["title"].split(" - ")[0].strip()  # Artist name (before "Artist - Album")
            row = [
                QStandardItem(str(r["id"])),
                QStandardItem(title),
                QStandardItem(artist),
                QStandardItem(str(r["year"])),
                QStandardItem(r.get("image_url", "")),
            ]
            self.model_results.appendRow(row)
        self.lbl_status.setText(f"Found {len(data)} releases.")
        self.tbl_results.setCurrentIndex(self.tbl_results.model().index(0, 0))   # Select first row by default


    def set_album_art(self, art_url):
        """
        Sets release album art.
        """
        if art_url:
            try:
                art_bytes = (
                self.discogs_client.get_album_artwork(art_url))
                img = QImage.fromData(art_bytes)
                pix = QPixmap.fromImage(img)
                self.album_art.setPixmap(
                    pix.scaled(
                        self.album_art.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return
            except Exception as e:
                self.album_art.setPixmap(
                    QPixmap("images/default_album_art.png")
                    if os.path.exists("static/images/default_album_art.png")
                    else QPixmap()
                )
                self.lbl_status.setText("Base64 album art decode error:" + str(e))
        else:
            # Fallback image
            self.album_art.setPixmap(
                QPixmap("images/default_album_art.png")
                if os.path.exists("images/default_album_art.png")
                else QPixmap()
            )
        return

    def _on_load_release_details(self, sel_row=None):
        if not hasattr(self, "results_data"):
            return
        if isinstance(sel_row, bool):
            sel_row = None

        if sel_row is None:
            current = self.tbl_results.currentIndex()
            if current.isValid():
                sel_row = current.row()
            else:
                sel = self.tbl_results.selectionModel().selection()
                if not sel.indexes():
                    return
                sel_row = sel.indexes()[0].row()

        if sel_row < 0 or sel_row >= len(self.results_data):
            return

        item = self.results_data[sel_row]
        res_id = item["id"]
        master_id = item.get("master_id")

        if not self.discogs_client:
            return

        # 1. Try fetching the specific Release first
        release = self.discogs_client.get_release(res_id)

        # 2. Fallback: If 404 (empty dict) and Master ID exists, fetch Master
        if not release and master_id:
            self.lbl_status.setText(
                f"Release {res_id} not found. Fetching Master ({master_id})..."
            )
            release = self.discogs_client.get_master(master_id)

        if release and release.get("title"):
            txt = f"Title: {release['title']}\nArtist: {release['artist']}\nYear: {release['year']}\n\nTracks:\n"
            for t in release.get("tracks", []):
                txt += f"{t['position']}. {t['title']}\n"
            self.txt_details.setPlainText(txt)
            self.set_album_art(release.get("image_url"))

            self.lbl_status.setText("Details loaded.")
            self.model_files.setRowCount(0)
            self.model_files.setHorizontalHeaderLabels(
                ["Artist", "Album", "Filename", "Song Title", "Nmb", "Time", "Format"]
            )
            self.tbl_files.setColumnWidth(0, 150)
            self.tbl_files.setColumnWidth(1, 150)
            self.tbl_files.setColumnWidth(2, 250)
            self.tbl_files.setColumnWidth(3, 150)
            self.tbl_files.setColumnWidth(4, 30)
            self.tbl_files.setColumnWidth(5, 40)
            self.tbl_files.setColumnWidth(6, 60)
            for f, t in zip(self.files, release.get("tracks", [])):
                min = round(f.duration.value) // 60
                sec = round(f.duration.value) % 60
                row = [
                    QStandardItem(release["artist"]),
                    QStandardItem(release["title"]),
                    QStandardItem(str(f.filename)),
                    QStandardItem(t["title"]),
                    QStandardItem(t["position"]),
                    QStandardItem(f"{min}:{sec:02}"),
                    QStandardItem(release["format"]),
                ]
                self.model_files.appendRow(row)
        else:
            self.lbl_status.setText(f"Failed to load details for ID {res_id}.")

    def fuzzy_match_tracks(self, track_titles):
        # Proceed with matching
        matches = []
        for f in self.files:
            clean_name = Path(f.filename).stem
            matched_title, score = fuzzy_match_track(
                clean_name, [t["title"] for t in track_titles], FUZZY_THRESHOLD
            )
            if matched_title:
                matches.append((f, matched_title))

        if not matches:
            QMessageBox.warning(
                self, "Match Failed", "No tracks matched automatically."
            )
            return matches

    # --- Tagging Logic ---
    def _on_match_and_tag(self):
        if not self.discogs_client:
            QMessageBox.warning(
                self, "Error", "Please authenticate with Discogs first."
            )
            return
        if not hasattr(self, "results_data") or not self.results_data:
            QMessageBox.warning(self, "Warning", "No search results available.")
            return

        sel = self.tbl_results.selectionModel().selection()
        if not sel.indexes():
            QMessageBox.information(self, "Info", "Please select a release first.")
            return

        sel_row = sel.indexes()[0].row()
        sel_data = self.results_data[sel_row]  # This is the raw search result

        fetched_release = None

        # Try to get the tracks
        tracks = sel_data.get("tracks")

        # If tracks missing or empty, try fetching full details (with fallback)
        if not tracks:
            res_id = sel_data["id"]
            master_id = sel_data.get("master_id")
            fetched_release = self.discogs_client.get_release(res_id)

            if not fetched_release and master_id:
                fetched_release = self.discogs_client.get_master(master_id)

            if fetched_release:
                tracks = fetched_release.get("tracks", [])
                # Update local display if we successfully fetched details
                if not self.results_data[sel_row].get("tracks"):
                    # Optional: Update the table result row with details
                    pass

        if not tracks:
            QMessageBox.warning(
                self, "Error", "Could not fetch tracklist for this release."
            )
            return

        # Proceed with matching
        matches = []
        for f, t in zip(self.files, tracks):
            matches.append((f, t["title"]))

        if not matches:
            QMessageBox.warning(
                self, "Match Failed", "No tracks matched automatically."
            )
            return

        # ... (Tagging logic) ...

        # NOTE: When tagging, we use sel_data (from search results) which might not have the full master details
        # We should ideally update sel_data['artist'], 'title' etc from 'fetched_release' before tagging
        # To keep it simple and safe, we will use the fetched data if available

        release_source = fetched_release or sel_data
        release_data_to_use = {
            "artist": release_source.get("artist") or sel_data.get("artist", ""),
            "album_artist": release_source.get("albumartist") or sel_data.get("albumartist", ""),
            "title": release_source.get("title") or sel_data.get("title", ""),
            "year": release_source.get("year") or sel_data.get("year", ""),
            "genre": release_source.get("genre", ""),
            "image_url": release_source.get("image_url")
            or sel_data.get("image_url", ""),
        }

        self.bar_progress.setValue(0)
        self.lbl_status.setText(f"Tagging {len(matches)} files...")
        self.txt_errors.clear()

        self.worker_tag = WorkerThread(self._do_tag, matches, release_data_to_use, with_progress=True)
        self.worker_tag.finished.connect(self._on_tag_finished)
        self.worker_tag.progress.connect(self._update_progress)
        self.worker_tag.start()

    def _do_tag(self, progress, matches, release_data):
        total = len(matches)
        errors = []
        art_url = release_data.get('image_url', '')
        art_bytes = None
        if art_url and settings.SETTINGS.get('embed_artwork', True):
            try:
                art_bytes = (
                    self.discogs_client.get_album_artwork(art_url))
                if not art_bytes:
                    logger.warning("No images available for release")
            except Exception as e:
                logger.error(f"Failed to download artwork: {e}")

        success_count = 0
        for i, (file_obj, track_title) in enumerate(matches):
            tags = {
                'title': track_title,
                'artist': release_data['artist'],
                'albumartist': release_data['album_artist'],
                'album': release_data['title'],
                'tracknumber': str(i+1), # Or try to find track number from release
                'date': str(release_data['year']) if release_data['year'] else '',
                'genre': release_data['genre'], 
                'comment': release_data.get('notes', '')
            }
            #   success = write_metadata(str(file_obj.path), tags, art_bytes, file_obj.format_name)
            success = write_tags(
                str(file_obj.path),
                tags,
                art_bytes,
                overwrite = False
            )
            if success:
                success_count += 1
            else:
                errors.append(file_obj.path.name)

            progress.emit(int((i+1)/total*100), f"Tagged {file_obj.filename}")

        return success_count == total, errors

    def _update_progress(self, val, msg):
        self.bar_progress.setValue(val)
        self.lbl_status.setText(msg)

    def _on_tag_finished(self, success, data):
        if success:
            QMessageBox.information(self, "Success", "Tagging completed successfully.")
        else:
            QMessageBox.warning(self, "Partial Success", f"Some files failed:\n{chr(10).join(data)}")
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
            QTableView { color: white; background: #3a3a3a; border: 1px solid #555; alternate-background-color: #444; }
            QTableView::item:selected { background: #0078d4; color: white; }
            QHeaderView::section { background: #2b2b2b; color: #fff; padding: 4px; }
            QTextEdit { background: #333; color: #ddd; border: 1px solid #555; }
            QMessageBox { background: #2b2b2b; color: #fff; }
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
