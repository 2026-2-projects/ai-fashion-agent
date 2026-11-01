"""Agent가 인증된 사용자 옷장을 읽기 위한 내부 Tool."""

from sqlalchemy import text
from sqlalchemy.orm import Session


def get_wardrobe(db: Session, user_id: int) -> list[dict]:
    """백엔드가 인증해 준 user_id에 대해서만 호출한다."""
    records = db.execute(
        text("""
            SELECT id, category, item_type, color, fit, seasons, image_url
            FROM wardrobe_items
            WHERE user_id = :user_id
            ORDER BY id
        """),
        {"user_id": user_id},
    ).mappings().all()
    return [
        {
            "item_id": row["id"],
            "category": row["category"],
            "type": row["item_type"],
            "color": row["color"],
            "fit": row["fit"],
            "season": row["seasons"] or [],
            "image": f"/api/v1/wardrobe/{row['id']}/image" if row["image_url"] else None,
        }
        for row in records
    ]
