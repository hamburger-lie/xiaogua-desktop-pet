#!/usr/bin/env python3
"""Build 每日一瓜 · 小瓜桌宠 for Windows:  python packaging/build.py [--installer]

1. Makes the .ico and the exe version resource from the package's own data.
2. Runs PyInstaller with xiaogua.spec  ->  packaging/dist/MeiriYigua/MeiriYigua.exe
3. Smoke-tests the frozen build: it must start, find its data, and convert a
   lunar date without Node.
4. With --installer, runs Inno Setup (iscc) on xiaogua.iss  ->  packaging/dist/
   XiaoguaDesktopPet-Setup-<version>.exe. Inno Setup 6 must be installed separately.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

import meihua  # noqa: E402


def make_icon() -> Path:
    from PIL import Image

    from meihua.companion.app import cut_out

    out = HERE / "build" / "xiaogua.ico"
    out.parent.mkdir(parents=True, exist_ok=True)
    image = cut_out(Image.open(meihua.ROOT / "assets" / "xiaogua-icon.png"))
    box = image.getchannel("A").getbbox()
    image = image.crop(box)
    side = max(image.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    square.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return out


def shrink_frames() -> Path:
    """Motion frames at ART_PX (the size the app keeps them at), not the 512px masters."""
    from PIL import Image

    from meihua.companion.app import ART_PX

    source = meihua.ROOT / "assets" / "xiaogua"
    out = HERE / "build" / "frames"
    if out.exists():
        shutil.rmtree(out)
    for folder in source.iterdir():
        if not folder.is_dir() or folder.name == "sheets":
            continue
        target = out / folder.name
        target.mkdir(parents=True)
        for file in folder.iterdir():
            if file.suffix == ".png":
                Image.open(file).resize((ART_PX, ART_PX), Image.LANCZOS).save(target / file.name, optimize=True)
            else:
                shutil.copy2(file, target / file.name)          # motion.json
    return out


def make_version_info() -> Path:
    numbers = [int(n) for n in meihua.__version__.split(".")] + [0]
    version = tuple((numbers + [0, 0, 0])[:4])
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={version}, prodvers={version}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('080404b0', [
      StringStruct('CompanyName', '每日一瓜'),
      StringStruct('FileDescription', '每日一瓜 · 小瓜桌宠'),
      StringStruct('FileVersion', '{meihua.__version__}'),
      StringStruct('ProductName', '每日一瓜'),
      StringStruct('ProductVersion', '{meihua.__version__}'),
      StringStruct('OriginalFilename', 'MeiriYigua.exe')])]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])]
)
"""
    out = HERE / "build" / "version_info.txt"
    out.write_text(text, encoding="utf-8")
    return out


def pyinstaller() -> Path:
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(HERE / "dist"), "--workpath", str(HERE / "build" / "work"),
                    str(HERE / "xiaogua.spec")], check=True)
    return HERE / "dist" / "MeiriYigua"


def smoke_test(app_dir: Path) -> None:
    internal = app_dir / "_internal" / "meihua"
    required = ["engines/lunar_table.json", "references/hexagrams.md", "evidence/meihua.md",
                "assets/xiaogua-icon.png", "assets/xiaogua/招手/01.png", "assets/ui/check.svg"]
    missing = [r for r in required if not (internal / r).exists()]
    if missing:
        raise SystemExit(f"打包缺文件：{missing}")
    if (internal / "assets" / "xiaogua" / "sheets").exists():
        raise SystemExit("源精灵图不该打进安装包")
    print("smoke test: data files present")
    # Run the frozen exe itself: catches missing hidden imports, data and time zones.
    report_path = HERE / "build" / "selftest.json"
    report_path.unlink(missing_ok=True)
    subprocess.run([str(app_dir / "MeiriYigua.exe"), "--selftest", str(report_path)], timeout=120)
    if not report_path.exists():
        raise SystemExit("打包版自检没有产出结果")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "ok":
        raise SystemExit(f"打包版自检失败：{report.get('error')}\n{report.get('trace', '')}")
    print("smoke test: frozen exe", json.dumps(report, ensure_ascii=False))


def installer() -> Path:
    iscc = shutil.which("iscc") or next(
        (str(p) for p in (Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
                          Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
                          Path.home() / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe")
         if p.exists()), None)
    if not iscc:
        raise SystemExit("没找到 Inno Setup 的 iscc.exe；装好 Inno Setup 6 后再加 --installer")
    subprocess.run([iscc, f"/DAppVersion={meihua.__version__}", str(HERE / "xiaogua.iss")], check=True)
    return HERE / "dist" / f"XiaoguaDesktopPet-Setup-{meihua.__version__}.exe"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--installer", action="store_true", help="also build the Inno Setup installer")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("icon:", make_icon())
    print("version:", make_version_info())
    print("frames:", shrink_frames())
    app_dir = pyinstaller()
    smoke_test(app_dir)
    print("app:", app_dir / "MeiriYigua.exe")
    if args.installer:
        print("installer:", installer())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
