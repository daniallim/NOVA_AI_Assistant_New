import sys

from PySide6.QtWidgets import QApplication

from ui import NovaWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("NOVA")
    app.setOrganizationName("NOVA AI")
    app.setStyle("Fusion")

    window = NovaWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
