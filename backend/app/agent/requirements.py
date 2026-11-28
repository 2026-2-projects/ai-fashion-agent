"""Bounded Korean item constraints for owned outfits. Only registered attributes are provable."""

import re
import unicodedata
from dataclasses import dataclass

from app.agent.contracts import WARDROBE_SLOTS
from app.agent.inference import WARDROBE_ONLY_KEYWORDS


def normalized(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def aliases(groups: tuple[str, ...]) -> dict[str, str]:
    return {word: group.split("|")[0] for group in groups for word in group.split("|")}


COLORS = aliases(
    (
        "흰색|흰|하얀|하양|화이트|white",
        "검정|검정색|검은색|검은|검은빛|블랙|black",
        "갈색|브라운|brown",
        "네이비|남색|navy",
        "빨강|빨강색|빨간색|빨간|적색|레드|red",
        "파랑|파란색|파란|블루|blue",
        "초록|녹색|초록색|그린|green",
        "회색|그레이|grey|gray",
        "노랑|노란색|노란|옐로|yellow",
        "보라|보라색|퍼플|purple",
        "베이지|beige",
        "아이보리|ivory",
        "분홍|분홍색|핑크|pink",
        "주황|주황색|오렌지|orange",
        "차콜|charcoal",
        "올리브|olive",
        "청록|청록색|teal",
        "연보라|라벤더|lavender",
    )
)
# Include common items even when none are registered. New registered type names work verbatim.
KINDS = {
    "top": ("셔츠|shirt", "티셔츠|t-shirt", "니트|스웨터|sweater", "블라우스|blouse", "후드티"),
    "bottom": (
        "슬랙스|slacks",
        "청바지|데님 팬츠|jeans",
        "치노 팬츠|치노",
        "스커트|치마|skirt",
        "반바지|쇼츠|shorts",
        "바지|팬츠|pants",
    ),
    "shoes": (
        "부츠|부트|boots|boot",
        "첼시 부츠|첼시부츠",
        "앵클 부츠|앵클부츠",
        "스니커즈|스니커|운동화|sneakers|sneaker",
        "로퍼|loafers|loafer",
        "샌들|sandals",
        "더비화|더비 슈즈",
        "구두",
        "플랫슈즈",
    ),
    "outer": ("재킷|자켓|jacket", "코트|coat", "패딩", "가디건|카디건|cardigan"),
    "accessory": ("모자|hat", "머플러|목도리|scarf", "가방|bag", "벨트|belt"),
}
KIND_ALIASES = {alias: name for group in KINDS.values() for alias, name in aliases(group).items()}


def color_name(value: object) -> str:
    name = normalized(value)
    return COLORS.get(name, name)


def kind_name(value: object) -> str:
    name = normalized(value)
    return KIND_ALIASES.get(name, name)


@dataclass(frozen=True)
class ItemCondition:
    slot: str | None
    kind: str = ""
    color: str = ""
    excluded: bool = False

    def allows(self, slot: str, kind: str, color: str) -> bool:
        if self.slot is not None and self.slot != slot:
            return True
        if (self.kind and not kind) or (self.color and not color):
            return False
        matches_kind = not self.kind or kind == self.kind or kind.endswith(" " + self.kind)
        matches = matches_kind and (not self.color or color == self.color)
        return not matches if self.excluded else matches


# Match whole item clauses. Unknown modifiers must never be discarded to make a match.
PARTICLE = r"(?:으로|로|을|를|은|는|이|가|도)?"
END = r"(?:\s*(?:해요?|야|예요|이에요|입니다|이야|돼요?|된다|합니다|한다))?"
ONLY = (
    r"만\s*(?:(?:신을|입을|쓸|들|맬|착용할|사용할)\s*수\s*있(?:어|어요|습니다)|"
    r"신어|입어|써|착용해|사용해|골라)"
)
MUST = re.compile(
    rf"(?P<item>.+?){PARTICLE}\s*(?:(?:모두\s*|꼭\s*|반드시\s*)?"
    rf"(?:{ONLY}|필수(?:적)?|포함(?:시켜|해|해야)?|넣어|착용해야|신어야|입어야|써야|매야|들어야|"
    rf"사용해야|(?:이|여|어)야|이어야|아니면\s*안){END}|빼지\s*마(?:세요)?)$"
)
EXCLUDE = re.compile(
    rf"(?P<item>.+?){PARTICLE}\s*(?:제외(?:해)?|빼|없이|빼고|피해|금지|빼야|피하고\s*싶어|"
    rf"원하지\s*않아|안\s*(?:신어|입어|써)|"
    rf"(?:신을|입을|쓸|사용할)\s*수\s*없(?:어|어요)|(?:신|입|쓰|착용하)지\s*(?:마|말아)){END}$"
)
NOT_REQUIRED = re.compile(
    r"(?:필수(?:는|가|까지는|인\s*(?:것은|건))?\s*(?:아니|아냐|아님)|"
    r"(?:해야\s*(?:하는|할)\s*(?:건|것은)|필요(?:는|가)?)\s*(?:없|아니)|"
    r"(?:신지|입지|쓰지|착용하지)\s*않아도\s*(?:돼|괜찮))"
)
SOFT = re.compile(r"선호|좋아|좋겠|면\s*좋")
HARD = re.compile(
    r"필수|반드시|꼭|제외|금지|빼|말고|없이|피해|만\s*(?:신|입|쓰|사용|착용)|(?:이어|여|신어|입어|해|써|어)야|수\s*없|지\s*(?:마|말)"
)
# Remove only the ordinary request framing. Keep the item verb and its negation intact.
WARDROBE_FRAME = re.compile(
    "(?:" + "|".join(map(re.escape, WARDROBE_ONLY_KEYWORDS)) + r")\s*"
    r"(?:(?:써서|써(?=\s|$)|사용해서|활용해서)\s*)?(?:입을\s*수\s*있는\s*)?"
)
# Sourcing from one's wardrobe does not disable generic LOOKs or establish occasion fit.
OWNED_SOURCE = re.compile(
    r"^(?:내|제|보유한|등록된)\s+옷(?:으로|을\s*(?:써서|사용해서|활용해서))\s*"
)
REQUEST_FRAME = re.compile(
    r"(?:코디해|(?:코디|옷차림|조합)(?:를|을)?\s*(?:추천해|골라)?|추천해|골라)\s*"
    r"(?:줘요?|주세요)?\s*$"
)
SLOT_PREFIX = re.compile(r"^(상의|하의|신발|아우터|액세서리)(?:은|는|로는|으로는)\s*")


@dataclass(frozen=True)
class Constraints:
    items: tuple[ItemCondition, ...]
    unverified: bool
    complete: bool
    wardrobe_requested: bool


def _item(phrase, restricted_slot, catalog, colors, excluded):
    words = phrase.strip().split()
    color = colors.get(words[0], "") if words else ""
    name = " ".join(words[1:] if color else words)
    if name in WARDROBE_SLOTS:
        slot, kind = WARDROBE_SLOTS[name], ""
    elif not name and color:
        slot, kind = restricted_slot, ""
    else:
        kind = kind_name(name)
        slots = catalog.get(kind, set())
        if restricted_slot:
            slots = slots.intersection({restricted_slot})
        if len(slots) != 1:
            return None
        slot = next(iter(slots))
    if (restricted_slot and slot != restricted_slot) or (slot is None and not excluded):
        return None
    return ItemCondition(slot, kind, color, excluded)


def parse_constraints(message: str, inventory: list[dict]) -> Constraints:
    colors = dict(COLORS)
    catalog: dict[str, set[str]] = {}
    for slot, group in KINDS.items():
        for kind in aliases(group).values():
            catalog.setdefault(kind, set()).add(slot)
    for item in inventory:
        color = normalized(item.get("color"))
        if color:
            colors.setdefault(color, color_name(color))
        kind = kind_name(item.get("item_type"))
        if kind:
            catalog.setdefault(kind, set()).add(item["category"])

    text = normalized(message)
    wardrobe_requested = bool(WARDROBE_FRAME.search(text) or OWNED_SOURCE.match(text))
    # Split coordinated requirements without treating alternatives as conjunctions.
    text = re.sub(r"필수(?:이고|고|이며|이고요)\s*", "필수. ", text)
    text = re.sub(r"(?:제외하고|말고)(?:\s+|(?=[.!?,;]|$))", " 제외. ", text)
    conditions: list[ItemCondition] = []
    other_slots = set()
    unknown = False
    complete = True
    for part in re.split(r"[.!?~,;\n]+|\s+그리고\s+|지만\s+", text):
        clause = WARDROBE_FRAME.sub(" ", part).strip()
        clause = REQUEST_FRAME.sub("", OWNED_SOURCE.sub("", clause)).strip()
        clause = re.sub(r"\s*(?:줘요?|주세요)$", "", clause).strip()
        if not clause:
            continue
        negated = NOT_REQUIRED.search(clause)
        if negated and not HARD.search(clause[negated.end() :]):
            continue
        scope = SLOT_PREFIX.match(clause)
        slot = WARDROBE_SLOTS[scope[1]] if scope else None
        if scope:
            clause = clause[scope.end() :]
        emphatic = bool(re.search(r"(?:반드시|꼭)", clause))
        clause = re.sub(r"^(?:반드시|꼭)\s*", "", clause)
        other = re.fullmatch(
            r"다른\s*(상의|하의|신발|아우터|액세서리)(?:은|는)?\s*(?:빼|제외해?)", clause
        )
        if other:
            other_slots.add(WARDROBE_SLOTS[other[1]])
            continue
        exclusion = EXCLUDE.fullmatch(clause)
        match = exclusion or MUST.fullmatch(clause)
        if not match and emphatic:
            match = re.fullmatch(
                rf"(?P<item>.+?){PARTICLE}\s*(?:반드시|꼭)?\s*(?:신어|입어|써|착용해)", clause
            )
        if match:
            for phrase in re.split(r"(?:와|과)\s+|\s+및\s+", match["item"]):
                condition = _item(phrase, slot, catalog, colors, bool(exclusion))
                if condition is None:
                    unknown = True
                else:
                    conditions.append(condition)
        elif HARD.search(part):
            unknown = True
        elif not SOFT.search(clause):
            complete = False
    required_slots = {c.slot for c in conditions if not c.excluded}
    unknown |= not other_slots.issubset(required_slots)
    return Constraints(tuple(conditions), unknown, complete and not unknown, wardrobe_requested)
