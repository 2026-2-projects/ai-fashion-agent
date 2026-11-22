"""사유 입력 계약과 SQL 바인딩 단위 테스트. 실제 DB 연결을 사용하지 않는다."""

import json
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.agent.contracts import FashionLook
from app.api.v1 import recommendations
from app.services import recommendation_interactions as interactions


class FeedbackReasonPayloadTests(unittest.TestCase):
    def other(self, reason_text):
        return recommendations.FeedbackUpdate(
            feedback_type="dislike", reason="other", reason_text=reason_text
        )

    def test_all_reasons_and_optional_reason(self):
        reasons = (
            "color", "fit", "not_my_style", "too_dressed_up", "too_plain",
            "too_casual", "weather", "occasion", "combination",
        )
        for reason in reasons:
            with self.subTest(reason=reason):
                payload = recommendations.FeedbackUpdate(feedback_type="dislike", reason=reason)
                self.assertEqual(payload.reason, reason)
                self.assertIsNone(payload.reason_text)
        self.assertEqual(self.other("원하는 분위기와 달라요").reason, "other")
        for feedback_type in ("like", "dislike"):
            payload = recommendations.FeedbackUpdate(feedback_type=feedback_type)
            self.assertIsNone(payload.reason)
            self.assertIsNone(payload.reason_text)

    def test_other_requires_nonempty_text(self):
        for value in (None, "", " \t\n\r\u00a0\u3000"):
            with self.subTest(value=repr(value)), self.assertRaises(ValidationError):
                self.other(value)
        with self.assertRaises(ValidationError):
            recommendations.FeedbackUpdate(feedback_type="dislike", reason="other")

    def test_text_is_only_allowed_for_dislike_other(self):
        for feedback_type, reason in (("like", None), ("dislike", None), ("dislike", "color")):
            for value in ("설명", "", " "):
                with self.subTest(feedback_type=feedback_type, reason=reason, value=value):
                    with self.assertRaises(ValidationError):
                        recommendations.FeedbackUpdate(
                            feedback_type=feedback_type, reason=reason, reason_text=value
                        )
        with self.assertRaises(ValidationError):
            recommendations.FeedbackUpdate(
                feedback_type="like", reason="other", reason_text="설명"
            )

    def test_trim_precedes_limit_and_limit_counts_unicode_codepoints(self):
        for value in ("가" * 300, "😀" * 300):
            with self.subTest(value=value[:1]):
                self.assertEqual(self.other("\u00a0 \t" + value + "\r\n\u3000").reason_text, value)
                with self.assertRaises(ValidationError):
                    self.other(value + "한")
        self.assertEqual(self.other("  색 조합\n조금\t어색해요  ").reason_text, "색 조합\n조금\t어색해요")

    def test_disallowed_controls_are_rejected_before_trimming(self):
        forbidden = [code for code in range(32) if code not in (9, 10, 13)]
        forbidden += list(range(127, 160))
        for code in forbidden:
            with self.subTest(code=code), self.assertRaises(ValidationError):
                self.other(chr(code) + "사유")

    def test_html_and_sql_characters_stay_plain_text(self):
        value = "<script>alert('x')</script> '); DROP TABLE feedback; --"
        self.assertEqual(self.other(value).reason_text, value)

    def test_invalid_types_reasons_and_extra_fields_are_rejected(self):
        for value in (123, True, [], {}, b"text"):
            with self.subTest(value=repr(value)), self.assertRaises(ValidationError):
                self.other(value)
        for payload in (
            {"feedback_type": "dislike", "reason": "new_unknown_reason"},
            {"feedback_type": "dislike", "reason": "OTHER"},
            {"feedback_type": "save"},
            {"feedback_type": "like", "style_tags": ["injected"]},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                recommendations.FeedbackUpdate.model_validate(payload)


class FeedbackReasonServiceTests(unittest.TestCase):
    def setUp(self):
        self.recommendation_id = UUID("00000000-0000-4000-8000-000000000001")
        self.user_id = 7
        self.look = FashionLook(
            look_id=1,
            role="preference_best",
            status="available",
            style="미니멀",
            items=[
                {"slot": slot, "name": slot, "item_id": None}
                for slot in ("top", "bottom", "shoes")
            ],
            reason="서버가 생성한 추천",
        )

    def write_feedback(self, feedback_type, reason, reason_text=None):
        db = Mock()
        with (
            patch.object(interactions, "_get_available_look", return_value=self.look),
            patch.object(interactions, "rebuild_feedback_summary", return_value={}) as rebuild,
            patch.object(interactions, "_get_interaction", return_value={}),
        ):
            interactions.set_feedback(
                db, self.user_id, self.recommendation_id, 1, feedback_type, reason, reason_text
            )
            rebuild.assert_called_once_with(db, self.user_id)
        return db.execute.call_args

    def test_other_text_is_a_parameter_and_never_a_style_tag(self):
        value = "<b>사유</b> '); DROP TABLE feedback; --"
        call = self.write_feedback("DISLIKE", "OTHER", "  " + value + "  ")
        sql, params = call.args
        self.assertIn(":reason_text", str(sql))
        self.assertIn("reason_text = EXCLUDED.reason_text", str(sql))
        self.assertNotIn(value, str(sql))
        self.assertEqual(params["reason_text"], value)
        self.assertEqual(params["style_tags"], [self.look.style])
        self.assertEqual(params["user_id"], self.user_id)
        self.assertEqual(params["recommendation_id"], self.recommendation_id)

    def test_like_or_preset_clears_stale_text_and_old_callers_work(self):
        for feedback_type, reason in (("LIKE", None), ("DISLIKE", "WEATHER"), ("DISLIKE", None)):
            with self.subTest(feedback_type=feedback_type, reason=reason):
                call = self.write_feedback(feedback_type, reason, "이전 기타 사유")
                self.assertIsNone(call.args[1]["reason_text"])
        db = Mock()
        with (
            patch.object(interactions, "_get_available_look", return_value=self.look),
            patch.object(interactions, "rebuild_feedback_summary", return_value={}),
            patch.object(interactions, "_get_interaction", return_value={}),
        ):
            interactions.set_feedback(db, self.user_id, self.recommendation_id, 1, "LIKE", None)
        self.assertIsNone(db.execute.call_args.args[1]["reason_text"])

    def test_read_restores_text_and_saved_state_independently(self):
        feedback = {
            "look_id": 1, "feedback_type": "DISLIKE", "reason": "OTHER", "reason_text": "조합 사유"
        }
        first, second = Mock(), Mock()
        first.mappings.return_value = [feedback]
        second.scalars.return_value = [1]
        db = Mock()
        db.execute.side_effect = [first, second]
        with patch.object(interactions, "load_owned_looks", return_value=[self.look]):
            states = interactions.get_interactions(db, self.user_id, self.recommendation_id)
        state = recommendations.LookInteractionState.model_validate(states[0])
        self.assertEqual(state.feedback, "dislike")
        self.assertEqual(state.reason, "other")
        self.assertEqual(state.reason_text, "조합 사유")
        self.assertTrue(state.saved)
        sql, params = db.execute.call_args_list[0].args
        self.assertIn("reason_text", str(sql))
        self.assertEqual(params["user_id"], self.user_id)

    def test_cancel_returns_null_text_and_keeps_saved_flag(self):
        db = Mock()
        first, second = Mock(), Mock()
        first.mappings.return_value = []
        second.scalars.return_value = [1]
        db.execute.side_effect = [Mock(), first, second]
        with (
            patch.object(interactions, "_get_available_look", return_value=self.look),
            patch.object(interactions, "rebuild_feedback_summary", return_value={}),
        ):
            state = interactions.delete_feedback(db, self.user_id, self.recommendation_id, 1)
        self.assertIsNone(state["feedback"])
        self.assertIsNone(state["reason"])
        self.assertIsNone(state["reason_text"])
        self.assertTrue(state["saved"])
        self.assertIn("DELETE FROM feedback", str(db.execute.call_args_list[0].args[0]))

    def test_summary_stays_style_only_with_existing_score_policy(self):
        value = "개인적인 자유 입력은 요약에 들어가면 안 됩니다."
        result = Mock()
        result.mappings.return_value = [
            {"signal": "dislike", "style": "미니멀", "reason_text": value},
            {"signal": "like", "style": "캐주얼", "reason_text": value},
            {"signal": "save", "style": "캐주얼", "reason_text": value},
        ]
        db = Mock()
        db.execute.side_effect = [result, Mock()]
        summary = interactions.rebuild_feedback_summary(db, self.user_id)
        self.assertEqual(summary["score_policy"], {"like": 1, "dislike": -1, "save": 2})
        self.assertEqual(
            {entry["style"]: entry["score"] for entry in summary["style_scores"]},
            {"미니멀": -1, "캐주얼": 3},
        )
        self.assertNotIn("reason_text", str(db.execute.call_args_list[0].args[0]))
        self.assertNotIn(value, json.dumps(summary, ensure_ascii=False))
        self.assertNotIn(value, db.execute.call_args_list[1].args[1]["summary"])

    def test_foreign_recommendation_stops_before_mutation(self):
        user_result, recommendation_result = Mock(), Mock()
        user_result.scalar_one_or_none.return_value = self.user_id
        recommendation_result.scalar_one_or_none.return_value = None
        db = Mock()
        db.execute.side_effect = [user_result, recommendation_result]
        with self.assertRaises(interactions.RecommendationNotFoundError):
            interactions.set_feedback(
                db, self.user_id, self.recommendation_id, 1, "DISLIKE", "OTHER", "사유"
            )
        self.assertEqual(db.execute.call_count, 2)
        for call in db.execute.call_args_list:
            self.assertIn("user_id", call.args[1])
            self.assertNotIn("INSERT", str(call.args[0]))

    def test_unavailable_look_stops_before_mutation(self):
        unavailable = FashionLook(
            look_id=1, role="preference_best", status="unavailable",
            style=None, items=[], reason="사용 불가",
        )
        db = Mock()
        with (
            patch.object(interactions, "_lock_user"),
            patch.object(interactions, "load_owned_looks", return_value=[unavailable]),
            self.assertRaises(interactions.LookUnavailableError),
        ):
            interactions.set_feedback(
                db, self.user_id, self.recommendation_id, 1, "DISLIKE", "OTHER", "사유"
            )
        db.execute.assert_not_called()

    def test_api_passes_canonical_text_and_commits(self):
        payload = recommendations.FeedbackUpdate(
            feedback_type="dislike", reason="other", reason_text="  직접 입력  "
        )
        db = Mock()
        with patch.object(recommendations, "set_feedback", return_value={}) as write:
            recommendations.update_look_feedback(
                self.recommendation_id, 1, payload, {"id": self.user_id}, db, None
            )
        write.assert_called_once_with(
            db, self.user_id, self.recommendation_id, 1, "DISLIKE", "OTHER", "직접 입력"
        )
        db.commit.assert_called_once_with()
        db.rollback.assert_not_called()

    def test_sql_failure_rolls_back_instead_of_committing(self):
        db = Mock()
        payload = recommendations.FeedbackUpdate(
            feedback_type="dislike", reason="other", reason_text="사유"
        )
        with (
            patch.object(recommendations, "set_feedback", side_effect=SQLAlchemyError("failure")),
            self.assertRaises(HTTPException) as caught,
        ):
            recommendations.update_look_feedback(
                self.recommendation_id, 1, payload, {"id": self.user_id}, db, None
            )
        self.assertEqual(caught.exception.status_code, 500)
        db.rollback.assert_called_once_with()
        db.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
