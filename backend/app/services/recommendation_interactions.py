"""추천 LOOK 평가·저장과 개인화 요약을 원자적으로 관리한다."""

import json
from collections.abc import Mapping
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.contracts import AgentDraft, FashionLook

FeedbackType = Literal["LIKE", "DISLIKE"]

SCORE_POLICY = {
    "like": 1,
    "dislike": -1,
    "save": 2,
}


class RecommendationNotFoundError(LookupError):
    """추천이 없거나 현재 사용자의 추천이 아닐 때 발생한다."""


class LookUnavailableError(ValueError):
    """사용할 수 없는 LOOK에 상호작용하려 할 때 발생한다."""


class StoredRecommendationError(RuntimeError):
    """서버에 저장된 추천 JSON이 계약을 위반할 때 발생한다."""


def _lock_user(db: Session, user_id: int) -> None:
    """사용자별 상호작용과 집계 갱신을 같은 순서로 직렬화한다."""
    locked_user = db.execute(
        text("SELECT id FROM users WHERE id = :user_id FOR UPDATE"),
        {"user_id": user_id},
    ).scalar_one_or_none()
    if locked_user is None:
        raise RecommendationNotFoundError


def load_owned_looks(
    db: Session,
    user_id: int,
    recommendation_id: UUID,
    *,
    for_update: bool = False,
) -> list[FashionLook]:
    """현재 사용자 소유의 저장 추천을 읽고 5 LOOK 계약으로 검증한다."""
    lock_clause = " FOR UPDATE" if for_update else ""
    stored_looks = db.execute(
        text(
            """
            SELECT looks
            FROM recommendation_runs
            WHERE id = :recommendation_id
              AND user_id = :user_id
            """
            + lock_clause
        ),
        {
            "recommendation_id": recommendation_id,
            "user_id": user_id,
        },
    ).scalar_one_or_none()
    if stored_looks is None:
        raise RecommendationNotFoundError

    try:
        return AgentDraft(
            context_summary="서버에 저장된 추천",
            looks=stored_looks,
        ).looks
    except (TypeError, ValidationError) as exc:
        raise StoredRecommendationError from exc


def _get_available_look(
    db: Session,
    user_id: int,
    recommendation_id: UUID,
    look_id: int,
) -> FashionLook:
    _lock_user(db, user_id)
    looks = load_owned_looks(
        db,
        user_id,
        recommendation_id,
        for_update=True,
    )
    look = next((item for item in looks if item.look_id == look_id), None)
    if look is None:
        raise StoredRecommendationError
    if look.status != "available":
        raise LookUnavailableError
    return look


def _interaction_rows(
    db: Session,
    user_id: int,
    recommendation_id: UUID,
) -> tuple[dict[int, Mapping[str, Any]], set[int]]:
    feedback_rows = db.execute(
        text("""
            SELECT look_id, feedback_type, reason
            FROM feedback
            WHERE user_id = :user_id
              AND recommendation_id = :recommendation_id
              AND feedback_type IN ('LIKE', 'DISLIKE')
        """),
        {
            "user_id": user_id,
            "recommendation_id": recommendation_id,
        },
    ).mappings()
    feedback_by_look = {row["look_id"]: row for row in feedback_rows}

    saved_look_ids = set(
        db.execute(
            text("""
                SELECT look_id
                FROM saved_outfits
                WHERE user_id = :user_id
                  AND recommendation_id = :recommendation_id
            """),
            {
                "user_id": user_id,
                "recommendation_id": recommendation_id,
            },
        ).scalars()
    )
    return feedback_by_look, saved_look_ids


def _state_for_look(
    recommendation_id: UUID,
    look: FashionLook,
    feedback_by_look: Mapping[int, Mapping[str, Any]],
    saved_look_ids: set[int],
) -> dict[str, Any]:
    feedback = feedback_by_look.get(look.look_id)
    reason = feedback["reason"] if feedback else None
    return {
        "recommendation_id": recommendation_id,
        "look_id": look.look_id,
        "status": look.status,
        "feedback": feedback["feedback_type"].lower() if feedback else None,
        "reason": reason.lower() if isinstance(reason, str) else None,
        "saved": look.look_id in saved_look_ids,
    }


def get_interactions(
    db: Session,
    user_id: int,
    recommendation_id: UUID,
) -> list[dict[str, Any]]:
    """새로고침 뒤 복원할 5개 LOOK의 서버 상태를 반환한다."""
    looks = load_owned_looks(db, user_id, recommendation_id)
    feedback_by_look, saved_look_ids = _interaction_rows(
        db,
        user_id,
        recommendation_id,
    )
    return [
        _state_for_look(
            recommendation_id,
            look,
            feedback_by_look,
            saved_look_ids,
        )
        for look in looks
    ]


def _get_interaction(
    db: Session,
    user_id: int,
    recommendation_id: UUID,
    look: FashionLook,
) -> dict[str, Any]:
    feedback_by_look, saved_look_ids = _interaction_rows(
        db,
        user_id,
        recommendation_id,
    )
    return _state_for_look(
        recommendation_id,
        look,
        feedback_by_look,
        saved_look_ids,
    )


def set_feedback(
    db: Session,
    user_id: int,
    recommendation_id: UUID,
    look_id: int,
    feedback_type: FeedbackType,
    reason: str | None,
) -> dict[str, Any]:
    """평가를 한 행으로 설정하고 전체 개인화 점수를 다시 계산한다."""
    look = _get_available_look(
        db,
        user_id,
        recommendation_id,
        look_id,
    )
    db.execute(
        text("""
            INSERT INTO feedback (
                user_id,
                feedback_type,
                reason,
                style_tags,
                recommendation_id,
                look_id
            )
            VALUES (
                :user_id,
                :feedback_type,
                :reason,
                CAST(:style_tags AS TEXT[]),
                :recommendation_id,
                :look_id
            )
            ON CONFLICT (user_id, recommendation_id, look_id)
                WHERE recommendation_id IS NOT NULL
            DO UPDATE SET
                feedback_type = EXCLUDED.feedback_type,
                reason = EXCLUDED.reason,
                style_tags = EXCLUDED.style_tags,
                color_tags = '{}'::TEXT[],
                fit_tags = '{}'::TEXT[]
        """),
        {
            "user_id": user_id,
            "feedback_type": feedback_type,
            "reason": reason,
            "style_tags": [look.style],
            "recommendation_id": recommendation_id,
            "look_id": look_id,
        },
    )
    rebuild_feedback_summary(db, user_id)
    return _get_interaction(db, user_id, recommendation_id, look)


def delete_feedback(
    db: Session,
    user_id: int,
    recommendation_id: UUID,
    look_id: int,
) -> dict[str, Any]:
    """평가가 이미 없어도 같은 최종 상태를 반환한다."""
    look = _get_available_look(
        db,
        user_id,
        recommendation_id,
        look_id,
    )
    db.execute(
        text("""
            DELETE FROM feedback
            WHERE user_id = :user_id
              AND recommendation_id = :recommendation_id
              AND look_id = :look_id
              AND feedback_type IN ('LIKE', 'DISLIKE')
        """),
        {
            "user_id": user_id,
            "recommendation_id": recommendation_id,
            "look_id": look_id,
        },
    )
    rebuild_feedback_summary(db, user_id)
    return _get_interaction(db, user_id, recommendation_id, look)


def save_look(
    db: Session,
    user_id: int,
    recommendation_id: UUID,
    look_id: int,
) -> dict[str, Any]:
    """서버 원본 LOOK 스냅샷을 멱등적으로 저장한다."""
    look = _get_available_look(
        db,
        user_id,
        recommendation_id,
        look_id,
    )
    outfit_data = json.dumps(look.model_dump(mode="json"), ensure_ascii=False)
    db.execute(
        text("""
            INSERT INTO saved_outfits (
                user_id,
                title,
                outfit_data,
                recommendation_id,
                look_id
            )
            VALUES (
                :user_id,
                :title,
                CAST(:outfit_data AS JSONB),
                :recommendation_id,
                :look_id
            )
            ON CONFLICT (user_id, recommendation_id, look_id)
                WHERE recommendation_id IS NOT NULL
            DO UPDATE SET
                title = EXCLUDED.title,
                outfit_data = EXCLUDED.outfit_data
        """),
        {
            "user_id": user_id,
            "title": look.style[:100],
            "outfit_data": outfit_data,
            "recommendation_id": recommendation_id,
            "look_id": look_id,
        },
    )
    rebuild_feedback_summary(db, user_id)
    return _get_interaction(db, user_id, recommendation_id, look)


def delete_saved_look(
    db: Session,
    user_id: int,
    recommendation_id: UUID,
    look_id: int,
) -> dict[str, Any]:
    """저장이 이미 없어도 같은 최종 상태를 반환한다."""
    look = _get_available_look(
        db,
        user_id,
        recommendation_id,
        look_id,
    )
    db.execute(
        text("""
            DELETE FROM saved_outfits
            WHERE user_id = :user_id
              AND recommendation_id = :recommendation_id
              AND look_id = :look_id
        """),
        {
            "user_id": user_id,
            "recommendation_id": recommendation_id,
            "look_id": look_id,
        },
    )
    rebuild_feedback_summary(db, user_id)
    return _get_interaction(db, user_id, recommendation_id, look)


def rebuild_feedback_summary(db: Session, user_id: int) -> dict[str, Any]:
    """연결된 서버 추천만 사용해 점수 드리프트 없이 전체 재계산한다."""
    signals = db.execute(
        text("""
            SELECT
                LOWER(f.feedback_type) AS signal,
                look.value ->> 'style' AS style
            FROM feedback AS f
            JOIN recommendation_runs AS recommendation
              ON recommendation.id = f.recommendation_id
             AND recommendation.user_id = f.user_id
            CROSS JOIN LATERAL
                jsonb_array_elements(recommendation.looks) AS look(value)
            WHERE f.user_id = :user_id
              AND f.recommendation_id IS NOT NULL
              AND f.feedback_type IN ('LIKE', 'DISLIKE')
              AND look.value ->> 'look_id' = CAST(f.look_id AS TEXT)
              AND look.value ->> 'status' = 'available'
              AND NULLIF(BTRIM(look.value ->> 'style'), '') IS NOT NULL

            UNION ALL

            SELECT
                'save' AS signal,
                look.value ->> 'style' AS style
            FROM saved_outfits AS saved
            JOIN recommendation_runs AS recommendation
              ON recommendation.id = saved.recommendation_id
             AND recommendation.user_id = saved.user_id
            CROSS JOIN LATERAL
                jsonb_array_elements(recommendation.looks) AS look(value)
            WHERE saved.user_id = :user_id
              AND saved.recommendation_id IS NOT NULL
              AND look.value ->> 'look_id' = CAST(saved.look_id AS TEXT)
              AND look.value ->> 'status' = 'available'
              AND NULLIF(BTRIM(look.value ->> 'style'), '') IS NOT NULL
        """),
        {"user_id": user_id},
    ).mappings()

    by_style: dict[str, dict[str, Any]] = {}
    interaction_counts = {"likes": 0, "dislikes": 0, "saves": 0}
    count_key = {"like": "likes", "dislike": "dislikes", "save": "saves"}

    for row in signals:
        signal = row["signal"]
        style = row["style"]
        if signal not in SCORE_POLICY or not isinstance(style, str):
            continue
        entry = by_style.setdefault(
            style,
            {
                "style": style,
                "score": 0,
                "likes": 0,
                "dislikes": 0,
                "saves": 0,
            },
        )
        entry["score"] += SCORE_POLICY[signal]
        entry[count_key[signal]] += 1
        interaction_counts[count_key[signal]] += 1

    if by_style:
        style_scores = sorted(
            by_style.values(),
            key=lambda entry: (
                -entry["score"],
                entry["style"].casefold(),
                entry["style"],
            ),
        )
        positive_styles = [entry["style"] for entry in style_scores if entry["score"] > 0]
        negative_styles = [
            entry["style"]
            for entry in sorted(
                style_scores,
                key=lambda entry: (
                    entry["score"],
                    entry["style"].casefold(),
                    entry["style"],
                ),
            )
            if entry["score"] < 0
        ]
        summary: dict[str, Any] = {
            "version": 1,
            "score_policy": SCORE_POLICY,
            "interaction_counts": interaction_counts,
            "style_scores": style_scores,
            "positive_styles": positive_styles,
            "negative_styles": negative_styles,
        }
    else:
        summary = {}

    db.execute(
        text("""
            INSERT INTO user_preferences (user_id, feedback_summary)
            VALUES (:user_id, CAST(:summary AS JSONB))
            ON CONFLICT (user_id)
            DO UPDATE SET
                feedback_summary = EXCLUDED.feedback_summary,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_preferences.feedback_summary
                IS DISTINCT FROM EXCLUDED.feedback_summary
        """),
        {
            "user_id": user_id,
            "summary": json.dumps(summary, ensure_ascii=False),
        },
    )
    return summary


def list_saved_outfits(db: Session, user_id: int) -> list[dict[str, Any]]:
    """레거시 저장 행을 포함해 현재 사용자의 저장 목록만 반환한다."""
    rows = db.execute(
        text("""
            SELECT
                id,
                recommendation_id,
                look_id,
                title,
                outfit_data,
                created_at
            FROM saved_outfits
            WHERE user_id = :user_id
            ORDER BY created_at DESC, id DESC
        """),
        {"user_id": user_id},
    ).mappings()
    return [dict(row) for row in rows]
