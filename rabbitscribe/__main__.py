import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from rabbitscribe.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("RabbitScribe")
    app.setOrganizationName("rabbitscribe")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
