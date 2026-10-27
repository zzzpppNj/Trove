# 平台配置

Trove 的数据源平台由 `platforms.json` 配置，不在代码里写死。

## 字段

- `active_platform`：当前启用的平台 id（默认 `xianyu`）。
- `platforms[]`：
  - `id`：平台唯一标识，用于选品记录的 `source` 字段。
  - `name`：展示名。
  - `enabled`：是否启用。
  - `default`：是否为默认平台。
  - `home_url` / `search_url_template` / `item_url_prefix`：首页与搜索 URL 模板，`{keyword}` 是关键词占位符。
  - `auth_mode`：登录方式，当前统一为 `reuse-existing-page`（接管用户已登录页面）。
  - `login_note`：登录说明。
  - `default_filters`：搜索时默认勾选的过滤项。
  - `currency`：币种。
  - `notes`：备注。

## 新增一个平台

1. 在 `platforms` 数组里加一个对象，填好 `id` / `name` / URL 模板与 `default_filters`。
2. 把 `active_platform` 切到新 id，或让采集时按需选择平台。
3. 在 `records/market/schema.md` 里确认该 id 可作为 `source` 取值。
4. 采集时用 `browser-use-existing-page` 接管该平台已登录的页面。

## 定价参数（pricing.json）

`pricing.json` 维护每个盯盘型号的 `reference_price`（参考价区间）、`good_price_line`（好价线）、`risk_tier`（风险档）与 `frequency`（采集频率）。这些值会随行情低频波动，更新时直接改该文件并 `updated_at`，不必改动采集逻辑或 watchlist。

周度自动更新：每周日 22:00 运行 `scripts/update_pricing.py`，读取最近 30 天 `records/market/*.json`，按风险档门槛（样本数与观察天数）用个人卖家样本的 P25/P75 更新参考价、用 P25 更新好价线；样本不足则保持原值。

## 谈价触发参数（negotiation_trigger.json）

每次市场采集成功后，`scripts/negotiation_trigger.py` 对当日结果做一次首次谈价评审。该配置控制：

- `max_listing_price`：首谈商品的单件价格上限。
- `minimum_discount_pct`：低于公允下限的最低折让。
- `first_offer_discount_pct`：生成 draft 时的初始报价折让，实时复核后可调整。
- `allowed_seller_types`：允许首谈的卖家类型。
- `reject_flags` / `reject_text_patterns`：直接排除的风险标签和描述。
- `active_slots`：按 `safe` / `medium` / `high` 风险档限制同时进行的谈价数。
- `same_model_slots`：同一型号的最大 active 谈价数。

触发资格严格以 `records/market/stats/*.json` 的 `status=ready` 为准。只有 3 天数据、样本不足或观察跨度不足的型号只进入观察，不得创建谈价。
