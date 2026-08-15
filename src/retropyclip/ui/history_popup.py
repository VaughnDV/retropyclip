from __future__ import annotations

import platform
from collections.abc import Callable

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QKeyEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from retropyclip.core.models import StoredRecord
from retropyclip.core.text import one_line_preview

INK = "#11141A"
PANEL = "#181D26"
PANEL_ALT = "#202735"
OFF_WHITE = "#F8F1DF"
CYAN = "#16D9E3"
GOLD = "#F2B134"
GREEN = "#4ED17A"
RED = "#E84A5F"


PIXEL_GLYPHS = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
}


class PixelHeader(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.clip_count = 0
        self.setFixedHeight(88)

    def set_clip_count(self, count: int) -> None:
        self.clip_count = count
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(self.rect(), QColor(INK))

        grid_pen = QPen(QColor("#1D2731"))
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        for x in range(0, self.width(), 16):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 16):
            painter.drawLine(0, y, self.width(), y)

        self._draw_cartridge(painter, QPoint(18, 17))
        self._draw_pixel_text(painter, "RETROPYCLIP", QPoint(72, 18), 3, QColor(CYAN))
        painter.setPen(QColor(GOLD))
        painter.setFont(QFont("Menlo", 10, QFont.Bold))
        painter.drawText(74, 70, f"HISTORY CONSOLE  //  {self.clip_count:03d} CLIPS")

        painter.fillRect(QRect(self.width() - 22, 13, 8, 8), QColor(GREEN))
        painter.fillRect(QRect(self.width() - 22, 29, 8, 8), QColor(GOLD))
        painter.fillRect(QRect(self.width() - 22, 45, 8, 8), QColor(RED))

    @staticmethod
    def _draw_cartridge(painter: QPainter, origin: QPoint) -> None:
        painter.fillRect(origin.x(), origin.y() + 6, 38, 48, QColor(OFF_WHITE))
        painter.fillRect(origin.x() + 4, origin.y() + 10, 30, 31, QColor(PANEL_ALT))
        painter.fillRect(origin.x() + 9, origin.y(), 20, 9, QColor(OFF_WHITE))
        painter.fillRect(origin.x() + 9, origin.y() + 45, 20, 5, QColor(GOLD))
        painter.fillRect(origin.x() + 10, origin.y() + 16, 18, 4, QColor(CYAN))
        painter.fillRect(origin.x() + 10, origin.y() + 24, 14, 3, QColor(OFF_WHITE))
        painter.fillRect(origin.x() + 10, origin.y() + 31, 10, 3, QColor(OFF_WHITE))

    @staticmethod
    def _draw_pixel_text(
        painter: QPainter, text: str, origin: QPoint, scale: int, color: QColor
    ) -> None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        cursor_x = origin.x()
        for character in text:
            glyph = PIXEL_GLYPHS.get(character)
            if glyph is None:
                cursor_x += scale * 4
                continue
            for row, line in enumerate(glyph):
                for column, pixel in enumerate(line):
                    if pixel == "1":
                        painter.drawRect(
                            cursor_x + column * scale,
                            origin.y() + row * scale,
                            scale,
                            scale,
                        )
            cursor_x += scale * 6


class ClipRow(QWidget):
    def __init__(self, index: int, record: StoredRecord) -> None:
        super().__init__()
        # The row widget is only visual; the list must receive the click so a
        # single mouse press selects and activates the underlying item.
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(12)

        number = QLabel(f"{index:02d}")
        number.setObjectName("clipNumber")
        number.setFixedWidth(32)
        number.setAlignment(Qt.AlignCenter)
        layout.addWidget(number)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        preview = QLabel(one_line_preview(record.record.text or "", 76))
        preview.setObjectName("clipPreview")
        metadata = QLabel(
            f"{record.record.captured_at.astimezone().strftime('%d %b  %H:%M:%S')}"
            f"   //   {record.record.device_name.upper()}"
            f"   //   {record.sync_state.value.upper()}"
        )
        metadata.setObjectName("clipMetadata")
        text_layout.addWidget(preview)
        text_layout.addWidget(metadata)
        layout.addLayout(text_layout, 1)


class HistoryPopup(QDialog):
    def __init__(self, on_selected: Callable[[str], None]) -> None:
        super().__init__()
        self.on_selected = on_selected
        self.records: list[StoredRecord] = []
        self.setWindowTitle("RetroPyClip History")
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(680, 520)

        shell = QWidget(self)
        shell.setObjectName("popupShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(2, 2, 2, 2)
        shell_layout.setSpacing(0)

        self.header = PixelHeader()
        shell_layout.addWidget(self.header)

        search_area = QWidget()
        search_area.setObjectName("searchArea")
        search_layout = QHBoxLayout(search_area)
        search_layout.setContentsMargins(14, 12, 14, 10)
        search_prompt = QLabel(">")
        search_prompt.setObjectName("searchPrompt")
        self.search = QLineEdit()
        self.search.setObjectName("historySearch")
        self.search.setAccessibleName("Filter clipboard history")
        self.search.setPlaceholderText("TYPE TO FILTER HISTORY...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.search.installEventFilter(self)
        search_layout.addWidget(search_prompt)
        search_layout.addWidget(self.search, 1)
        shell_layout.addWidget(search_area)

        self.list = QListWidget()
        self.list.setObjectName("historyList")
        self.list.setAccessibleName("Clipboard history")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.itemClicked.connect(self._activate_item)
        self.list.itemActivated.connect(self._activate_item)
        shell_layout.addWidget(self.list, 1)

        self.empty = QLabel("NO CLIPS IN LOCAL MEMORY")
        self.empty.setObjectName("emptyState")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.hide()
        shell_layout.addWidget(self.empty, 1)

        action = "PASTE" if platform.system() == "Darwin" else "COPY"
        footer = QLabel(f"↑↓  NAVIGATE     ENTER  {action}     ESC  CLOSE     ⌘⇧V  TOGGLE")
        footer.setObjectName("popupFooter")
        footer.setAlignment(Qt.AlignCenter)
        footer.setFixedHeight(38)
        shell_layout.addWidget(footer)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(shell)
        self._apply_style()

    def set_records(self, records: list[StoredRecord]) -> None:
        self.records = records
        self.header.set_clip_count(len(records))
        self.list.clear()
        for index, record in enumerate(records, start=1):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, record.record.text or "")
            item.setData(Qt.UserRole + 1, (record.record.text or "").lower())
            item.setData(Qt.UserRole + 2, record.record.device_name.lower())
            item.setSizeHint(QSize(0, 62))
            self.list.addItem(item)
            self.list.setItemWidget(item, ClipRow(index, record))
        self._show_list_or_empty()
        if self.list.count():
            self.list.setCurrentRow(0)

    def show_browser(self, records: list[StoredRecord]) -> None:
        self.set_records(records)
        self.search.clear()
        self._position_on_active_screen()
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus(Qt.ShortcutFocusReason)

    def toggle(self, records: list[StoredRecord]) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show_browser(records)

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if watched is self.search and event.type() == QEvent.KeyPress:
            key_event = event
            if isinstance(key_event, QKeyEvent):
                if key_event.key() in {Qt.Key_Down, Qt.Key_Up}:
                    self._move_selection(1 if key_event.key() == Qt.Key_Down else -1)
                    return True
                if key_event.key() in {Qt.Key_Return, Qt.Key_Enter}:
                    current = self.list.currentItem()
                    if current is not None:
                        self._activate_item(current)
                    return True
                if key_event.key() == Qt.Key_Escape:
                    self.hide()
                    return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def event(self, event: QEvent) -> bool:
        result = super().event(event)
        if event.type() == QEvent.WindowDeactivate and self.isVisible():
            self.hide()
        return result

    def _activate_item(self, item: QListWidgetItem) -> None:
        text = item.data(Qt.UserRole)
        if isinstance(text, str):
            self.hide()
            self.on_selected(text)

    def _filter(self, query: str) -> None:
        words = query.lower().split()
        first_visible = -1
        for row in range(self.list.count()):
            item = self.list.item(row)
            haystack = f"{item.data(Qt.UserRole + 1)} {item.data(Qt.UserRole + 2)}"
            visible = all(word in haystack for word in words)
            item.setHidden(not visible)
            if visible and first_visible < 0:
                first_visible = row
        self._show_list_or_empty()
        if first_visible >= 0:
            self.list.setCurrentRow(first_visible)

    def _move_selection(self, delta: int) -> None:
        visible_rows = [
            row for row in range(self.list.count()) if not self.list.item(row).isHidden()
        ]
        if not visible_rows:
            return
        current = self.list.currentRow()
        try:
            position = visible_rows.index(current)
        except ValueError:
            position = 0
        target = visible_rows[max(0, min(position + delta, len(visible_rows) - 1))]
        self.list.setCurrentRow(target)
        self.list.scrollToItem(self.list.item(target))

    def _show_list_or_empty(self) -> None:
        any_visible = any(
            not self.list.item(row).isHidden() for row in range(self.list.count())
        )
        self.list.setVisible(any_visible)
        self.empty.setVisible(not any_visible)
        self.empty.setText(
            "NO MATCHING CLIPS" if self.list.count() else "NO CLIPS IN LOCAL MEMORY"
        )

    def _position_on_active_screen(self) -> None:
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        x = available.x() + (available.width() - self.width()) // 2
        y = available.y() + max(36, (available.height() - self.height()) // 4)
        self.move(x, y)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            QWidget#popupShell {{
                background: {PANEL};
                border: 2px solid {CYAN};
            }}
            QWidget#searchArea {{
                background: {PANEL_ALT};
                border-top: 2px solid {GOLD};
                border-bottom: 1px solid #344052;
            }}
            QLabel#searchPrompt {{
                color: {CYAN};
                font-family: Menlo;
                font-size: 18px;
                font-weight: bold;
            }}
            QLineEdit#historySearch {{
                color: {OFF_WHITE};
                background: {INK};
                border: 1px solid #3A465A;
                padding: 8px 10px;
                font-family: Menlo;
                font-size: 12px;
                selection-background-color: {CYAN};
                selection-color: {INK};
            }}
            QLineEdit#historySearch:focus {{ border: 1px solid {CYAN}; }}
            QListWidget#historyList {{
                background: {PANEL};
                color: {OFF_WHITE};
                border: none;
                outline: none;
                padding: 5px;
            }}
            QListWidget#historyList::item {{
                background: {PANEL};
                border-bottom: 1px solid #2D3748;
                margin: 1px 3px;
            }}
            QListWidget#historyList::item:selected {{
                background: #164B56;
                border: 1px solid {CYAN};
            }}
            QLabel#clipNumber {{
                color: {INK};
                background: {GOLD};
                font-family: Menlo;
                font-size: 10px;
                font-weight: bold;
                padding: 4px;
            }}
            QLabel#clipPreview {{
                color: {OFF_WHITE};
                font-size: 14px;
            }}
            QLabel#clipMetadata {{
                color: {CYAN};
                font-family: Menlo;
                font-size: 9px;
            }}
            QLabel#emptyState {{
                color: {GOLD};
                background: {PANEL};
                font-family: Menlo;
                font-size: 12px;
                font-weight: bold;
            }}
            QLabel#popupFooter {{
                color: {OFF_WHITE};
                background: {INK};
                border-top: 2px solid {GOLD};
                font-family: Menlo;
                font-size: 10px;
                font-weight: bold;
            }}
            QScrollBar:vertical {{
                background: {INK};
                width: 10px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {CYAN};
                min-height: 24px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            """
        )
