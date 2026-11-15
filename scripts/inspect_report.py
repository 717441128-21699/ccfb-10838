import json

r = json.load(open("data/demo_report.json", encoding="utf-8"))
print(f"{'table':<22}{'source':>8}{'seed':>7}{'closure+':>10}{'kept':>8}{'pct':>8}")
for t in r["tables"]:
    if t["extracted_rows"] == 0:
        continue
    print(f"{t['table']:<22}{t['source_rows']:>8}{t['seed_rows']:>7}"
          f"{t['closure_added']:>10}{t['extracted_rows']:>8}"
          f"{t['percent']:>7.1f}%")

print("\n校验:", r["validation"]["zero_error"],
      "| FK错误:", r["validation"]["foreign_key_errors"],
      "| 格式错误:", r["validation"]["format_errors"])
print("日期平移:", r["date_shift_days"], "天")

# 种子表的 seed_rows 应反映 WHERE 命中数, closure_added 反映被其他关系带回的
cust = next(t for t in r["tables"] if t["table"] == "customers")
print(f"\ncustomers: WHERE 命中种子 {cust['seed_rows']} 行, "
      f"闭包额外带入 {cust['closure_added']} 行")
