/** 金額顯示：整數台幣，加千分位。 */
export function money(amount) {
  return `$${Number(amount).toLocaleString("zh-TW")}`;
}

/** 2026-09-01 → 09/01 */
export function shortDate(iso) {
  return iso.slice(5).replace("-", "/");
}

const taipeiDateTime = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

export function taipeiStamp(iso) {
  return taipeiDateTime.format(new Date(iso));
}

/** 舊版結算 API 回傳不含時區的 UTC 時間。 */
export function settlementStamp(iso) {
  const hasZone = /(?:Z|[+-]\d\d:\d\d)$/i.test(iso);
  return taipeiStamp(hasZone ? iso : `${iso}Z`);
}
