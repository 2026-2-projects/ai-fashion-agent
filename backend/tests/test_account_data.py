"""Contract-level tests for the account data deletion endpoint (no real rows removed)."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1 import account_data


class Result:
    def __init__(self, value=None, rows=None, rowcount=0):
        self.value, self.rows, self.rowcount = value, rows or [], rowcount

    def scalar_one(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value

    def all(self):
        return self.rows


class FakeDatabase:
    def __init__(self):
        self.counts = dict(profile=1, preferences=1, wardrobe=2, feedback=3, saved=1, recommendations=2)
        self.statements = []
        self.commit_count = 0
        self.rollback_count = 0
        self.fail = False

    def execute(self, statement, params):
        sql = str(statement)
        assert params.get("user_id") == 7  # all queries are scoped to authenticated user
        self.statements.append(sql)
        if self.fail and "DELETE FROM" in sql:
            raise SQLAlchemyError("synthetic failure")
        if "SELECT password_hash" in sql:
            return Result(value="test-hash")
        if "SELECT image_url FROM wardrobe_items" in sql:
            return Result(rows=[("wardrobe/7/00000000000000000000000000000001.jpg",), (None,)])
        for key, table in account_data.COUNT_TABLES.items():
            if f"SELECT COUNT(*) FROM {table}" in sql:
                return Result(value=self.counts[key])
            if f"DELETE FROM {table}" in sql:
                prev = self.counts[key]
                self.counts[key] = 0
                return Result(rowcount=prev)
        raise AssertionError(f"Unexpected SQL: {sql}")

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


@pytest.fixture
def env(monkeypatch):
    db = FakeDatabase()
    monkeypatch.setattr(account_data, "password_hash", SimpleNamespace(verify=lambda provided, digest: provided == "correct" and digest == "test-hash"))
    recomputed = []
    removed = []
    monkeypatch.setattr(account_data, "rebuild_feedback_summary", lambda db, uid: recomputed.append(uid))
    monkeypatch.setattr(account_data, "remove_image", lambda key, uid: removed.append((key, uid)))
    return db, recomputed, removed


def request(scope, password="correct"):
    return account_data.DataDeleteRequest(scope=scope, password=password)


def test_summary_is_user_scoped(env):
    db, _, _ = env
    summary = account_data.read_my_data_summary({"id": 7}, db)
    assert summary.wardrobe == 2
    assert summary.recommendations == 2
    assert db.commit_count == 0


def test_bad_password_blocks_all_deletes(env):
    db, _, _ = env
    with pytest.raises(HTTPException) as error:
        account_data.delete_my_data(request("wardrobe", "wrong"), {"id": 7}, db, None)
    assert error.value.status_code == 403
    assert db.commit_count == 0
    assert db.counts["wardrobe"] == 2
    assert db.rollback_count == 1


def test_wardrobe_delete_and_scoped_photo_cleanup(env):
    db, _, removed = env
    result = account_data.delete_my_data(request("wardrobe"), {"id": 7}, db, None)
    assert result.scope == "wardrobe"
    assert result.removed_records == 2
    assert result.summary.wardrobe == 0
    assert db.counts["feedback"] == 3
    assert removed == [("wardrobe/7/00000000000000000000000000000001.jpg", 7)]
    assert db.commit_count == 1


def test_history_delete_clears_children_before_parent(env):
    db, recomputed, _ = env
    result = account_data.delete_my_data(request("history"), {"id": 7}, db, None)
    assert result.removed_records == 6
    assert [next(key for key, table in account_data.COUNT_TABLES.items() if f"DELETE FROM {table}" in sql)
            for sql in db.statements if "DELETE FROM" in sql] == ["feedback", "saved", "recommendations"]
    assert result.summary.profile == 1 and result.summary.wardrobe == 2
    assert recomputed == [7]


def test_saved_delete_preserves_feedback_and_recomputes_summary(env):
    db, recomputed, _ = env
    result = account_data.delete_my_data(request("saved"), {"id": 7}, db, None)
    assert result.removed_records == 1
    assert result.summary.feedback == 3
    assert result.summary.recommendations == 2
    assert recomputed == [7]


def test_profile_delete_does_not_remove_account(env):
    db, _, _ = env
    result = account_data.delete_my_data(request("profile"), {"id": 7}, db, None)
    assert result.removed_records == 1
    assert result.summary.profile == 0
    assert all("DELETE FROM users" not in sql for sql in db.statements)


def test_unknown_scope_and_extra_fields_rejected():
    with pytest.raises(ValidationError):
        account_data.DataDeleteRequest(scope="all_users", password="correct")
    with pytest.raises(ValidationError):
        account_data.DataDeleteRequest(scope="wardrobe", password="correct", user_id=8)


def test_sql_error_rolls_back_and_returns_500(env):
    db, _, _ = env
    db.fail = True
    with pytest.raises(HTTPException) as error:
        account_data.delete_my_data(request("feedback"), {"id": 7}, db, None)
    assert error.value.status_code == 500
    assert db.rollback_count == 1 and db.commit_count == 0
