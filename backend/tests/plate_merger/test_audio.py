"""提示音渲染测试。"""

from __future__ import annotations

from app.plate_merger.audio import PLATE_SOUND_FLAG, render_audio
from app.plate_merger.models import AudioMode


def test_off_mode_returns_empty() -> None:
    assert render_audio(AudioMode.OFF) == ""


def test_short_mode_wraps_notes_with_start_and_end() -> None:
    text = render_audio(AudioMode.SHORT)

    assert text.count(PLATE_SOUND_FLAG) == 2
    assert "M1006 S1" in text
    assert "M1006 W" in text
    assert text.count("M1006 A") == 3


def test_jingle_mode_has_more_notes() -> None:
    text = render_audio(AudioMode.JINGLE)

    assert text.count("M1006 A") == 4


def test_audio_preamble_enables_steppers() -> None:
    text = render_audio(AudioMode.SHORT)

    assert "M17" in text
    assert "M400 S1" in text


def test_custom_newline() -> None:
    text = render_audio(AudioMode.SHORT, newline="\r\n")

    assert "\r\n" in text
    assert "\n" in text
