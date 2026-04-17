import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QTextEdit, QTableView, QComboBox,
                             QLabel, QSplitter, QSizePolicy, QFileDialog, QAction, QShortcut, QProgressDialog)
from PyQt5.QtSql import QSqlDatabase, QSqlQuery, QSqlQueryModel
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QStringListModel
from PyQt5.QtGui import QFont, QColor, QSyntaxHighlighter
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import os
import re

from PyQt5.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
from PyQt5.QtCore import QRegExp

from PyQt5.QtWidgets import QApplication, QPlainTextEdit, QCompleter
from PyQt5.QtCore import Qt
import sys

keywords = [
    "add", "all", "alter", "and", "any", "as", "asc",
    "backup", "between", "by"
    "case", "check", "column", "commit", "constraint", "create",
    "database", "default", "delete", "desc", "distinct", "drop",
    "exists",
    "from", "full",
    "group",
    "having",
    "in", "index", "inner", "insert", "is", "into",
    "join",
    "left", "like", "limit",
    "not", "null",
    "on", "or", "order", "outer",
    "primary", "procedure",
    "reindex", "replace", "rollback",
    "rownum", "savepoint", "select", "set",
    "table", "top", "truncate",
    "union", "unique", "update", "using",
    "values", "vacuum", "view",
    "when", "where"
]

class Editor(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.model = QStringListModel(keywords)
        self.completer = QCompleter(self.model, self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setWidget(self)
        self.completer.setCompletionMode(QCompleter.PopupCompletion)
        self.completer.activated.connect(self.insert_completion)

    def set_db_keywords(self, new_keywords):
        self.model.setStringList(keywords + new_keywords)



    def keyPressEvent(self, event):
        if self.completer.popup().isVisible():
            if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
                event.ignore()
                return

        super().keyPressEvent(event)

        prefix = self.text_under_cursor()
        if len(prefix) < 2 or self.text_under_cursor() == self.completer.popup().currentIndex().data():
            self.completer.popup().hide()
            return

        if prefix != self.completer.completionPrefix():
            self.completer.setCompletionPrefix(prefix)
            self.completer.popup().setCurrentIndex(
                self.completer.completionModel().index(0, 0)
            )

        cr = self.cursorRect()
        cr.setWidth(self.completer.popup().sizeHintForColumn(0))
        self.completer.complete(cr)

    def insert_completion(self, completion):
        tc = self.textCursor()
        extra = len(completion) - len(self.completer.completionPrefix())
        tc.movePosition(tc.Left)
        tc.movePosition(tc.EndOfWord)
        if completion != self.completer.completionPrefix():
            tc.insertText(completion[-extra:])
        tc.insertText(" ")
        self.setTextCursor(tc)

    def text_under_cursor(self):
        tc = self.textCursor()
        tc.select(tc.WordUnderCursor)
        return tc.selectedText()


class SQLHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        self.set_keywords([])

    def reset(self):
        self.rules = []
        self.set_keywords([])

    def set_keywords(self, new_keywords):
        # Keyword format
        keyword_format = QTextCharFormat()
        keyword_format.setForeground(QColor("blue"))
        keyword_format.setFontWeight(QFont.Bold)

        for word in keywords + new_keywords:
            pattern = QRegExp(f"\\b{word}\\b")
            pattern.setCaseSensitivity(Qt.CaseInsensitive)
            self.rules.append((pattern, keyword_format))

        # String format
        string_format = QTextCharFormat()
        string_format.setForeground(QColor("magenta"))
        self.rules.append((QRegExp("\".*\""), string_format))

        # Comment format
        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("green"))
        self.rules.append((QRegExp("#[^\n]*"), comment_format))

    def add_keywords(self, words, color):
        fmt = QTextCharFormat()
        fmt.setForeground(color)
        for word in words:
            pattern = QRegExp(f"\\b{word}\\b")
            pattern.setCaseSensitivity(Qt.CaseInsensitive)
            self.rules.append((pattern, fmt))
        self.rehighlight()

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            expression = QRegExp(pattern)
            index = expression.indexIn(text)

            while index >= 0:
                length = expression.matchedLength()
                self.setFormat(index, length, fmt)
                index = expression.indexIn(text, index + length)


class DbChangeHandler(FileSystemEventHandler):
    """Watchdog handler that emits a Qt signal when the watched DB file is modified."""

    def __init__(self, db_path, signal):
        super().__init__()
        self._db_path = os.path.abspath(db_path)
        self._signal = signal

    def on_modified(self, event):
        if not event.is_directory and os.path.abspath(event.src_path) == self._db_path:
            self._signal.emit()


class MiniSqlApp(QWidget):
    focus_in = pyqtSignal(object)
    _db_changed = pyqtSignal()  # internal signal, fired from watchdog thread

    def __init__(self):
        super().__init__()
        self.state = 0
        self.counter = 0


        # Global Font 12pt
        #self.setFont(QFont("Segoe UI", 18))

        self._observer = None  # watchdog Observer instance

        self.db = None

        main_splitter = QSplitter(Qt.Vertical)

        # --- TOP: EDITOR & ERRORS ---
        self.top_widget = QWidget()
        top_layout = QVBoxLayout(self.top_widget)

        qlbl = QLabel("Query Editor (Ctrl+Enter)")
        qlbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.query_input = Editor()
        self.query_input.setMinimumHeight(150)
        self.highlighter = SQLHighlighter(self.query_input.document())

        self.info_output = QTextEdit()
        self.info_output.setReadOnly(True)
        self.info_output.setMinimumHeight(120)
        self.info_output.setFont(QFont("Monospace"))
        #self.info_output.setStyleSheet("background: #fdfdfd; color: #333;")

        top_layout.addWidget(qlbl)
        top_layout.addWidget(self.query_input)
        op_info = QLabel("Operation Info / Errors:")
        top_layout.addWidget(op_info)
        top_layout.addWidget(self.info_output)
        main_splitter.addWidget(self.top_widget)

        # --- BOTTOM: TABLES ---
        table_splitter = QSplitter(Qt.Horizontal)

        # Left: Result
        self.results_w = QWidget()
        res_l = QVBoxLayout(self.results_w)
        self.query_view = QTableView()
        self.query_view.verticalHeader().setVisible(False)
        self.query_model = QSqlQueryModel()
        self.query_view.setModel(self.query_model)
        query_res = QLabel("Query Result")
        res_l.addWidget(query_res)
        res_l.addWidget(self.query_view)
        table_splitter.addWidget(self.results_w)

        # Right: Watcher
        self.watcher_w = QWidget()
        wat_l = QVBoxLayout(self.watcher_w)
        self.table_selector = QComboBox()
        self.table_selector.currentTextChanged.connect(self.refresh_full_view)
        self.full_view = QTableView()
        self.full_view.verticalHeader().setVisible(False)

        self.full_model = QSqlQueryModel()
        self.full_view.setModel(self.full_model)
        table_w_lbl = QLabel("Table Watcher")
        wat_l.addWidget(table_w_lbl)
        wat_l.addWidget(self.table_selector)
        wat_l.addWidget(self.full_view)
        table_splitter.addWidget(self.watcher_w)

        main_splitter.addWidget(table_splitter)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 2)

        #self.setCentralWidget(main_splitter)
        self.setLayout(QVBoxLayout())
        self.layout().addWidget(main_splitter)

        # Connect the internal signal (emitted from watchdog thread) to refresh,
        # ensuring the slot always runs on the Qt main thread.
        self._db_changed.connect(self.refresh_full_view)

        q = QShortcut("Ctrl+B", self)
        q.activated.connect(self.loop_views)

        self.fontable = [qlbl, self.query_input, self.info_output,
                         self.table_selector, self.full_view,
                         self.query_view, op_info, query_res, table_w_lbl]

        self.set_font_size(14)

    def loop_views(self):
        self.state = (self.state + 1) % 4
        if self.state == 0:
            self.results_w.setVisible(True)
            self.top_widget.setVisible(True)
            self.watcher_w.setVisible(True)
        elif self.state == 1:
            self.results_w.setVisible(False)
            self.top_widget.setVisible(False)
            self.watcher_w.setVisible(True)
        elif self.state == 2:
            self.results_w.setVisible(True)
            self.watcher_w.setVisible(False)
            self.top_widget.setVisible(True)
        elif self.state == 3:
            self.results_w.setVisible(False)
            self.watcher_w.setVisible(True)
            self.top_widget.setVisible(True)


    # ------------------------------------------------------------------
    # Watchdog helpers
    # ------------------------------------------------------------------

    def _start_watching(self, db_path):
        """Start a watchdog Observer for the given DB file."""
        self._stop_watching()
        abs_path = os.path.abspath(db_path)
        watch_dir = os.path.dirname(abs_path) or "."
        handler = DbChangeHandler(abs_path, self._db_changed)
        self._observer = Observer()
        self._observer.schedule(handler, watch_dir, recursive=False)
        self._observer.start()

    def _stop_watching(self):
        """Stop and join any running watchdog Observer."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None

    def closeEvent(self, event):
        self._stop_watching()
        super().closeEvent(event)

    # ------------------------------------------------------------------

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() == Qt.ControlModifier:
            self.run_query()
        else:
            super().keyPressEvent(event)

    def insert_result(self, text, color=Qt.black):
        self.counter += 1
        cursor = self.info_output.textCursor()
        cursor.movePosition(cursor.Start)
        fmt = cursor.charFormat()
        fmt.setForeground(color)
        cursor.setCharFormat(fmt)
        cursor.insertText(f"[{self.counter}] {text}\n")
        self.info_output.setTextCursor(cursor)

    def run_query(self):
        sql = self.query_input.toPlainText()
        query = QSqlQuery()
        if query.exec_(sql):
            self.query_model.setQuery(query)

            if not query.isSelect():
                # Check rows affected or returned
                affected = query.numRowsAffected()
                msg = f"Success. Rows affected: {affected}"
                if affected > 0:
                    self.insert_result(msg, color=Qt.darkGreen)
                else:
                    # orange
                    self.insert_result(msg, color=QColor(255, 140, 0))
            else:
                def delayed(pd=None):
                    while self.query_model.canFetchMore():
                        self.query_model.fetchMore()

                    # If it's a SELECT, count rows in the model
                    self.insert_result(f"Success. Rows returned: {self.query_model.rowCount()}", color=Qt.darkGreen)

                    self.refresh_table_list()
                    if pd is not None:
                        pd.close()
                if self.query_model.rowCount() < 256:
                    delayed()
                else:
                    pd = QProgressDialog("Fetching more rows...", "Cancel", 0, 0, self)
                    pd.setWindowModality(Qt.WindowModal)
                    pd.show()
                    QTimer.singleShot(100, lambda : delayed(pd))
        else:
            self.insert_result(query.lastError().text(), color=Qt.red)

    def refresh_table_list(self):
        current = self.table_selector.currentText()
        self.table_selector.blockSignals(True)
        self.table_selector.clear()
        self.table_selector.addItems(self.db.tables())
        if current in self.db.tables():
            self.table_selector.setCurrentText(current)
        self.table_selector.blockSignals(False)
        self.query_view.resizeColumnsToContents()

    def refresh_full_view(self):
        table = self.table_selector.currentText()
        if table:
            self.full_model.setQuery(f"SELECT * FROM {table}")
            self.full_view.resizeColumnsToContents()


    def open_database(self, db_path):

        # Clear models FIRST, before closing/removing the connection
        if self.db:
            self._stop_watching()
            self.query_model.clear()
            self.full_model.clear()
            self.db.close()
            QSqlDatabase.removeDatabase(self.db.connectionName())

        # Open new DB
        self.db = QSqlDatabase.addDatabase("QSQLITE")
        self.db.setDatabaseName(db_path)
        if not self.db.open():
            self.insert_result(f"Failed to open {db_path}: {self.db.lastError().text()}", color=Qt.red)
            return False

        self.insert_result(f"Opened database: {db_path}", color=Qt.darkGreen)
        self.setWindowTitle(f"Minimal SQLite Browser - {db_path}")
        new_words = []
        for table in self.db.tables():
            new_words.append(table)
            for i in range(self.db.record(table).count()):
                new_words.append(self.db.record(table).fieldName(i))

        self.highlighter.reset()
        self.highlighter.add_keywords(new_words, Qt.darkGreen)
        self.query_input.set_db_keywords(new_words)
        self.refresh_table_list()
        self._start_watching(db_path)
        QTimer.singleShot(50, self.refresh_full_view)

        return True

    def set_dark_mode(self, enabled):
        if enabled:
            self.setStyleSheet("""
                QWidget { background: #2b2b2b; color: #f0f0f0; }
                QTableView { background: #3c3c3c; }
                QTextEdit { background: #3c3c3c; }
                QComboBox { background: #3c3c3c; }
            """)
        else:
            self.setStyleSheet("")

    def update_config(self):
        pass

    def is_selectable(self):
        return False

    def on_disk(self):
        return False

    def set_font_size(self, font_size):
        font = QFont("Monospace")
        font.setStyleHint(QFont.TypeWriter)
        font.setPixelSize(font_size)
        for f in self.fontable:
            f.setFont(font)
        self.query_view.resizeColumnsToContents()
        self.full_view.resizeColumnsToContents()

    def get_font_size(self):
        return self.fontable[0].font().pixelSize() if self.fontable else 12

class MainWindow(QMainWindow):
    def __init__(self, db):
        super().__init__()
        self.mini_app = MiniSqlApp()
        self.setCentralWidget(self.mini_app)

        # Menu
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        open_action = QAction("Open Database...", self)
        open_action.triggered.connect(self.open_database_dialog)
        file_menu.addAction(open_action)
        self.setCentralWidget(self.mini_app)

        if db is not None and self.mini_app.open_database(db):
            self.setWindowTitle(f"Minimal SQLite Browser - {db}")
        else:
            self.setWindowTitle("Minimal SQLite Browser")

    def enable_font_resize_shortcuts(self):
        zoom_in = QShortcut("Ctrl++", self)
        zoom_out = QShortcut("Ctrl+-", self)
        zoom_in.activated.connect(lambda: self.mini_app.set_font_size(self.mini_app.get_font_size() + 1))
        zoom_out.activated.connect(lambda: self.mini_app.set_font_size(max(6, self.mini_app.get_font_size() - 1)))

    def open_database_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open SQLite Database", "", "SQLite DB Files (*.db *.sqlite *.sqlite3);;All Files (*)")
        if path and self.mini_app.open_database(path):
            self.setWindowTitle(f"Minimal SQLite Browser - {path}")


def main():
    target_db = sys.argv[1] if len(sys.argv) > 1 else None
    app = QApplication(sys.argv)
    window = MainWindow(target_db)
    window.resize(1200, 900)
    window.enable_font_resize_shortcuts()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()