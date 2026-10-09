#!/usr/bin/env node
/**
 * Build lunar_table.json from ICU's Chinese calendar, so Python can convert
 * dates without Node (the packaged desktop app ships no Node runtime).
 *
 * One row per lunar month: [first Gregorian day "YYYY-MM-DD", related year,
 * year name, month number, is leap]. A Gregorian date's lunar date is the last
 * row starting on or before it; the day is the distance to that row + 1.
 *
 * Month boundaries are computed on the Asia/Shanghai calendar day, which is how
 * ICU's Chinese calendar defines them. Usage: node build_lunar_table.mjs > lunar_table.json
 */

const START = Date.UTC(1900, 0, 1), END = Date.UTC(2101, 0, 1), DAY = 86_400_000;
const formatter = new Intl.DateTimeFormat("zh-CN-u-ca-chinese", {
  timeZone: "UTC", year: "numeric", month: "long", day: "numeric",
});
const months = { 正月: 1, 一月: 1, 二月: 2, 三月: 3, 四月: 4, 五月: 5, 六月: 6,
  七月: 7, 八月: 8, 九月: 9, 十月: 10, 十一月: 11, 十二月: 12, 腊月: 12 };

const rows = [];
for (let t = START; t < END; t += DAY) {
  // Noon UTC of a civil date: the formatter reads that same civil date.
  const parts = Object.fromEntries(formatter.formatToParts(new Date(t + DAY / 2))
    .map(({ type, value }) => [type, value]));
  if (Number(parts.day) !== 1) continue;
  const leap = parts.month.startsWith("闰");
  rows.push([new Date(t).toISOString().slice(0, 10), Number(parts.relatedYear), parts.yearName,
    months[parts.month.replace(/^闰/, "")], leap]);
}
console.log(JSON.stringify({
  source: `ICU ${process.versions.icu} Chinese calendar via Node ${process.version}`,
  range: [rows[0][0], "2100-12-31"],
  months: rows,
}));
