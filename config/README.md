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

周度自动更新：每周日 22:00 运行 `scripts/update_pricing.py`，读取最近 30 天 `records/market/*.json`，按风险档门槛（样本数与观察天数）用个人卖家样本的 P25/P75 更新参考价、用 P25 更新好价线；同时把已售样本的 `sold_median` / `sold_p25` 等退出价指标写回 `records/market/stats/`；样本不足则保持原值。

## 购买策略参数（acquisition_policy.json）

`acquisition_policy.json` 决定“什么价格可以买”。当前只实现 `resale_profit`（可盈利转卖）模式，后续可新增 `personal_use`（自用）而不改动触发器。

- `active_mode`：当前启用的模式，目前固定为 `resale_profit`。
- `modes.resale_profit.min_net_profit`：每单最低净利润（元）。
- `modes.resale_profit.min_roi_pct`：相对全包买入成本的最低净利率（%）。
- `modes.resale_profit.risk_reserve_pct` / `risk_reserve_min`：风险准备金，按预计卖出价的百分比，并设有最低值。
- `modes.resale_profit.platform_fee_pct`：卖出平台/服务费百分比；闲鱼目前先设为 0，变化时改这里。
- `modes.resale_profit.listing_estimate_pct`：没有足够已售样本时，用挂牌中位数乘以该比例估算退出价。
- `modes.resale_profit.min_sold_comps`：可信退出价所需的最少已售样本数。
- `modes.resale_profit.allow_estimated_exit`：是否允许在已售样本不足时使用挂牌价估算退出价；启用时置信度为 `low`。
- `modes.resale_profit.auto_trigger_min_confidence`：允许自动创建谈价 draft 的最低退出价置信度；默认 `high`，低置信度只 watch、需人工复核。
- `cost_profiles`：按品类配置卖出快递、包材和未明示时的默认买入邮费。

计算模块位于 `scripts/acquisition_policy.py`，只做纯计算，不读写文件。买入决策输出预计净利润、ROI、最高全包买入成本和最高商品价，供触发器和谈价档案使用。

## 谈价触发参数（negotiation_trigger.json）

每次市场采集成功后，`scripts/negotiation_trigger.py` 对当日结果做一次首次谈价评审。该配置控制：

- `max_listing_price`：首谈商品的单件价格上限。
- `first_offer_discount_pct`：生成 draft 时的初始报价折让，实时复核后可调整。
- `allowed_seller_types`：允许首谈的卖家类型。
- `reject_flags` / `reject_text_patterns`：直接排除的风险标签和描述。
- `active_slots`：按 `safe` / `medium` / `high` 风险档限制同时进行的谈价数。
- `same_model_slots`：同一型号的最大 active 谈价数。

触发资格严格以 `records/market/stats/*.json` 的 `status=ready` 为准。只有 3 天数据、样本不足或观察跨度不足的型号只进入观察，不得创建谈价。

## 逐商品谈价调度（negotiation_scheduler.json）

调度器按 `records/negotiation/index.json` 中每条记录的 `thread_id` 分组投递：一个 listing 一个独立线程，到期后向该线程 `codex queue`。旧记录没有 `thread_id` 时，退回 `negotiation_scheduler.json` 里的 `thread_id` 作为 fallback。

- `thread_id`：fallback 线程 id，通常用于每日采集/聚合等非谈价任务。
- `active_window`：允许唤醒的时间段。
- `retry_failed_after_minutes`：投递失败后的重试间隔。
- `repeat_unprocessed_after_minutes`：投递成功但尚未处理的重复提醒间隔。

新建独立谈价线程时，用状态脚本把线程 id 绑定到档案：

```bash
python3 .codex/skills/price-negotiation/scripts/negotiation_state.py set-thread <listing-id> <thread-id>
```
