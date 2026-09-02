import pytest

from app.core.security import sanitize_text


def test_sanitize_text_removes_angle_brackets() -> None:
    assert sanitize_text("<script>hello</script>", allow_question_text=True) == "scripthelloscript"


def test_sanitize_text_rejects_command_in_non_question_fields() -> None:
    with pytest.raises(ValueError):
        sanitize_text("hello && rm -rf /")
