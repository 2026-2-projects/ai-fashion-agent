"""Score saved cases against their independent fixture expectations; make no inference calls."""

import argparse
import json
from pathlib import Path

from app.agent.contracts import AgentDraft, normalize_wardrobe_slot

# Colour spellings in the synthetic fixtures. These checks do not use the production resolver.
COLORS = {
    "빨강": ("빨강", "빨간", "레드", "red"),
    "네이비": ("네이비", "남색", "navy"),
    "주황": ("주황", "오렌지", "orange"),
    "black": ("검정", "검은", "블랙", "black"),
}


def score(row, looks):
    if looks is None:
        return {"assessable": False, "pass": False}
    try:
        AgentDraft.model_validate(
            {"context_summary": "synthetic", "looks": looks}, strict=True
        )
        valid_contract = True
    except ValueError:
        valid_contract = False
    inventory = {v["item_id"]: v for v in row["provided_facts"]["get_wardrobe"]}
    preference = row["provided_facts"]["get_user_context"].get("preference") or {}
    disliked = preference.get("disliked_colors") or []
    refs = {frozenset(combo) for combo in row.get("eligible_outfits", [])}
    invalid = []
    ownership = []
    color_errors = []
    duplicates = []
    used = set()
    statuses = [look.get("status") for look in looks]
    if len(statuses) != 5:
        return {
            "assessable": True,
            "pass": False,
            "structural": False,
            "statuses": statuses,
        }
    for n, look in enumerate(looks, 1):
        if look["status"] != "available":
            continue
        items = look["items"]
        for item in items:
            if n < 4:
                if item.get("item_id") is not None:
                    ownership.append(n)
                color_text = item["name"].casefold()
            else:
                registered = inventory.get(item.get("item_id"))
                if (
                    not registered
                    or normalize_wardrobe_slot(registered.get("category"))
                    != item["slot"]
                ):
                    ownership.append(n)
                    continue
                color_text = registered["color"].casefold()
            for c in disliked:
                if any(t in color_text for t in COLORS.get(c, (c,))):
                    color_errors.append(n)
        if n < 4:
            continue
        ids = frozenset(i.get("item_id") for i in items)
        combo = frozenset((i["slot"], i.get("item_id")) for i in items)
        if combo in used:
            duplicates.append(n)
        used.add(combo)
        if "eligible_outfits" in row:
            if ids not in refs:
                invalid.append(n)
        elif (
            row["case"].startswith("brown-boots-")
            or row["case"] == "white-sneakers-only"
        ):
            shoe = next((p for p in items if p["slot"] == "shoes"), {})
            actual = inventory.get(shoe.get("item_id"), {})
            expected = (
                ("갈색", "부츠")
                if row["case"].startswith("brown-boots-")
                else ("흰색", "운동화")
            )
            if (actual.get("color"), actual.get("type")) != expected:
                invalid.append(n)
        if (
            n == 4
            and row.get("expected_top") is not None
            and dict(combo) != {"top": row["expected_top"], "bottom": 773, "shoes": 774}
        ):
            invalid.append(n)
    rejected = [
        n
        for n, (a, e) in enumerate(zip(statuses, row["expected"], strict=True), 1)
        if a == "unavailable" and e == "available"
    ]
    offered = [
        n
        for n, (a, e) in enumerate(zip(statuses, row["expected"], strict=True), 1)
        if a == "available" and e == "unavailable"
    ]
    return {
        "assessable": True,
        "structural": valid_contract,
        "statuses": statuses,
        "unowned_or_wrong_slot": sorted(set(ownership)),
        "forbidden_color": sorted(set(color_errors)),
        "duplicate": duplicates,
        "ineligible_items": sorted(set(invalid)),
        "false_unavailable": rejected,
        "false_available": offered,
        "pass": valid_contract
        and not (
            ownership or color_errors or duplicates or invalid or rejected or offered
        ),
    }


def grade(record):
    row = record["input"]
    raw = score(row, record.get("model_original"))
    final = score(row, record.get("backend_final"))
    return {
        "case_id": record["case_id"],
        "job_id": record["job_id"],
        "case": row["case"],
        "expected_feasible": "available" in row["expected"][3:],
        "unverified": row.get("unverified", False),
        "error": record["error"],
        "seconds": record.get("seconds"),
        "finish": record.get("finish_reason"),
        "usage": record.get("usage"),
        "changes": record.get("corrections", []),
        "raw": raw,
        "final": final,
        "tools_match": record.get("called_tools") == list(row["provided_facts"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    for path in sorted(args.directory.glob("*.json")):
        record = json.loads(path.read_bytes())
        print(json.dumps(grade(record), ensure_ascii=False))


if __name__ == "__main__":
    main()
