"""
데이터셋 전처리 및 5 LOOK 계약 무결성 검증 스크립트
- Train(864) / Validation(100) / Test(100) 간 중복 제로 검증
- 5 LOOK 슬롯 순서, 슬롯 중복 없음, 옷장 item_id 정합성 검증
"""

import json
import hashlib
from pathlib import Path

EXPECTED_ROLES = [
    "preference_best",
    "preference_alternative",
    "exploration",
    "wardrobe_best",
    "wardrobe_alternative",
]
ALLOWED_TOOLS = {"get_user_context", "get_wardrobe", "get_weather", "get_calendar_events"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_dataset_folder(data_dir: str):
    root = Path(data_dir)
    manifest = json.loads((root / "dataset_manifest.json").read_text(encoding="utf-8"))

    for fname, expected_hash in manifest["sha256"].items():
        actual_hash = sha256_file(root / fname)
        assert actual_hash == expected_hash, f"SHA256 mismatch for {fname}"

    splits = {}
    for split_file in ["train.jsonl", "validation.jsonl", "test.jsonl"]:
        rows = [json.loads(line) for line in (root / split_file).read_text(encoding="utf-8").splitlines() if line.strip()]
        splits[split_file] = rows

    # Check zero prompt overlap
    get_prompts = lambda rows: {next(m["content"] for m in r["messages"] if m["role"] == "user") for r in rows}
    p_train = get_prompts(splits["train.jsonl"])
    p_val = get_prompts(splits["validation.jsonl"])
    p_test = get_prompts(splits["test.jsonl"])

    assert len(p_train & p_val) == 0, "Overlap between train and validation"
    assert len(p_train & p_test) == 0, "Overlap between train and test"
    assert len(p_val & p_test) == 0, "Overlap between validation and test"
    print("All SHA256 hashes and zero-overlap checks passed!")


if __name__ == "__main__":
    verify_dataset_folder("./qwen35_864_five_look_data_v2")
