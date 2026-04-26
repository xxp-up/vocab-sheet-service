from __future__ import annotations

from datetime import date

from app.services.feedback import FeedbackService


def test_feedback_service_generates_expected_sections() -> None:
    service = FeedbackService()

    draft = service.generate_draft(
        transcript_text=(
            "Today we review comparative adjectives. "
            "A be as ... as B is one key pattern. "
            "Homework: finish the worksheet and memorize the irregular forms."
        ),
        lesson_date=date(2026, 3, 11),
        lesson_index=1,
        class_name="五年级英语提高班",
    )

    assert [section.key for section in draft.draft_sections] == [
        "header",
        "focus",
        "patterns",
        "homework",
        "teacher_note",
    ]
    assert "2026年March 11th，第1节" in draft.draft_sections[0].content
    assert "五年级英语提高班" in draft.draft_sections[0].content
    assert "Homework" not in draft.draft_sections[3].content
    assert "finish the worksheet" in draft.draft_sections[3].content.lower()
    assert "抬头" in draft.composed_text
