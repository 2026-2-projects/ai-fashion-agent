from unittest.mock import Mock

import pytest

from app.agent.tools.user_context import get_user_context


def test_get_user_context_normalizes_missing_and_saved_values():
    db = Mock()
    db.execute.return_value.mappings.return_value.first.return_value = {
        "gender": None,
        "age_group": "20s",
        "height_cm": 175,
        "body_type": "slim",
        "preferred_styles": ["minimal"],
        "preferred_colors": ["navy"],
        "disliked_colors": None,
        "preferred_fit": "regular",
        "feedback_summary": {"liked_styles": ["minimal"]},
    }

    result = get_user_context(db, 7)

    assert result == {
        "profile": {
            "gender": None,
            "age_group": "20s",
            "height_cm": 175,
            "body_type": "slim",
        },
        "preference": {
            "preferred_styles": ["minimal"],
            "preferred_colors": ["navy"],
            "disliked_colors": [],
            "preferred_fit": "regular",
        },
        "feedback_summary": {"liked_styles": ["minimal"]},
    }
    assert db.execute.call_args.args[1] == {"user_id": 7}


def test_get_user_context_rejects_unknown_user():
    db = Mock()
    db.execute.return_value.mappings.return_value.first.return_value = None

    with pytest.raises(LookupError, match="Context"):
        get_user_context(db, 999)
