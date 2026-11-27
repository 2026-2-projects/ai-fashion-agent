"""Build and check the same ID-based, complete owned outfits for the Qwen path."""

from collections import defaultdict
from itertools import islice, product

from app.agent.contracts import AgentRecommendationRequest, FashionLook, OutfitItem
from app.agent.display_names import performance_base_kind
from app.agent.errors import InferenceResponseError
from app.agent.inference import wardrobe_only_requested
from app.agent.requirements import ItemCondition, color_name, kind_name, parse_constraints

REQUIRED_SLOTS = ("top", "bottom", "shoes")
OPTIONAL_SLOTS = ("outer", "accessory")


class WardrobeCandidates:
    def __init__(self, request: AgentRecommendationRequest, wardrobe: list[dict], preference: dict):
        self.constraints = parse_constraints(request.message, wardrobe)
        self.has_schedule = any((request.place, request.date, request.time))
        self.can_fill = (
            self.constraints.complete
            and (bool(self.constraints.items) or wardrobe_only_requested(request.message))
            and not self.has_schedule
        )
        self.by_id = {
            p["item_id"]: p for p in wardrobe if type(p.get("item_id")) is int and p["item_id"] > 0
        }
        disliked = {color_name(c) for c in preference.get("disliked_colors") or [] if c}
        self.eligible = {}
        for iid, p in self.by_id.items():
            slot, kind, color = (
                p["category"],
                kind_name(p.get("item_type")),
                color_name(p.get("color")),
            )
            if color in disliked or self.constraints.unverified:
                continue
            if all(c.allows(slot, kind, color) for c in self.constraints.items):
                self.eligible[iid] = slot
        self.required = (
            *REQUIRED_SLOTS,
            *(
                s
                for s in OPTIONAL_SLOTS
                if any(c.slot == s and not c.excluded for c in self.constraints.items)
            ),
        )
        self.examples = self._examples(self.eligible)

    def _examples(self, eligible: dict[int, str]) -> list[dict]:
        slots = defaultdict(list)
        for iid, slot in eligible.items():
            slots[slot].append(iid)
        # The contract needs at most two different complete combinations, including optional layers.
        complete = product(*(slots[s] for s in self.required))
        examples = [dict(zip(self.required, ids, strict=True)) for ids in islice(complete, 2)]
        if len(examples) == 1:
            for optional in OPTIONAL_SLOTS:
                if optional not in self.required and slots[optional]:
                    examples.append({**examples[0], optional: slots[optional][0]})
                    break
        return examples

    @staticmethod
    def _performance_uncertain(item: dict, condition: ItemCondition) -> bool:
        slot = item["category"]
        if slot != condition.slot:
            return False
        if not condition.excluded:
            return True
        color = color_name(item.get("color"))
        if color and condition.color and color != condition.color:
            return False
        # A registered loafer rules out an excluded waterproof sandal. An
        # ordinary sandal's name cannot establish whether it is waterproof.
        target = performance_base_kind(condition.kind, slot)
        actual = performance_base_kind(item.get("item_type"), slot)
        if not (target and actual):
            return True
        return actual == target or actual.endswith(" " + target) or target.endswith(" " + actual)

    def _accepts(self, combo: dict, eligible: dict[int, str]) -> bool:
        return all(s in combo for s in self.required) and all(
            eligible.get(iid) == slot for slot, iid in combo.items()
        )

    def _registered_piece(self, slot, iid) -> OutfitItem:
        source = self.by_id[iid]
        name = " ".join(filter(None, (source.get("color"), source.get("item_type")))) or slot
        return OutfitItem(slot=slot, item_id=iid, name=name)

    def _owned_look(self, template: FashionLook, combo: dict) -> FashionLook:
        pieces = [self._registered_piece(slot, iid) for slot, iid in combo.items()]
        return FashionLook(
            look_id=template.look_id,
            role=template.role,
            status="available",
            style="옷장 코디" if template.look_id == 4 else "옷장 대안 코디",
            items=pieces,
            reason="등록된 품목을 조합했습니다.",
        )

    def reconcile(
        self,
        looks: list[FashionLook],
        *,
        contextual: bool = False,
        unverified_performance: tuple[ItemCondition, ...] = (),
    ) -> tuple[list[FashionLook], list[dict]]:
        """Retain valid model choices first. Fill gaps only if inventory can prove feasibility."""
        # Leave source integrity errors to AgentService, even if the offending LOOK would disappear.
        owned = looks[3:]
        for look in owned:
            for piece in look.items:
                if (
                    self.by_id.get(piece.item_id, {}).get("category") != piece.slot
                    or piece.image_url is not None
                ):
                    return looks, []

        uncertain = set()
        eligible = self.eligible
        examples = self.examples
        if unverified_performance:
            uncertain = {
                iid
                for iid, item in self.by_id.items()
                if any(self._performance_uncertain(item, c) for c in unverified_performance)
            }
            eligible = {iid: slot for iid, slot in self.eligible.items() if iid not in uncertain}
            examples = self._examples(eligible)

        choices = []
        used = []
        for look in owned:
            combo = {piece.slot: piece.item_id for piece in look.items}
            if look.status == "available" and self._accepts(combo, eligible):
                if combo in used:
                    if not self.can_fill and not self.constraints.items:
                        return looks, []  # Preserve the existing duplicate-outfit error.
                    continue
                choices.append(look)
                used.append(combo)
        if self.has_schedule or contextual:
            # Inventory proves these IDs can form an outfit. Weather and calendar
            # tools supply facts, but no owned-outfit rule certifies contextual fit.
            if len(choices) < 2 and any(combo not in used for combo in examples):
                raise InferenceResponseError(
                    "옷장에 남은 조합이 요청 상황에 적합한지 확인할 수 없습니다."
                )
        elif self.can_fill:
            for combo in examples:
                if len(choices) == 2:
                    break
                if combo not in used:
                    choices.append(self._owned_look(owned[len(choices)], combo))
                    used.append(combo)

        result = list(looks[:3])
        changes = []
        for index, original in enumerate(owned):
            if index < len(choices):
                updated = choices[index].model_copy(
                    update={"look_id": original.look_id, "role": original.role}
                )
            else:
                updated = original.model_copy(
                    update={"status": "unavailable", "style": None, "items": []}
                )
            if updated.items and self.constraints.items:
                # A model-supplied display name must not relabel the selected registered ID.
                updated = updated.model_copy(
                    update={
                        "items": [
                            self._registered_piece(piece.slot, piece.item_id)
                            for piece in updated.items
                        ]
                    }
                )
            before = {p.slot: p.item_id for p in original.items}
            after = {p.slot: p.item_id for p in updated.items}
            if original.status != updated.status or before != after:
                if self.constraints.unverified or uncertain.intersection(before.values()):
                    why = "unverified_constraint"
                elif original.status == "unavailable":
                    why = "eligible_outfit_omitted"
                elif not self._accepts(before, eligible):
                    why = "ineligible_registered_selection"
                else:
                    why = "distinct_outfit_or_role"
                changes.append(
                    {"look_id": original.look_id, "cause": why, "status": updated.status}
                )
            elif [p.name for p in original.items] != [p.name for p in updated.items]:
                changes.append(
                    {
                        "look_id": original.look_id,
                        "cause": "registered_item_label",
                        "status": updated.status,
                    }
                )
            result.append(updated)
        return result, changes
