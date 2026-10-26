"""小瓜's look, shared by the settings window and the menus: colours, line icons, the menu style.

The layout follows dsh-pet-indesktop's settings system (page → section → card → row; one
icon family, monochrome outlines), in 小瓜's own colours: cream paper and leaf green.
"""

from __future__ import annotations

import meihua

CREAM, PAPER, INK, LEAF, LEAF_DARK, LINE, MUTED = (
    "#FAF8F0", "#FFFFFF", "#2F4737", "#8FAE72", "#6E8F55", "#B7C69B", "#8C9687")
GOOD, BAD = "#5E8C4A", "#B5533C"
SIDEBAR, CARD_LINE, DIVIDER, HOVER, PICKED = "#F1F4E6", "#E1E6D3", "#ECEFE3", "#EEF2E2", "#E3EBD2"
UI = (meihua.ROOT / "assets" / "ui").as_posix()      # images the stylesheets point at

# Line icons on a 24-unit grid, drawn here so they share one stroke and can take any colour.
# Our own simple shapes (no icon pack, so nothing to license).
_ICONS = {
    # settings pages
    "连接": '<path d="M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0z M12 17v4"/>',
    "小瓜": '<path d="M12 21v-8 M12 13c0-4.4 3.2-7.5 8-7.5 0 4.4-3.2 7.5-8 7.5z M12 13c0-3.6-2.6-6-6.8-6 0 3.6 2.6 6 6.8 6z"/>',
    "外观": '<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.6-.8 1.6-1.6 0-.8-.6-1.2-.6-2 0-.9.7-1.6 1.6-1.6H17a4 4 0 0 0 4-4'
            'c0-4.9-4-8.8-9-8.8z"/><circle cx="7.6" cy="11" r="1"/><circle cx="10" cy="7.2" r="1"/>'
            '<circle cx="14.6" cy="7.2" r="1"/><circle cx="17.2" cy="11" r="1"/>',
    "互动": '<path d="M9 11.5V5a1.5 1.5 0 0 1 3 0v5 M12 9.5a1.5 1.5 0 0 1 3 0V11 M15 10.5a1.5 1.5 0 0 1 3 0V15'
            'a6 6 0 0 1-6 6h-.8a6 6 0 0 1-4.8-2.4L4.3 15.8a1.5 1.5 0 0 1 2.3-1.9L9 16.2"/>',
    "记忆": '<path d="M12 20s-7.5-4.6-7.5-10.2A4.2 4.2 0 0 1 12 7.3a4.2 4.2 0 0 1 7.5 2.5C19.5 15.4 12 20 12 20z"/>',
    "回收站": '<path d="M4 7h16 M9.5 7V4.5h5V7 M6 7l1 13h10l1-13 M10 11v5.5 M14 11v5.5"/>',
    "快捷键与启动": '<rect x="3" y="6.5" width="18" height="11" rx="2"/><path d="M7 10h.01 M10.5 10h.01 M14 10h.01'
                  ' M17 10h.01 M8 14h8"/>',
    "关于": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5 M12 7.8h.01"/>',
    # menu actions
    "问小瓜": '<path d="M4.5 5h15a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H10l-4.5 3.8V16h-1a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z"/>',
    "打开对话": '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M3.5 9h17 M7.5 13h9 M7.5 16h5"/>',
    "今天": '<rect x="4" y="5.5" width="16" height="14.5" rx="2"/><path d="M8 3.5v4 M16 3.5v4 M4 10h16 M9 14.5h.01'
            ' M12 14.5h.01 M15 14.5h.01"/>',
    "大小": '<path d="M14.5 4H20v5.5 M9.5 20H4v-5.5 M20 4l-6.5 6.5 M4 20l6.5-6.5"/>',
    "小球": '<circle cx="12" cy="12" r="6.5"/><path d="M8.9 10.3a3.6 3.6 0 0 1 2.7-2"/>',
    "锁定": '<rect x="5.5" y="10.5" width="13" height="9.5" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5'
            ' M12 14.3v2"/>',
    "置顶": '<path d="M12 16.5V21 M8.5 3.5h7l-1 5.5 3 3V14h-11v-2l3-3z"/>',
    "穿透": '<path d="M5.5 3.5l13 7.8-5.6 1.6-2.4 5.6z M13 13l5 5"/>',
    "隐藏": '<path d="M3.5 3.5l17 17 M10.4 6.2A9 9 0 0 1 12 6c5 0 8.5 6 8.5 6a15 15 0 0 1-2.6 3.3 M6.7 6.8'
            'C4.6 8.4 3.5 12 3.5 12s3.5 6 8.5 6a8.6 8.6 0 0 0 3.9-.9"/>',
    "新对话": '<path d="M12 5v14 M5 12h14"/>',
    "删除": '<path d="M4 7h16 M9.5 7V4.5h5V7 M6 7l1 13h10l1-13"/>',
    "设置": '<circle cx="12" cy="12" r="3.2"/><path d="M12 3.5v2.4 M12 18.1v2.4 M3.5 12h2.4 M18.1 12h2.4'
            ' M6 6l1.7 1.7 M16.3 16.3 18 18 M6 18l1.7-1.7 M16.3 7.7 18 6"/>',
    "退出": '<path d="M12 3.5v8 M6.4 6.6a8 8 0 1 0 11.2 0"/>',
}


def icon(name: str, color: str = INK, selected: str | None = None, size: int = 18, switch: bool = False):
    """A QIcon for one of the line icons above; `selected` colours it for the selected state (the sidebar).
    A `switch` icon shows its state itself: switched on, white lines on a leaf-green tile. (A menu draws
    a checkable entry's icon where the check would go, so the check alone could not be seen.)"""
    from PySide6.QtGui import QIcon

    result = QIcon()
    for mode, ink in ((QIcon.Normal, color), (QIcon.Selected, selected or color), (QIcon.Active, color)):
        result.addPixmap(_pixmap(name, ink, size), mode, QIcon.Off)
        result.addPixmap(_pixmap(name, "#FFFFFF", size, tile=LEAF) if switch else _pixmap(name, ink, size),
                         mode, QIcon.On)
    return result


def _pixmap(name: str, color: str, size: int, tile: str = ""):
    from PySide6.QtGui import QGuiApplication, QPixmap

    scale = 2 if QGuiApplication.instance() is None else max(1.0, QGuiApplication.instance().devicePixelRatio())
    pixels = round(size * max(scale, 2))                     # drawn large, shown small: crisp on any screen
    lines = _ICONS[name]
    if tile:
        lines = (f'<rect x="0.5" y="0.5" width="23" height="23" rx="6" fill="{tile}" stroke="none"/>'
                 f'<g transform="translate(3.6 3.6) scale(0.7)">{lines}</g>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{pixels}" height="{pixels}" viewBox="0 0 24 24" '
           f'fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
           f'{lines}</svg>')
    pixmap = QPixmap()
    pixmap.loadFromData(svg.encode("utf-8"), "SVG")
    pixmap.setDevicePixelRatio(pixels / size)
    return pixmap


MENU_STYLE = f"""
QMenu {{ background: #FFFDF7; border: 1px solid {CARD_LINE}; border-radius: 12px; padding: 6px;
         font-family: 'Microsoft YaHei'; font-size: 13px; color: {INK}; }}
QMenu::item {{ padding: 7px 30px 7px 10px; border-radius: 8px; margin: 1px 0; background: transparent; }}
QMenu::item:selected {{ background: {PICKED}; color: {INK}; }}
QMenu::item:disabled {{ color: {MUTED}; }}
QMenu::icon {{ padding-left: 10px; }}
QMenu::separator {{ height: 1px; background: {DIVIDER}; margin: 5px 10px; }}
QMenu::indicator {{ width: 16px; height: 16px; padding-left: 8px; }}
QMenu::indicator:checked {{ image: url({UI}/menu-check.svg); }}
QMenu::right-arrow {{ image: url({UI}/chevron-right.svg); width: 14px; height: 14px; padding-right: 8px; }}
"""


def menu(parent=None, title: str = ""):
    """A rounded cream menu with icons, for 小瓜's right click and the tray."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMenu

    styled = QMenu(title, parent)
    styled.setWindowFlags(styled.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    styled.setAttribute(Qt.WA_TranslucentBackground)       # the rounded corners show the desktop, not black
    styled.setStyleSheet(MENU_STYLE)
    return styled


def add_action(target, label: str, handler=None, icon_name: str | None = None, checked: bool | None = None,
               shortcut: str = ""):
    """One menu entry: an icon on the left (a switch's icon turns into a green tile when on; without an
    icon it gets a check), a key hint on the right."""
    from PySide6.QtGui import QAction

    action = QAction(label + (f"\t{shortcut}" if shortcut else ""), target)
    if icon_name:
        action.setIcon(icon(icon_name, LEAF_DARK, switch=checked is not None))
    if checked is not None:
        action.setCheckable(True)
        action.setChecked(checked)
    if handler is not None:
        action.triggered.connect(handler)
    target.addAction(action)
    return action
