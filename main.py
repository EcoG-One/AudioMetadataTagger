"""Application entry point."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metadata_tagger.ui.main_window import main
from PyQt6.QtWidgets import QApplication

if __name__ == "__main__":
    app = QApplication(sys.argv)
    main()
    sys.exit(app.exec())
