# Trove 二手商品淘手交易 Agent

Trove 的名字取自“宝藏、珍品”，对应“在二手市场淘到宝”的感觉：短、好读、好记。

Trove 是一个帮你 **搜寻买入后可盈利转卖的二手商品**，并通过 **对话聊天谈价**、最后 **交给你本人付款完成交易** 的 Agent。

## 核心能力

- **搜索与筛选**：按你的需求在二手平台搜索，优先个人闲置，支持排序、价格区间、区域等过滤，并翻页浏览。
- **评估**：从可盈利性（预计净利润和 ROI）和可行度（卖家可信、描述与实拍一致、风险可控）两个维度做判断，给出依据。
- **谈价**：进入聊天与卖家礼貌议价，朝你的心理价位推进，并记录关键信息。
- **交接**：输出候选清单与建议，由你最终拍板；付款、下单、收货地址、退款等操作一律由你本人完成。

## 目录结构

```
Trove/
├── README.md                    # 项目说明（本文件）
├── AGENTS.md                    # Agent 工作守则（给 Codex 会话用）
├── .gitignore
├── templates/
│   ├── search-checklist.md      # 搜索任务清单模板
│   └── deal-record.md           # 成交记录模板
└── records/
    ├── search/                  # 搜索记录
    ├── negotiation/             # 谈价记录
    └── deals/                   # 成交记录
```

## 快速开始

直接对 Trove 描述你想淘什么即可，例如：

> 帮我在闲鱼找一台 256G 的 iPhone 13，预算 2500 以内，成色好一点，优先同城面交。

Trove 会先和你确认关键条件，然后开始搜索、筛选、评估，必要时进入聊天谈价，最后把候选和报价交给你决定。

## 使用边界

- Trove 只负责搜索、评估、谈价和汇报，**不会代替你付款、下单、确认收货或转账**。
- 涉及支付密码、验证码、收货地址等隐私信息，只在必要环节且经你明确同意后使用。
- 默认建议走平台内交易，避免私下转账和不明链接。

## 平台

数据源平台由 [config/platforms.json](config/platforms.json) 配置，当前默认启用闲鱼（Xianyu）。浏览与数据采集用 Codex browser-use 接管当前平台已登录的页面，遵循本机 `browser-use-existing-page` skill 的约定；新增平台只需在配置里加一条并切换 `active_platform`。

## 购买策略

买入决策由 [config/acquisition_policy.json](config/acquisition_policy.json) 配置，当前只启用 `resale_profit`（可盈利转卖）模式，后续可扩展 `personal_use`（自用）模式。计算公式和门槛在 [scripts/acquisition_policy.py](scripts/acquisition_policy.py) 中维护，买入前会把卖出快递、包材、平台费和风险准备金从预计卖出价里扣除。

谈价跟进采用“一个 listing 一个独立线程”，由 [scripts/negotiation_due_scheduler.py](scripts/negotiation_due_scheduler.py) 按每条记录的 `thread_id` 在到期时唤醒对应线程；每日采集/聚合等非谈价任务仍使用 `config/negotiation_scheduler.json` 里的 fallback 线程。
