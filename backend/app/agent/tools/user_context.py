"""인증된 사용자의 프로필·취향·개인화 요약을 읽는 Agent Tool."""

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_user_context(db: Session, user_id: int) -> dict:
    """Backend가 인증한 user_id의 Agent용 개인화 Context만 반환한다."""
    row = (
        db.execute(
            text("""
                SELECT
                    p.gender,
                    p.age_group,
                    p.height_cm,
                    p.body_type,
                    pref.preferred_styles,
                    pref.preferred_colors,
                    pref.disliked_colors,
                    pref.preferred_fit,
                    pref.feedback_summary
                FROM users AS u
                LEFT JOIN user_profiles AS p ON p.user_id = u.id
                LEFT JOIN user_preferences AS pref ON pref.user_id = u.id
                WHERE u.id = :user_id
            """),
            {"user_id": user_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise LookupError("사용자 Context를 찾을 수 없습니다.")

    return {
        "profile": {
            "gender": row["gender"],
            "age_group": row["age_group"],
            "height_cm": row["height_cm"],
            "body_type": row["body_type"],
        },
        "preference": {
            "preferred_styles": row["preferred_styles"] or [],
            "preferred_colors": row["preferred_colors"] or [],
            "disliked_colors": row["disliked_colors"] or [],
            "preferred_fit": row["preferred_fit"],
        },
        "feedback_summary": row["feedback_summary"] or {},
    }
