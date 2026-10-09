#!/usr/bin/env node
/** Convert an offset-aware Gregorian datetime to Chinese lunar date using ICU. */

const argv = process.argv.slice(2);

function arg(name) {
  const index = argv.indexOf(name);
  if (index === -1 || index + 1 >= argv.length) {
    throw new Error(`缺少参数 ${name}`);
  }
  return argv[index + 1];
}

const datetime = arg("--datetime");
const timeZone = arg("--timezone");

if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(datetime)) {
  throw new Error("datetime 必须带 Z 或时区偏移，例如 2026-09-21T18:35:00+08:00");
}

const instant = new Date(datetime);
if (Number.isNaN(instant.getTime())) {
  throw new Error(`无法解析时间：${datetime}`);
}

const lunarFormatter = new Intl.DateTimeFormat("zh-CN-u-ca-chinese", {
  timeZone,
  year: "numeric",
  month: "long",
  day: "numeric",
});
const clockFormatter = new Intl.DateTimeFormat("en-GB", {
  timeZone,
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

const lunarParts = Object.fromEntries(
  lunarFormatter.formatToParts(instant).map(({ type, value }) => [type, value]),
);
const clockParts = Object.fromEntries(
  clockFormatter.formatToParts(instant).map(({ type, value }) => [type, value]),
);

const rawMonth = lunarParts.month;
const isLeapMonth = rawMonth.startsWith("闰");
const monthName = rawMonth.replace(/^闰/, "");
const monthNumbers = {
  正月: 1,
  一月: 1,
  二月: 2,
  三月: 3,
  四月: 4,
  五月: 5,
  六月: 6,
  七月: 7,
  八月: 8,
  九月: 9,
  十月: 10,
  十一月: 11,
  十二月: 12,
  腊月: 12,
};
const lunarMonth = monthNumbers[monthName];
if (!lunarMonth) {
  throw new Error(`无法识别农历月份：${rawMonth}`);
}

const localHour = Number(clockParts.hour);
const hourBranchNumber = localHour === 23 || localHour === 0
  ? 1
  : Math.floor((localHour + 1) / 2) + 1;
const branches = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"];

const result = {
  method: "ICU Chinese calendar conversion",
  input: { datetime, timezone: timeZone },
  lunar: {
    year: Number(lunarParts.relatedYear),
    year_name: lunarParts.yearName ?? null,
    month: lunarMonth,
    month_name: rawMonth,
    is_leap_month: isLeapMonth,
    day: Number(lunarParts.day),
  },
  local_clock: {
    hour: localHour,
    minute: Number(clockParts.minute),
    hour_branch: branches[hourBranchNumber - 1],
    hour_branch_number: hourBranchNumber,
  },
};

console.log(JSON.stringify(result, null, 2));
