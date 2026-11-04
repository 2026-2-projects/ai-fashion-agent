"""One current reaction and save per server-issued LOOK, with reversible summaries."""

import json
from collections import Counter
from datetime import datetime
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.contracts import AgentRecommendationResponse, FashionLook, LookReference
from app.agent.personalization import LookFeatures
from app.agent.tools.wardrobe import get_wardrobe
from app.agent.validators import AgentResultError, validate_owned_look, validate_wardrobe_looks

ReasonCode = Literal["color", "fit", "style", "too_formal", "too_plain"]


class FeedbackWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    reaction: Literal["like", "dislike"]
    reason_codes: list[ReasonCode] = Field(default_factory=list, max_length=5)
    comment: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_reasons(self) -> Self:
        self.reason_codes = list(dict.fromkeys(self.reason_codes))
        if self.reaction == "dislike" and not self.reason_codes:
            raise ValueError("싫어요 이유를 하나 이상 선택해 주세요.")
        if self.reaction == "like" and self.reason_codes:
            raise ValueError("좋아요에는 싫어요 이유를 지정할 수 없습니다.")
        return self


class FeedbackState(BaseModel):
    outfit_id: UUID
    reaction: Literal["like", "dislike"] | None = None
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    comment: str | None = None


class SaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SavedOutfit(BaseModel):
    outfit_id: UUID
    saved_at: datetime
    look: FashionLook
    feedback: FeedbackState
    missing_item_ids: list[int]


class SavedOutfits(BaseModel):
    items: list[SavedOutfit]
    total: int
    limit: int
    offset: int


class InteractionError(Exception):
    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def summarize_signals(signals: list[dict]) -> dict:
    """Rebuild from current state; no click counters or cumulative update drift."""
    if not signals:
        return {}
    scores = {key: Counter() for key in ("styles", "fits", "colors")}
    counts, tendencies = Counter(), Counter()
    for signal in signals:
        features = LookFeatures.model_validate(signal["features"])
        reaction, reasons = signal["reaction"], set(signal["reason_codes"])
        counts[reaction] += 1
        if reaction == "dislike":
            dimensions = set()
            if reasons & {"style", "too_formal", "too_plain"}:
                dimensions.add("styles")
            if "color" in reasons:
                dimensions.add("colors")
            if "fit" in reasons:
                dimensions.add("fits")
            tendencies.update(reasons & {"too_formal", "too_plain"})
            weight = -1
        else:
            dimensions, weight = set(scores), 3 if reaction == "save" else 1
        for dimension in dimensions:
            for tag in getattr(features, dimension):
                scores[dimension][tag] += weight
    bounded = {}
    for dimension, values in scores.items():
        positive = sorted((tag for tag in values if values[tag] > 0), key=lambda t: (-values[t], t))
        negative = sorted((tag for tag in values if values[tag] < 0), key=lambda t: (values[t], t))
        bounded[dimension] = {tag: values[tag] for tag in positive[:5] + negative[:5]}
    return {
        "weights": bounded,
        "liked_styles": [tag for tag, score in bounded["styles"].items() if score > 0],
        "disliked_tendencies": sorted(tendencies, key=lambda t: (-tendencies[t], t))[:5],
        "signals": {key: counts[key] for key in ("like", "dislike", "save")},
    }


class FeedbackService:
    def __init__(self, db: Session):
        self.db = db

    def record_recommendation(
        self, user_id: int, result: AgentRecommendationResponse
    ) -> AgentRecommendationResponse:
        # Recheck ownership against the live DB after inference; lock through snapshot commit.
        wardrobe = get_wardrobe(self.db, user_id, for_share=True)
        stripped = [strip_images(look) for look in result.looks]
        result.looks = validate_wardrobe_looks(stripped, wardrobe)
        by_id = {item["item_id"]: item for item in wardrobe}
        references = []
        for look in result.looks:
            features = result._look_features.get(look.look_id, LookFeatures())
            if look.look_id >= 4:
                owned = [by_id[item.item_id] for item in look.items]
                features = LookFeatures(
                    styles=features.styles,
                    colors=[item["color"] for item in owned if item.get("color")],
                    fits=[item["fit"] for item in owned if item.get("fit")],
                )
            if look.status == "unavailable":
                features = LookFeatures()
            outfit_id = uuid4()
            self.db.execute(
                text("""
                    INSERT INTO recommendation_looks (id, user_id, look_id, snapshot, features)
                    VALUES (:id, :user_id, :look_id,
                            CAST(:snapshot AS jsonb), CAST(:features AS jsonb))
                """),
                {
                    "id": outfit_id,
                    "user_id": user_id,
                    "look_id": look.look_id,
                    "snapshot": strip_images(look).model_dump_json(),
                    "features": features.model_dump_json(),
                },
            )
            references.append(LookReference(look_id=look.look_id, outfit_id=outfit_id))
        self.db.commit()
        result.look_refs = references
        return result

    def _lock_user(self, user_id: int) -> None:
        # All feedback/save mutations acquire this same lock before reading current state.
        row = self.db.execute(
            text("SELECT id FROM users WHERE id = :id FOR UPDATE"), {"id": user_id}
        ).first()
        if row is None:
            raise InteractionError("user_not_found", "로그인이 필요합니다.", 401)

    def _lookup(self, user_id: int, outfit_id: UUID) -> dict:
        row = (
            self.db.execute(
                text("""
                SELECT * FROM recommendation_looks WHERE id = :id AND user_id = :user_id
            """),
                {"id": outfit_id, "user_id": user_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise InteractionError("outfit_not_found", "코디를 찾을 수 없습니다.", 404)
        return dict(row)

    @staticmethod
    def _available(row: dict) -> FashionLook:
        look = FashionLook.model_validate(row["snapshot"], strict=True)
        if look.status != "available":
            raise InteractionError(
                "outfit_unavailable", "사용 불가 코디에는 반응하거나 저장할 수 없습니다.", 422
            )
        return look

    def feedback(self, user_id: int, outfit_id: UUID) -> FeedbackState:
        self._lookup(user_id, outfit_id)
        row = (
            self.db.execute(
                text("SELECT * FROM feedback WHERE user_id = :user AND outfit_id = :outfit"),
                {"user": user_id, "outfit": outfit_id},
            )
            .mappings()
            .first()
        )
        return feedback_state(outfit_id, row)

    def put_feedback(self, user_id: int, outfit_id: UUID, payload: FeedbackWrite) -> FeedbackState:
        self._lock_user(user_id)
        self._available(self._lookup(user_id, outfit_id))
        self.db.execute(
            text("""
                INSERT INTO feedback (user_id, outfit_id, reaction, reason_codes, comment)
                VALUES (:user, :outfit, :reaction, :reasons, :comment)
                ON CONFLICT (user_id, outfit_id) DO UPDATE SET
                    reaction = EXCLUDED.reaction, reason_codes = EXCLUDED.reason_codes,
                    comment = EXCLUDED.comment, updated_at = CURRENT_TIMESTAMP
            """),
            {
                "user": user_id,
                "outfit": outfit_id,
                "reaction": payload.reaction,
                "reasons": payload.reason_codes,
                "comment": payload.comment,
            },
        )
        self._rebuild(user_id)
        state = self.feedback(user_id, outfit_id)
        self.db.commit()
        return state

    def delete_feedback(self, user_id: int, outfit_id: UUID) -> None:
        self._lock_user(user_id)
        self._lookup(user_id, outfit_id)
        self.db.execute(
            text("DELETE FROM feedback WHERE user_id = :user AND outfit_id = :outfit"),
            {"user": user_id, "outfit": outfit_id},
        )
        self._rebuild(user_id)
        self.db.commit()

    def save(self, user_id: int, outfit_id: UUID) -> SavedOutfit:
        self._lock_user(user_id)
        look = self._available(self._lookup(user_id, outfit_id))
        saved = self.db.execute(
            text("SELECT 1 FROM saved_outfits WHERE user_id = :user AND outfit_id = :outfit"),
            {"user": user_id, "outfit": outfit_id},
        ).first()
        if not saved:
            wardrobe = get_wardrobe(self.db, user_id, for_share=True)
            try:
                if look.look_id >= 4:
                    validate_owned_look(strip_images(look), wardrobe)
            except AgentResultError:
                raise InteractionError(
                    "wardrobe_changed", "코디에 포함된 옷이 삭제되거나 변경되었습니다.", 409
                ) from None
            self.db.execute(
                text("""
                    INSERT INTO saved_outfits (user_id, outfit_id) VALUES (:user, :outfit)
                    ON CONFLICT (user_id, outfit_id) DO NOTHING
                """),
                {"user": user_id, "outfit": outfit_id},
            )
        self._rebuild(user_id)
        result = self.saved(user_id, outfit_id)
        self.db.commit()
        return result

    def unsave(self, user_id: int, outfit_id: UUID) -> None:
        self._lock_user(user_id)
        self._lookup(user_id, outfit_id)
        self.db.execute(
            text("DELETE FROM saved_outfits WHERE user_id = :user AND outfit_id = :outfit"),
            {"user": user_id, "outfit": outfit_id},
        )
        self._rebuild(user_id)
        self.db.commit()

    def _rebuild(self, user_id: int) -> None:
        rows = (
            self.db.execute(
                text("""
                SELECT r.features, f.reaction, f.reason_codes
                FROM feedback f JOIN recommendation_looks r ON r.id = f.outfit_id
                WHERE f.user_id = :user
                UNION ALL
                SELECT r.features, 'save' AS reaction, '{}'::text[] AS reason_codes
                FROM saved_outfits s JOIN recommendation_looks r ON r.id = s.outfit_id
                WHERE s.user_id = :user
            """),
                {"user": user_id},
            )
            .mappings()
            .all()
        )
        summary = summarize_signals(rows)
        self.db.execute(
            text("""
                INSERT INTO user_preferences (user_id, feedback_summary)
                VALUES (:user, CAST(:summary AS jsonb))
                ON CONFLICT (user_id) DO UPDATE SET feedback_summary = EXCLUDED.feedback_summary,
                    updated_at = CURRENT_TIMESTAMP
            """),
            {"user": user_id, "summary": json.dumps(summary)},
        )

    def _saved_rows(
        self, user_id: int, *, outfit_id: UUID | None = None, limit: int = 20, offset: int = 0
    ) -> list[dict]:
        condition = " AND r.id = :outfit" if outfit_id is not None else ""
        rows = (
            self.db.execute(
                text(
                    """
                SELECT r.id, r.snapshot, s.created_at, f.reaction, f.reason_codes, f.comment
                FROM saved_outfits s JOIN recommendation_looks r ON r.id = s.outfit_id
                LEFT JOIN feedback f ON f.outfit_id = r.id AND f.user_id = s.user_id
                WHERE s.user_id = :user
            """
                    + condition
                    + " ORDER BY s.created_at DESC, r.id DESC LIMIT :limit OFFSET :offset"
                ),
                {"user": user_id, "outfit": outfit_id, "limit": limit, "offset": offset},
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]

    def saved(self, user_id: int, outfit_id: UUID) -> SavedOutfit:
        rows = self._saved_rows(user_id, outfit_id=outfit_id)
        if not rows:
            raise InteractionError("saved_outfit_not_found", "저장한 코디를 찾을 수 없습니다.", 404)
        wardrobe = get_wardrobe(self.db, user_id)
        return present_saved(rows[0], wardrobe)

    def list_saved(self, user_id: int, limit: int, offset: int) -> SavedOutfits:
        rows = self._saved_rows(user_id, limit=limit, offset=offset)
        total = self.db.execute(
            text("SELECT count(*) FROM saved_outfits WHERE user_id = :user"), {"user": user_id}
        ).scalar_one()
        wardrobe = get_wardrobe(self.db, user_id) if rows else []
        return SavedOutfits(
            items=[present_saved(row, wardrobe) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )


def strip_images(look: FashionLook) -> FashionLook:
    return look.model_copy(
        update={"items": [item.model_copy(update={"image_url": None}) for item in look.items]}
    )


def feedback_state(outfit_id: UUID, row) -> FeedbackState:
    return FeedbackState(
        outfit_id=outfit_id,
        reaction=row["reaction"] if row else None,
        reason_codes=(row["reason_codes"] or []) if row else [],
        comment=row["comment"] if row else None,
    )


def present_saved(row: dict, wardrobe: list[dict]) -> SavedOutfit:
    look = FashionLook.model_validate(row["snapshot"], strict=True)
    by_id = {item["item_id"]: item for item in wardrobe}
    missing = []
    for piece in look.items:
        source = by_id.get(piece.item_id)
        if piece.item_id is not None and source is None:
            missing.append(piece.item_id)
        piece.image_url = source.get("image") if source else None
    return SavedOutfit(
        outfit_id=row["id"],
        saved_at=row["created_at"],
        look=look,
        feedback=feedback_state(row["id"], row),
        missing_item_ids=missing,
    )
