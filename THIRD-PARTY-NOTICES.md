# 第三方组件说明 / Third-party notices

每日一瓜自己的代码和小瓜的形象用 CC BY-NC 4.0（见 [LICENSE](LICENSE)）。下面这些组件不是我写的，各自保留自己的协议；安装包里带着它们的原样副本。

The components below are not covered by this project's license; each keeps its own.

## 运行时组件（安装包里自带）

| 组件 | 用途 | 协议 |
|---|---|---|
| [Python](https://www.python.org/) | 运行环境 | PSF License |
| [Qt for Python (PySide6 / shiboken6)](https://doc.qt.io/qtforpython/) | 窗口和界面 | LGPL-3.0（另有 GPL 选项） |
| [pynput](https://github.com/moses-palmer/pynput) | 按键说话时替你按 Win + H | LGPL-3.0 |
| [Pillow](https://python-pillow.org/) | 处理小瓜的图片 | MIT-CMU (HPND) |
| [lunar_python](https://github.com/6tail/lunar-python) | 农历、干支、黄历宜忌；节气交节时刻表 `engines/solar_terms.json` 也是用它生成的 | MIT |
| [anthropic](https://github.com/anthropics/anthropic-sdk-python) | 连接 Claude | MIT |
| httpx / httpcore / h11 / idna | 网络请求 | BSD-3-Clause / MIT |
| anyio / sniffio / jiter / pydantic / pydantic-core / distro / docstring-parser | anthropic 的依赖 | MIT / Apache-2.0 |
| aiohttp / click / charset-normalizer | 依赖库 | Apache-2.0 / BSD-3-Clause / MIT |
| [certifi](https://github.com/certifi/python-certifi) | HTTPS 根证书 | MPL-2.0 |
| [tzdata](https://github.com/python/tzdata) | 时区数据 | Apache-2.0 |
| typing-extensions | 类型标注 | PSF-2.0 |
| pywin32 | Windows 接口 | PSF-2.0 |

**关于 LGPL 组件（Qt / PySide6、pynput）：** 它们以独立的动态库 / 模块形式放在安装目录的 `_internal` 文件夹里，没有被改动，也没有静态链接进程序。你可以用同版本或兼容版本替换它们。源码可以从 [Qt 官网](https://www.qt.io/download-open-source)、[PyPI 上的 PySide6](https://pypi.org/project/PySide6/) 和 [pynput 仓库](https://github.com/moses-palmer/pynput) 获取。LGPL-3.0 全文见 <https://www.gnu.org/licenses/lgpl-3.0.html>。

## 打包工具

| 组件 | 用途 | 协议 |
|---|---|---|
| [PyInstaller](https://pyinstaller.org/) | 把程序打成 exe | GPL-2.0 加特别例外：允许用它打包分发任意协议的程序 |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | 制作安装包 | Inno Setup License（免费，可用于任何程序） |
| `packaging/ChineseSimplified.isl` | 安装界面的简体中文翻译，来自 Inno Setup 官方仓库，作者 Zhenghan Yang | 同 Inno Setup License |

## 对照数据

为了核对紫微、奇门排得对不对，用下面四个开源库各排了一批对照盘，结果存在 `src/meihua/evidence/ziwei-reference-cases.json` 和 `qimen-reference-cases.json`，只在测试里用。仓库和安装包里都没有它们的代码。

| 组件 | 用途 | 协议 |
|---|---|---|
| [iztro](https://github.com/SylarLong/iztro) 2.6.3 | 紫微对照盘 | MIT |
| [fortel-ziweidoushu](https://github.com/airicyu/fortel-ziweidoushu) 1.3.4 | 紫微对照盘 | MIT |
| [taobi](https://github.com/Taogram/taobi) 0.4.5 | 奇门对照盘（指定拆补法） | MPL-2.0 |
| [qimen-skill](https://github.com/DuShifang/qimen-skill) 引擎 0.4.1 | 奇门对照盘 | MIT |

## 传统文献

起卦方法和卦义依据《梅花易数》，黄历宜忌依据《协纪辨方书》，物象依据《周易·说卦传》。紫微排盘依据《紫微斗数全书》，星性取卷一「诸星问答论」；奇门依据《奇门遁甲统宗》和《烟波钓叟歌》（都用维基文库录文，行号见 `src/meihua/references/`），挑时辰的门得地另参《御定奇门宝鉴》（殆知阁录文）和《奇门遁甲元灵经》（维基文库）。八字结构依据《三命通会》《滴天髓》等，小六壬依据《萬寶玉匣記》（1936 年上海鴻文書局本）。这些都是公有领域的古籍；项目里的白话解释是自己写的。
