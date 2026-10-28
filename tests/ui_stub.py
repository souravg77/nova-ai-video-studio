"""Shared minimal PySide6 stub for headless UI logic tests.

PySide6 can't be installed in CI, so tests inject this stub. It provides enough
of QtCore/QtWidgets for the NOVA windows/panels to import and for their pure
logic to run. Both UI test modules import install_qt_stub() from here so there
is exactly one stub implementation (no conflicting partial stubs).
"""
from __future__ import annotations

import sys
import types


def install_qt_stub() -> None:
    existing = sys.modules.get("PySide6")
    if existing is not None and getattr(existing, "_nova_stub", False):
        return

    qtcore = types.ModuleType("PySide6.QtCore")
    qtwidgets = types.ModuleType("PySide6.QtWidgets")
    pyside6 = types.ModuleType("PySide6")
    pyside6._nova_stub = True

    class _BoundSignal:
        def __init__(self): self._cbs = []
        def connect(self, cb): self._cbs.append(cb)
        def emit(self, *a):
            for cb in self._cbs:
                cb(*a)

    class _Signal:
        def __get__(self, obj, owner):
            if obj is None:
                return self
            key = "_sig_" + str(id(self))
            if not hasattr(obj, key):
                setattr(obj, key, _BoundSignal())
            return getattr(obj, key)

    class Qt:
        Horizontal = 1
        Vertical = 2
        UserRole = 256

    class _Callable:
        def __call__(self, *a, **k): return None
        def connect(self, *a, **k): return None

    class _W:
        def __init__(self, *a, **k):
            self._text = a[0] if a and isinstance(a[0], str) else ""
            self._enabled = True
            self._row = -1
            self._value = 0
            self._items = []
            self._plain = ""
        def __getattr__(self, name):
            return _Callable()
        def setEnabled(self, v): self._enabled = v
        def isEnabled(self): return self._enabled
        def setText(self, t): self._text = t
        def text(self): return self._text
        def setValue(self, v): self._value = v
        def value(self): return self._value
        def setRange(self, *a): pass
        def setSingleStep(self, *a): pass
        def setFixedHeight(self, *a): pass
        def setToolTip(self, *a): pass
        def setPlaceholderText(self, *a): pass
        def toPlainText(self): return self._plain
        def addItem(self, it, *a):
            self._items.append(it)
            # Qt auto-selects the first item added to an empty combo.
            if self._row == -1:
                self._row = 0
        def clear(self): self._items = []; self._row = -1
        def count(self): return len(self._items)
        def item(self, i): return self._items[i] if 0 <= i < len(self._items) else None
        def setData(self, *a): pass
        def data(self, *a): return None
        def currentItem(self):
            return self._items[self._row] if 0 <= self._row < len(self._items) else None
        def currentRow(self): return self._row
        def currentIndex(self): return self._row
        def setCurrentRow(self, r): self._row = r
        def insertRow(self, *a): pass
        def setItem(self, *a): pass
        def rowCount(self): return 0
        def setHorizontalHeaderLabels(self, *a): pass
        def addWidget(self, *a): pass
        def addLayout(self, *a): pass
        def setSizes(self, *a): pass
        def setWordWrap(self, *a): pass
        def addItems(self, items): self._items.extend(items)
        def setCentralWidget(self, *a): pass
        def setWindowTitle(self, *a): pass
        def resize(self, *a): pass
        def setReadOnly(self, *a): pass
        def append(self, *a): pass

    widget_names = [
        "QComboBox", "QDoubleSpinBox", "QCheckBox", "QFileDialog", "QGroupBox",
        "QHBoxLayout", "QLabel", "QLineEdit", "QListWidget", "QMainWindow",
        "QProgressBar", "QPushButton", "QSpinBox", "QSplitter", "QTableWidget",
        "QTableWidgetItem", "QTextEdit", "QPlainTextEdit", "QVBoxLayout",
        "QWidget", "QApplication",
    ]
    for n in widget_names:
        setattr(qtwidgets, n, type(n, (_W,), {}))

    class QMessageBox(_W):
        @staticmethod
        def information(*a, **k): return None
        @staticmethod
        def warning(*a, **k): return None
        @staticmethod
        def critical(*a, **k): return None
        @staticmethod
        def question(*a, **k): return None
    qtwidgets.QMessageBox = QMessageBox

    class QInputDialog(_W):
        @staticmethod
        def getText(*a, **k): return ("", False)
        @staticmethod
        def getInt(*a, **k): return (1, False)
        @staticmethod
        def getItem(*a, **k): return ("", False)
    qtwidgets.QInputDialog = QInputDialog

    class QObject:
        def __init__(self, *a, **k): pass
    qtcore.QObject = QObject
    qtcore.Qt = Qt
    qtcore.Signal = lambda *a, **k: _Signal()

    pyside6.QtCore = qtcore
    pyside6.QtWidgets = qtwidgets
    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtWidgets"] = qtwidgets
