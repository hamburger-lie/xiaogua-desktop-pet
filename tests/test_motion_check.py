"""The motion checker that new artwork must pass (ANIMATION_BRIEF.md)."""

from __future__ import annotations

import json
import shutil

from PIL import Image

from meihua.companion import app as companion
from meihua.companion.motion_check import check

IDLE = companion.ASSETS / "xiaogua" / "待机"


def _copy_idle(tmp_path, name="点头", frames=6, ms=90):
    folder = tmp_path / name
    folder.mkdir()
    source = sorted(IDLE.glob("*.png"))
    for i in range(frames):
        shutil.copy(source[i % len(source)], folder / f"{i + 1:02d}.png")
    (folder / "motion.json").write_text(json.dumps({"frame_ms": ms, "kind": "once"}), encoding="utf-8")
    return folder


def test_frames_drawn_like_the_idle_pose_pass(tmp_path):
    fails, _ = check(_copy_idle(tmp_path))
    assert fails == []


def test_a_background_wrong_size_or_off_the_feet_line_fails(tmp_path):
    folder = _copy_idle(tmp_path)
    Image.new("RGBA", (512, 512), (250, 248, 240, 255)).save(folder / "03.png")      # cream paper, not cut out
    small = Image.open(folder / "01.png").resize((400, 400))
    canvas = Image.new("RGBA", (512, 512))
    canvas.alpha_composite(small, (56, 20))                                           # smaller and floating
    canvas.save(folder / "01.png")
    Image.new("RGBA", (300, 300)).save(folder / "02.png")
    fails, _ = check(folder)
    joined = " ".join(fails)
    assert "背景没抠干净" in joined and "512×512" in joined and "脚底" in joined


def test_frozen_frames_and_naming_are_reported(tmp_path):
    folder = _copy_idle(tmp_path)
    shutil.copy(folder / "02.png", folder / "03.png")
    (folder / "06.png").rename(folder / "7.png")
    fails, warns = check(folder)
    assert any("连续命名" in f for f in fails) and any("卡帧" in w for w in warns)


def test_every_shipped_motion_passes_the_checker():
    """New artwork (Codex sheets, tools/make_procedural_motions.py) must stay within the rules."""
    import pytest
    for name in ("点头", "摇头", "歪头", "说话", "被摸头", "犯困", "欢呼", "登场", "落地"):
        folder = companion.ASSETS / "xiaogua" / name
        if not folder.is_dir():
            pytest.fail(f"{name} 不见了")
        fails, _ = check(folder)
        assert fails == [], (name, fails)
