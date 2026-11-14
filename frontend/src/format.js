/** 金額顯示：整數台幣，加千分位。 */
export function money(amount) {
  return `$${Number(amount).toLocaleString("zh-TW")}`;
}

/** 2026-09-01 → 09/01 */
export function shortDate(iso) {
  return iso.slice(5).replace("-", "/");
}

/** 2026-09-01T14:03:22 → 2026/09/01 14:03 */
export function stamp(iso) {
  return iso.slice(0, 16).replace("T", " ").replaceAll("-", "/");
}
