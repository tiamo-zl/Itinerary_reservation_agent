# LLM-as-judge 校准报告

- 时间：2026-11-02T14:19:36+00:00
- 数据集：`tests/eval/judge_calibration.jsonl`
- 用例数：24
- 标签来源：{'seed': 24}
- prompt：judge v1
- 模型：deepseek/deepseek-flash

## 指标

| 指标 | 值 |
|---|---|
| 有效评审 | 24/24 |
| verdict 一致率 | 0.8750 |
| score MAE | 0.6667 |
| quadratic weighted kappa | 0.7580 |
| fail precision | 1.0000 |
| fail recall | 0.7500 |
| fail F1 | 0.8571 |

## 混淆矩阵

| 人工 \ judge | pass | fail |
|---|---|---|
| pass | 12 | 0 |
| fail | 3 | 9 |

## 逐条结果

| case | 人工 | judge | 一致 | 理由 / 错误 |
|---|---|---|---|---|
| pass-flight-hotel | pass/5 | pass/5 | yes | 方案符合经济舱、王府井住宿和2000元预算要求，合计1160元，差标通过且无需审批，摘要无矛盾。 |
| pass-hotel-only | pass/5 | pass/5 | yes | 用户仅需酒店，所选王府井酒店 480 元/晚、1 晚共 480 元，在 1500 元预算内且位于指定王府井区域，差标校验通过、无需审批，摘要与实际方案完全一致，无遗漏或矛盾。 |
| pass-flight-only | pass/5 | pass/5 | yes | 用户仅需机票，已选 CA1501 经济舱 680 元，在 1200 元预算内，政策通过且无需审批，摘要与方案一致无矛盾。 |
| pass-approval-approved | pass/5 | pass/5 | yes | 方案满足上海至北京往返、王府井酒店和商务舱需求，住宿仅1晚合计2400元未超3000元预算，舱位超标已按要求提交审批并获批，说明与审批结果一致且无矛盾。 |
| pass-budget-exact | pass/4 | pass/4 | yes | 行程为11-10至11-11共一晚，机票800元加酒店600元恰为1400元，符合预算与王府井区域要求，政策通过、无需审批，方案与差标一致；仅因预算恰好用满无余量，略有风险。 |
| pass-hotel-area | pass/5 | pass/5 | yes | 机票经济舱600元、王府井酒店520元/晚合计1120元，均在2000元预算与差标内，政策校验通过且无需审批，方案完整回应用户需求且无矛盾。 |
| pass-two-options | pass/4 | pass/5 | yes | 所选航班与酒店均符合经济舱、王府井区域及1800元预算要求，合计1100元且审批免申请，方案完整一致。 |
| pass-no-approval | pass/5 | pass/5 | yes | 方案满足目的地、日期、舱位和王府井酒店要求，总价1100元未超1500元预算，差标通过且无需审批，无明显遗漏或矛盾。 |
| pass-cheap | pass/5 | pass/5 | yes | 机票500元加工1晚酒店300元共800元，符合1000元预算；同时满足王府井住宿、经济舱、京沪往返等需求，政策校验通过且无需审批，无遗漏或矛盾。 |
| pass-long-summary | pass/4 | pass/4 | yes | 行程、舱位、酒店区域均符合需求，合计 1180 元未超 2000 元预算，差标校验通过且无需审批；但仅列出去程航班，未见返程航班安排，建议补充确认。 |
| pass-single-day | pass/4 | pass/4 | yes | 方案满足北京出差、经济舱和王府井酒店需求，合计1100元未超1500元预算且审批无需，仅单日往返与住宿安排存在轻微表述矛盾。 |
| pass-high-budget | pass/4 | pass/5 | yes | 方案覆盖商务舱机票和王府井酒店，合计3200元低于5000元预算，差标校验通过且无需审批，与用户需求一致。 |
| fail-missing-destination | fail/0 | pass/4 | no | 已按上海出发、王府井住宿需求选定北京行程机票680元与酒店480元/晚（共1晚），合计1160元未超2000元预算，符合差标且无需审批，仅目的地城市字段为空、住宿晚数未明确说明略有不足。 |
| fail-missing-dates | fail/1 | fail/2 | yes | 用户未提供出行日期，总结却编造“11月10日至11日”，且无法核实住宿晚数与总预算是否在2000元内，存在信息不足和矛盾。 |
| fail-budget-violation | fail/1 | fail/1 | yes | 机票900元加酒店500元共1400元，超出1000元预算，但汇总仍称校验通过，存在明显矛盾。 |
| fail-selected-not-in-options | fail/2 | fail/1 | yes | 方案选择的酒店是国贸酒店，而非用户指定的王府井区域，且总结写“已选择王府井酒店”，与所选酒店和价格信息明显矛盾。 |
| fail-flight-over-budget | fail/1 | fail/1 | yes | 机票 1500 元已超过 1000 元总预算，加酒店 300 元共 1800 元，摘要却称“符合预算”，与预算限制及差标明显矛盾；政策 passed 且无违规也与超预算事实不一致。 |
| fail-hotel-missing | fail/1 | fail/1 | yes | 用户明确需要酒店，但酒店选项为空且未预订（hotel 为 null），摘要却称已预订机票和酒店，存在明显矛盾与需求遗漏。 |
| fail-approval-pending | fail/1 | fail/1 | yes | 摘要称商务舱已获批并完成预订，但审批状态为 pending 且政策未通过（舱位超标需审批），且机票1800+酒店480=2280超出2000预算，存在明显矛盾与超支。 |
| fail-policy-contradiction | fail/1 | fail/2 | yes | 差标校验结果存在明显矛盾：policy.violations 标注“酒店超差标”，但 passed=true 且总结称“差标校验通过”，未说明或处理该违规项，方案与审批结论不一致。 |
| fail-empty-summary | fail/2 | pass/5 | no | 所选经济舱机票680元与王府井酒店480元/晚合计1160元，低于2000元预算，符合差标且无需审批，无明显遗漏或矛盾。 |
| fail-no-selection | fail/2 | pass/4 | no | 机票经济舱680元与王府井酒店480元×1晚合计1160元，符合2000元预算与差标（policy通过、无需审批），行程日期与目的地均匹配；仅 selected 为空且总结未列明具体航班/酒店与金额明细，信息呈现略单薄。 |
| fail-hotel-area | fail/1 | fail/2 | yes | 所选国贸酒店不在用户要求的王府井区域，摘要却称“位于王府井附近”，与需求矛盾；预算与差标虽合规，但住宿区域不符属明显遗漏。 |
| fail-status-inconsistent | fail/1 | fail/2 | yes | 方案符合预算与差标且无需审批，但任务状态为 WAITING_HUMAN，而总结称已完成确认，存在明显状态矛盾。 |

> 当前标签为 seeded 基线；正式校准前应替换为人工标注。

## 解读

- 12 条 pass 全部一致；12 条 fail 中识别 9 条，3 条 false negative：
  - `fail-missing-destination`
  - `fail-empty-summary`
  - `fail-no-selection`
- judge 倾向从 `options` 推断方案，忽略了 `request` 关键字段、
  `summary` 或 `selected` 为空。
- 建议 judge v2 明确规则：
  - 关键 request 字段缺失必须 fail；
  - summary 为空必须 fail；
  - 有候选但 selected 为空必须 fail。

