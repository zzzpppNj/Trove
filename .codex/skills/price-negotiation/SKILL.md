---
name: price-negotiation
description: 生成二手交易（默认闲鱼）的谈价话术、报价边界和可恢复状态流程：口语化、有行情依据，并统一处理等待、还价、长时间未回复和交易交接。选品完成后需要联系卖家、持续跟踪会话或恢复谈价时使用。
---

# 二手谈价

在完成选品后，与卖家聊天谈价。目标是用自然、口语化的方式，以有依据的价格成交，而不是生硬压价。

## 必做流程

1. **确认门槛**：只有市场样本达到项目门槛的型号才能进入谈价。
2. **实时复核**：打开具体 listing，确认仍在售、价格未变、卖家和关键描述一致；已售商品直接结束。
3. **建档案**：从 [templates/negotiation-record.md](../../../templates/negotiation-record.md) 建立独立记录，写明市场价、首报、目标和最高可接受价。
4. **生成待确认消息**：先问在售、成色、配件和关键功能，再报首价。对外发送前把最终原文交给用户确认。
5. **发送后迁移状态**：发送消息后才进入 `awaiting_reply`；收到卖家回复后使用状态脚本更新档案。
6. **交接而非成交**：价格和条件明确后交给用户决定。下单、付款、地址和售后始终由用户本人处理。

## 状态机

谈价状态统一使用英文机器值，记录在 Markdown 字段 `- 谈价状态：<status>` 中。可用状态和合法迁移见 [references/negotiation-sop.md](references/negotiation-sop.md)。

状态操作优先使用脚本，避免手工改错：

```bash
python3 .codex/skills/price-negotiation/scripts/negotiation_state.py validate
python3 .codex/skills/price-negotiation/scripts/negotiation_state.py list --active-only
python3 .codex/skills/price-negotiation/scripts/negotiation_state.py transition <listing-id> awaiting_reply --our-message "<已发送原话>" --next-follow-up "2026-10-27 23:30"
python3 .codex/skills/price-negotiation/scripts/negotiation_state.py check <listing-id> --seller-message "<卖家原话>" --next-follow-up "2026-10-28 09:30"
```

每轮回复追踪先运行 `list --active-only`；只处理有变化或已到跟进时间的记录。不要反复催问，也不要把“浏览过”误写成“卖家已读”或“已承诺”。

## 报价原则

- 像真实买家说话，不像客服或谈判专家：口语化、有温度、长短句交替。
- 报价要有依据：把行情分析和风险折价“翻译”成日常理由，不把分析原文搬进聊天。
- 先建立信任再谈价：先问成色/凭证/瑕疵，再自然带出价格。
- 首报接近目标价，最高可接受价只作内部边界，不向卖家提前亮出。
- 最多主动让步两次；所有价格按“商品价 + 邮费”的总成本比较。
- 金额和风险对应：低价小件简单砍，大额或有风险的商品才值得细谈。

## 风格红线

- 不用“尊敬的卖家”“请问”“敬请”等书面客套。
- 不连续堆专业术语；行情数据只给结论式理由，如“我看同款最近都这个价”。
- 一句话别太长，像发消息不是写作文。
- 不编造“别家更便宜”的假事实；有真实依据才说。

## 报价依据

- 首轮报价 ≈ 目标价，并给一条具体理由（成色瑕疵、已过保、行情变化、自提/邮寄成本）。
- 最高可接受价只在对方还价时渐进逼近，不要提前亮出。
- 问题机或来源不清的货：按“问题机”幅度砍，并要求验机/面交兜底。
- 卖家接受报价后仍需确认货况和平台交易方式；口头接受不等于完成交易。

## 参考

- 完整状态、跟进节奏、异常处理和交接规则：[references/negotiation-sop.md](references/negotiation-sop.md)。
- 分阶段话术与“机械 vs 口语”改写示例：[references/scripts.md](references/scripts.md)。

## 边界

全程只在平台内沟通，不脱离平台转账或收取不明链接。浏览和更新本地档案可以自动进行；每条对外发送的消息都必须先展示原文并取得用户当轮明确授权。不得代替用户下单、付款、填写收货地址、确认收货或申请售后。
