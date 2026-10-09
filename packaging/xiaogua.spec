# PyInstaller spec for 每日一瓜 · 小瓜桌宠.  Build with:  python packaging/build.py
#
# One folder (not one file): a one-file exe unpacks itself to %TEMP% on every
# start, which makes login autostart noticeably slower.
#
# The engines/checks modules are imported by bare name after meihua puts
# their folders on sys.path, so PyInstaller cannot see them by itself: they are
# listed in `hiddenimports` with their folders on `pathex`. The package's data
# (evidence, references, artwork, lunar table…) is copied next to them so
# meihua.ROOT resolves to the same layout as in the source tree.

import pathlib

from PyInstaller.utils.hooks import collect_data_files

HERE = pathlib.Path(SPECPATH)
SRC = HERE.parent / "src"
PKG = SRC / "meihua"

engine_modules = sorted(
    p.stem for folder in ("engines", "checks")
    for p in (PKG / folder).glob("*.py"))

datas = [
    (str(path), str(pathlib.Path("meihua") / path.parent.relative_to(PKG)))
    for path in PKG.rglob("*")
    if path.is_file()
    and "__pycache__" not in path.parts
    and "tests" not in path.relative_to(PKG).parts
    and path.suffix not in (".pyc",)
    and not (path.parent.name == "sheets")          # source sprite sheets: frames are shipped instead
    and not (path.parent.parent == PKG / "assets" / "xiaogua")   # 512px frames: see FRAMES below
]
# Motion frames at the size the app draws them (build.py: shrink_frames).
FRAMES = HERE / "build" / "frames"
datas += [(str(path), str(pathlib.Path("meihua/assets/xiaogua") / path.parent.name))
          for path in FRAMES.rglob("*") if path.is_file()]
datas += collect_data_files("tzdata")              # Windows has no system time-zone database

a = Analysis(
    [str(HERE / "launcher.py")],
    pathex=[str(SRC)] + [str(PKG / f) for f in ("engines", "checks")],
    datas=datas,
    hiddenimports=engine_modules + ["meihua.companion.app", "meihua.companion.settings_window",
                                    "tzdata", "pynput.keyboard._win32", "pynput.mouse._win32"],
    excludes=["tkinter", "matplotlib", "numpy", "pytest", "mcp", "cryptography", "setuptools",
              "pkg_resources", "aiohttp", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf",
              "PySide6.QtOpenGL"],
    noarchive=False,
)

# Qt pieces a widgets-only app never loads. The self-test in build.py and a real
# launch catch it if one of these turns out to be needed after all.
DROP = ("opengl32sw.dll", "Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6VirtualKeyboard", "qpdf.dll",
        "libcrypto-3-x64.dll", "libssl-3-x64.dll")
KEEP_TRANSLATIONS = ("qtbase_zh_CN.qm",)


def wanted(entry) -> bool:
    name = entry[0].replace("\\", "/")
    base = name.rsplit("/", 1)[-1]
    if any(base.startswith(d) or base == d for d in DROP):
        return False
    if "/translations/" in name and base not in KEEP_TRANSLATIONS:
        return False
    return True


a.binaries = [b for b in a.binaries if wanted(b)]
a.datas = [d for d in a.datas if wanted(d)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="MeiriYigua",
    icon=str(HERE / "build" / "xiaogua.ico"),
    console=False,
    version=str(HERE / "build" / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="MeiriYigua")
