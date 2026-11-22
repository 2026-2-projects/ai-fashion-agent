/** Conservative title-level filtering for unverified external shopping results.
 * Not image recognition. A visually incorrect product can still have a plausible title.
 * The original recommendation text remains visible even if its image is withheld.
 */
const normalize = text => String(text ?? "").normalize("NFKC").toLowerCase().replace(/[\s_\-/]+/g, " ");
const match = (text, pattern) => pattern.test(text);
const groups = [
  { requested: /로퍼|loafer/i, title: /로퍼|loafer|드라이빙 슈즈/i, wrong: /스니커즈|운동화|러닝화|슬리퍼|boots|부츠/i },
  { requested: /스니커즈|운동화|sneaker|로우탑|하이탑/i, title: /스니커즈|운동화|신발|스니커|sneaker|shoes|nike|adidas|컨버스|converse|low top|low\b/i, wrong: /로퍼|슬리퍼|샌들|boots|부츠|힐|펌프스/i },
  { requested: /코트|coat/i, title: /코트|coat/i, wrong: /베스트|vest|셔츠|티셔츠|바지|팬츠|스니커즈|기타|guitar/i },
  { requested: /자켓|재킷|점퍼|블루종|패딩|바람막이|jacket|outer|아우터/i, title: /자켓|재킷|점퍼|블루종|패딩|바람막이|jacket|coat|outer|윈드브레이커|jumper/i, wrong: /기타|guitar|베이스|반바지|팬츠|셔츠|신발/i },
  { requested: /후드티|후디|hoodie/i, title: /후드|후디|hood/i, wrong: /후드집업|zip\s?up|팬츠|신발|티셔츠/i },
  { requested: /니트\s*베스트|knit\s*vest/i, title: /니트\s*베스트|knit\s*vest|스웨터\s*베스트/i, wrong: /셔츠|팬츠|스니커즈|기타|guitar/i },
  { requested: /티셔츠|t\s?shirt|반팔/i, title: /티셔츠|t\s?shirt|반팔|tee\b/i, wrong: /바지|팬츠|재킷|로퍼|슬리브리스|민소매/i },
  { requested: /니트|스웨터|sweater|knit/i, title: /니트|스웨터|knit|sweater/i, wrong: /팬츠|바지|스니커즈|기타|guitar/i },
  { requested: /셔츠|남방|shirt/i, title: /셔츠|남방|shirt/i, wrong: /티셔츠|t\s?shirt|슬리브리스|민소매|sleeveless|원피스|dress|반바지|쇼츠|팬츠/i },
  { requested: /바지|팬츠|슬랙스|데님|청바지|조거|jogger|trousers|jeans|pants/i, title: /바지|팬츠|슬랙스|데님|청바지|조거|jogger|trousers|jeans|pants|denim/i, wrong: /반바지|하프\s*팬츠|쇼츠|shorts|bermuda|jorts|스커트|치마|skirt|원피스|dress|기타|guitar/i },
];
const colors = [
  [/블랙|검정|black/i,/블랙|검정|black/i],
  [/화이트|흰색|white|ivory|아이보리/i,/화이트|흰색|white|ivory|아이보리/i],
  [/차콜|charcoal|그레이|grey|gray|회색/i,/차콜|charcoal|그레이|grey|gray|회색/i],
  [/네이비|navy|인디고|indigo|블루|blue|청색/i,/네이비|navy|인디고|indigo|블루|blue|청색/i],
  [/베이지|beige|크림|cream/i,/베이지|beige|크림|cream/i],
  [/브라운|brown|갈색/i,/브라운|brown|갈색/i],
  [/올리브|olive|카키|khaki|그린|green/i,/올리브|olive|카키|khaki|그린|green/i],
];
/** @returns {boolean} false means 'do not show potentially mismatched image'. */
export function isPlausibleProductImage(name, title, slot) {
  if (typeof name !== "string" || !name.trim() || typeof title !== "string" || !title.trim()) return false;
  const n = normalize(name), t = normalize(title);
  if (/guitar|악기|기타\s*\(|전자기타|장난감|피규어|휴대폰|책|의자|가구|인테리어 소품|키링|식품|초콜릿|music man|stingray/i.test(t)) return false;
  const group = groups.find(g => g.requested.test(n));
  if (group && (!group.title.test(t) || group.wrong.test(t))) return false;
  if (!group && !/셔츠|티셔츠|코트|자켓|재킷|점퍼|니트|스웨터|조끼|베스트|팬츠|바지|슬랙스|데님|청바지|신발|운동화|스니커즈|로퍼|shirt|jacket|coat|pants|jeans|shoes|sneaker|knit|vest|tee\b/i.test(t)) return false;
  if ((/와이드|wide/i.test(n) && /슬림|스키니|skinny|slim\s?fit/i.test(t)) || (/롱|long/i.test(n) && /하프|shorts|반바지/i.test(t))) return false;
  if (slot === "bottom" && /상의|셔츠|티셔츠|재킷|아우터|스니커즈|신발/i.test(t) && !/팬츠|바지|슬랙스|데님|청바지|jeans|pants/i.test(t)) return false;
  if (slot === "shoes" && /팬츠|바지|티셔츠|재킷|아우터|코트/i.test(t) && !/신발|슈즈|sneaker|shoes|운동화|스니커즈/i.test(t)) return false;
  // Reject an explicitly different color only when the source title also contains a known color.
  const expected = colors.find(([regex]) => regex.test(n));
  if (expected) {
    const titleHasColor = colors.some(([re]) => re.test(t));
    if (titleHasColor && !expected[1].test(t)) return false;
  }
  return true;
}
