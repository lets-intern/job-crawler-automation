"""`tidy_text` 필터. 연속된 빈 줄을 화면에 그릴 때만 접는다.

분류가 낸 값(주요 업무 등)은 원문의 빈 줄을 그대로 옮겨 적어 세네 줄씩 비기도 한다
(`app/classify/classifier.py`). 저장값은 그대로 두고 완성 공고 미리보기가 보여줄 때만
접는다(`app/templates/fragments/complete_preview.html`).
"""

from __future__ import annotations

from app.api.ui import collapse_blank_lines


def test_연속된_빈_줄이_하나로_접힌다() -> None:
    text = "ㅇ 재무\n\n\n\n- 결산\n\n\n ㅇ CR\n\n- 홍보"
    assert collapse_blank_lines(text) == "ㅇ 재무\n\n- 결산\n\n ㅇ CR\n\n- 홍보"


def test_빈_값은_빈_문자열이다() -> None:
    assert collapse_blank_lines(None) == ""
    assert collapse_blank_lines("") == ""


def test_빈_줄이_없으면_그대로다() -> None:
    assert collapse_blank_lines("한 줄") == "한 줄"


def test_앞뒤_빈_줄은_없어진다() -> None:
    assert collapse_blank_lines("\n\n본문\n\n") == "본문"


def test_필터로_등록되어_있다() -> None:
    from app.api.ui import templates

    assert templates.env.filters["tidy_text"] is collapse_blank_lines
