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
| [lunar_python](https://github.com/6tail/lunar-python) | 农历、干支、黄历宜忌 | MIT |
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

## 传统文献

起卦方法和卦义依据《梅花易数》，黄历宜忌依据《协纪辨方书》，物象依据《周易·说卦传》。这些都是公有领域的古籍；项目里的白话解释是自己写的。
