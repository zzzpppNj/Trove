# 选品数据 schema（records/market/）

每日选品结果按 `records/market/YYYY-MM-DD.json` 保存；聚合结果写 `records/market/stats/`。

## 每日文件结构

```json
{
  "date": "2026-10-22",
  "source": "xianyu",
  "records": []
}
```

`source` 使用平台 id（见 `config/platforms.json`），当前默认 `xianyu`（闲鱼）。

## 记录字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | string | 平台商品 id（闲鱼为 item id），用于跨日去重；历史记录早期为日期序号，去重时同时解析 `url` 中的 id |
| category | string | 品类，见下方枚举 |
| brand | string | 品牌 |
| model | string | 型号，必须具体到可比型号 |
| title | string | 商品标题 |
| listing_price | number | 挂牌价（元） |
| shipping_included | boolean\|null | 是否包邮；未确认时记 null |
| shipping_cost_in | number\|null | 卖家另收的买入邮费（元），不包邮且已知时填写 |
| condition | string | 新旧程度 |
| seller_type | string | personal / suspected_reseller / unknown |
| region | string | 地区 |
| url | string | 商品链接 |
| face_to_face | boolean | 是否支持面交（仅限用户所在城市合肥） |
| platform_inspection | boolean | 是否支持平台验货/验机（如闲鱼验机） |
| flags | string[] | 标记，如“疑似矿卡”“来源不清”“低于行情” |
| sold | boolean | 是否已售；用于聚合真实成交价 |
| sold_price | number\|null | 已售成交价（元），仅 sold=true 时有效 |
| listed_at | string\|null | 上架时间，ISO 日期或日期时间 |
| sold_at | string\|null | 售出时间，ISO 日期或日期时间 |
| notes | string | 备注 |

## 枚举

- category：图书绘本游戏卡带 / 二手显示器 / 相机定焦镜头 / 游戏机主机 / 迷你主机老款整机 / 二手手机 / 母婴健身乐器
- seller_type：personal（个人卖家）、suspected_reseller（疑似二道贩子）、unknown（无法判断）
- condition：尽量统一到“全新 / 99新 / 95新 / 9成新 / 8成新 / 有瑕疵”六档，细节写进 notes

## 聚合口径（算“市场平均二手价格”）

- 分组维度：brand + model。
- 计算前先剔除 flags 含“疑似矿卡 / 来源不清 / 问题机”的记录。
- 指标：样本数、时间跨度（天）、中位数、P25、P75、最小值、最大值；个人卖家与全体分别给中位数。
- 参考市场价优先用个人卖家中位数；样本不足时用全体中位数并在 notes 注明。
- 挂牌价不等于成交价：估算成交价可按挂牌价中位数 × 0.85–0.95；有“已售 / 成交”信息优先采信。
- 好价：挂牌价 ≤ 参考市场价区间下限（约 P25），且通过风险检查。
- 已售样本（`sold=true` 且有 `sold_price`）额外聚合 `sold_sample_count`、`sold_median`、`sold_p25`、`sold_p75`、`sold_span_days`；有真实成交时优先作为退出价基准。
- 可盈利转卖模式的买入决策由 `config/acquisition_policy.json` 和 `scripts/acquisition_policy.py` 计算，不直接使用 `good_price_line`。

## 单条记录示例

```json
{
  "date": "2026-10-22",
  "source": "闲鱼",
  "records": [
    {
      "id": "2026-10-22-001",
      "category": "相机定焦镜头",
      "brand": "佳能",
      "model": "EF 50mm f/1.8 STM",
      "title": "佳能小痰盂 50 1.8 自用",
      "listing_price": 450,
      "shipping_included": true,
      "shipping_cost_in": null,
      "condition": "9成新",
      "seller_type": "personal",
      "region": "上海",
      "url": "https://example.com/item/123",
      "face_to_face": true,
      "platform_inspection": false,
      "flags": [],
      "sold": false,
      "sold_price": null,
      "listed_at": "2026-10-21",
      "sold_at": null,
      "notes": "带前后盖，无霉无划痕"
    }
  ]
}
```

## 聚合结果文件（可选）

`records/market/stats/<brand>-<model>.json`：

```json
{
  "brand": "佳能",
  "model": "EF 50mm f/1.8 STM",
  "category": "相机定焦镜头",
  "updated_at": "2026-10-22",
  "sample_count": 23,
  "time_span_days": 14,
  "personal_median": 420,
  "overall_median": 440,
  "p25": 400,
  "p75": 470,
  "fair_price_range": [400, 470],
  "sold_sample_count": 12,
  "sold_median": 395,
  "sold_p25": 380,
  "sold_p75": 420,
  "sold_span_days": 21,
  "status": "ready",
  "notes": ""
}
```

`status` 取值：ready（样本达标，可谈价）/ insufficient（样本不足）。
