#!/usr/bin/env python3
"""Validate, merge, split, and convert the 80 Gold records for pilot SFT."""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path


ALLOWED_TOOLS = {
    "get_user_context",
    "get_wardrobe",
    "get_weather",
    "get_calendar_events",
}

FR_SYSTEM = (
    "당신은 개인 맞춤형 패션 추천 에이전트입니다. 제공된 기준 시각, 사용자 요청, "
    "프로필, 선호, 날씨, 일정, 옷장을 근거로 정확히 3개의 LOOK을 추천하세요. "
    "LOOK의 role은 preference_best, preference_alternative, exploration 순서로 사용하세요. "
    "일반 추천의 item_id는 null이어야 하며, 내 옷 추천은 제공된 wardrobe의 item_id만 "
    "사용해야 합니다. 답변은 answer 객체와 동일한 JSON만 출력하세요."
)

TC_SYSTEM = (
    "당신은 패션 에이전트의 Tool Router입니다. 요청에 필요한 Tool만 호출하고 불필요한 "
    "Tool은 호출하지 마세요. 사용할 수 있는 Tool은 get_user_context, get_wardrobe, "
    "get_weather, get_calendar_events 네 가지뿐입니다. Tool이 필요하지 않으면 직접 "
    "답변하세요. Tool 결과가 모두 주어지면 final_response 객체와 동일한 JSON으로 "
    "최종 행동을 출력하세요."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_user_context",
            "description": "사용자의 프로필, 패션 취향, 피드백 요약을 조회합니다.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_wardrobe",
            "description": "사용자가 등록한 옷장 아이템을 조회합니다.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "지정한 장소와 날짜, 시간의 날씨를 조회합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "place": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "time": {"type": "string", "description": "HH:MM"},
                },
                "required": ["place", "date", "time"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_calendar_events",
            "description": "지정한 날짜의 캘린더 일정을 조회합니다.",
            "parameters": {
                "type": "object",
                "properties": {"date": {"type": "string", "description": "YYYY-MM-DD"}},
                "required": ["date"],
                "additionalProperties": False,
            },
        },
    },
]


def author_for(record_id: str) -> str:
    prefix, number_text = record_id.split("-")
    number = int(number_text)
    if prefix == "FR":
        if number <= 15:
            return "김진호"
        if number <= 25:
            return "곽준오"
        if number <= 35:
            return "김서진"
        return "김윤아"
    if number <= 5:
        return "김진호"
    if number <= 15:
        return "곽준오"
    if number <= 25:
        return "김서진"
    return "김윤아"


def compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def validate_record(record: dict) -> list[str]:
    errors: list[str] = []
    record_id = record.get("id", "UNKNOWN")
    data_type = record.get("type")
    if data_type == "fashion_recommendation":
        context = record.get("context", {})
        looks = record.get("answer", {}).get("looks", [])
        if len(looks) != 3:
            errors.append(f"{record_id}: LOOK은 3개여야 함")
        expected_roles = ["preference_best", "preference_alternative", "exploration"]
        if [look.get("role") for look in looks] != expected_roles:
            errors.append(f"{record_id}: LOOK role 순서 오류")
        if [look.get("look_id") for look in looks] != [1, 2, 3]:
            errors.append(f"{record_id}: look_id 오류")
        if context.get("use_wardrobe"):
            valid_ids = {item.get("item_id") for item in context.get("wardrobe", [])}
            used_ids = {
                item.get("item_id")
                for look in looks
                for item in look.get("items", [])
            }
            invalid_ids = sorted(used_ids - valid_ids)
            if invalid_ids:
                errors.append(f"{record_id}: 존재하지 않는 item_id {invalid_ids}")
        else:
            non_null = [
                item.get("item_id")
                for look in looks
                for item in look.get("items", [])
                if item.get("item_id") is not None
            ]
            if non_null:
                errors.append(f"{record_id}: 일반 추천 item_id는 null이어야 함")
    elif data_type == "tool_calling":
        steps = record.get("steps", [])
        for index, step in enumerate(steps, start=1):
            if step.get("step") != index:
                errors.append(f"{record_id}: step 번호 불연속")
            name = step.get("tool_call", {}).get("name")
            if name not in ALLOWED_TOOLS:
                errors.append(f"{record_id}: 허용되지 않은 Tool {name}")
            if "arguments" not in step.get("tool_call", {}):
                errors.append(f"{record_id}: Tool arguments 누락")
            if "tool_result" not in step:
                errors.append(f"{record_id}: tool_result 누락")
        if not isinstance(record.get("final_response"), dict):
            errors.append(f"{record_id}: final_response 누락")
    else:
        errors.append(f"{record_id}: 알 수 없는 type {data_type}")
    return errors


def to_messages(record: dict) -> list[dict]:
    if record["type"] == "fashion_recommendation":
        user_payload = {
            "reference_datetime": record["reference_datetime"],
            "user_request": record["user_request"],
            "context": record["context"],
        }
        return [
            {"role": "system", "content": FR_SYSTEM},
            {"role": "user", "content": compact(user_payload)},
            {"role": "assistant", "content": compact(record["answer"])},
        ]

    messages: list[dict] = [
        {"role": "system", "content": TC_SYSTEM},
        {
            "role": "user",
            "content": compact(
                {
                    "reference_datetime": record["reference_datetime"],
                    "user_request": record["user_request"],
                }
            ),
        },
    ]
    for step in record["steps"]:
        call = step["tool_call"]
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": call["arguments"],
                        },
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "name": call["name"],
                "content": compact(step["tool_result"]),
            }
        )
    messages.append(
        {"role": "assistant", "content": compact(record["final_response"])}
    )
    return messages


def choose_split(records: list[dict], seed: int) -> dict[str, list[dict]]:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for record in records:
        groups[(record["author"], record["type"])].append(record)
    rng = random.Random(seed)
    for values in groups.values():
        values.sort(key=lambda item: item["id"])
        rng.shuffle(values)

    validation_quota = {
        ("김진호", "fashion_recommendation"): 1,
        ("김진호", "tool_calling"): 1,
        ("곽준오", "fashion_recommendation"): 1,
        ("곽준오", "tool_calling"): 1,
        ("김서진", "fashion_recommendation"): 1,
        ("김서진", "tool_calling"): 1,
        ("김윤아", "fashion_recommendation"): 2,
        ("김윤아", "tool_calling"): 0,
    }
    test_quota = {
        ("김진호", "fashion_recommendation"): 2,
        ("김진호", "tool_calling"): 0,
        ("곽준오", "fashion_recommendation"): 1,
        ("곽준오", "tool_calling"): 1,
        ("김서진", "fashion_recommendation"): 1,
        ("김서진", "tool_calling"): 1,
        ("김윤아", "fashion_recommendation"): 1,
        ("김윤아", "tool_calling"): 1,
    }

    result = {"train": [], "validation": [], "test": []}
    for key, values in groups.items():
        val_count = validation_quota[key]
        test_count = test_quota[key]
        result["validation"].extend(values[:val_count])
        result["test"].extend(values[val_count : val_count + test_count])
        result["train"].extend(values[val_count + test_count :])
    for values in result.values():
        values.sort(key=lambda item: item["id"])
    return result


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            messages = to_messages(record)
            expected_first_action = "fashion_recommendation"
            if record["type"] == "tool_calling":
                expected_first_action = (
                    record["steps"][0]["tool_call"]["name"]
                    if record["steps"]
                    else "direct_answer"
                )
            row = {
                "id": record["id"],
                "type": record["type"],
                "author": record["author"],
                "expected_first_action": expected_first_action,
                "messages_json": compact(messages),
            }
            handle.write(compact(row) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=3407)
    args = parser.parse_args()

    source_files = sorted(
        path
        for path in args.gold_dir.glob("*.json")
        if path.name != "sample-gold-data.json"
    )
    records: list[dict] = []
    source_counts: dict[str, int] = {}
    errors: list[str] = []
    for path in source_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        source_counts[path.name] = len(data)
        for record in data:
            record = dict(record)
            record["author"] = author_for(record["id"])
            record["source_file"] = path.name
            errors.extend(validate_record(record))
            records.append(record)

    ids = [record["id"] for record in records]
    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    if len(records) != 80:
        errors.append(f"전체 레코드 수가 80이 아님: {len(records)}")
    if duplicates:
        errors.append(f"중복 ID: {duplicates}")
    if Counter(record["type"] for record in records) != {
        "fashion_recommendation": 50,
        "tool_calling": 30,
    }:
        errors.append("FR/TC 개수가 50/30이 아님")
    if errors:
        raise ValueError("\n".join(errors))

    splits = choose_split(records, args.seed)
    expected_sizes = {"train": 64, "validation": 8, "test": 8}
    for name, expected in expected_sizes.items():
        if len(splits[name]) != expected:
            raise ValueError(f"{name} 크기 오류: {len(splits[name])}")

    clean_records = []
    for record in sorted(records, key=lambda item: item["id"]):
        clean = {key: value for key, value in record.items() if key not in {"author", "source_file"}}
        clean_records.append(clean)
    write_json(args.output_dir / "data" / "raw" / "gold_merged.json", clean_records)
    write_json(args.output_dir / "data" / "processed" / "tool_definitions.json", TOOLS)
    for name, split_records in splits.items():
        write_jsonl(args.output_dir / "data" / "processed" / f"{name}.jsonl", split_records)

    manifest = {
        "seed": args.seed,
        "ratio": {"train": 0.8, "validation": 0.1, "test": 0.1},
        "counts": {
            name: {
                "total": len(values),
                "fashion_recommendation": sum(
                    item["type"] == "fashion_recommendation" for item in values
                ),
                "tool_calling": sum(item["type"] == "tool_calling" for item in values),
                "ids": [item["id"] for item in values],
            }
            for name, values in splits.items()
        },
    }
    write_json(args.output_dir / "data" / "processed" / "split_manifest.json", manifest)

    report = {
        "status": "passed",
        "total": len(records),
        "unique_ids": len(set(ids)),
        "type_counts": Counter(record["type"] for record in records),
        "author_counts": Counter(record["author"] for record in records),
        "source_counts": source_counts,
        "look_counts": Counter(
            len(record["answer"]["looks"])
            for record in records
            if record["type"] == "fashion_recommendation"
        ),
        "tool_counts": Counter(
            step["tool_call"]["name"]
            for record in records
            if record["type"] == "tool_calling"
            for step in record["steps"]
        ),
        "warnings": [
            "README의 5 LOOK 변경 메모는 현재 가이드 및 80개 데이터의 3 LOOK 구조와 충돌함. Pilot은 현행 3 LOOK을 유지함.",
            "합성 데이터 500~1,000개가 없으므로 이번 결과는 최종 학습이 아닌 파이프라인 검증용 Pilot임.",
        ],
    }
    write_json(args.output_dir / "reports" / "validation_report.json", report)

    review_rng = random.Random(args.seed + 1)
    review_quota = {
        ("김진호", "fashion_recommendation"): 3,
        ("김진호", "tool_calling"): 1,
        ("곽준오", "fashion_recommendation"): 2,
        ("곽준오", "tool_calling"): 2,
        ("김서진", "fashion_recommendation"): 2,
        ("김서진", "tool_calling"): 2,
        ("김윤아", "fashion_recommendation"): 3,
        ("김윤아", "tool_calling"): 1,
    }
    reviewers = {"김진호": "곽준오", "곽준오": "김서진", "김서진": "김윤아", "김윤아": "김진호"}
    review_rows = []
    grouped = defaultdict(list)
    for record in records:
        grouped[(record["author"], record["type"])].append(record)
    for key, values in grouped.items():
        values = sorted(values, key=lambda item: item["id"])
        review_rng.shuffle(values)
        for record in values[: review_quota[key]]:
            review_rows.append(
                {
                    "id": record["id"],
                    "author": record["author"],
                    "reviewer": reviewers[record["author"]],
                    "type": record["type"],
                    "user_request": record["user_request"],
                    "schema_valid": "",
                    "request_understood": "",
                    "context_or_tool_valid": "",
                    "output_quality": "",
                    "decision": "",
                    "notes": "",
                }
            )
    review_rows.sort(key=lambda item: item["id"])
    review_path = args.output_dir / "reports" / "hitl_review_20pct.csv"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    with review_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(review_rows[0]))
        writer.writeheader()
        writer.writerows(review_rows)

    print(compact({"status": "passed", "records": len(records), "splits": expected_sizes, "hitl_sample": len(review_rows)}))


if __name__ == "__main__":
    main()
