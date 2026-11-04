# LLM-as-judge 校准报告

- 时间：2026-11-04T00:49:05+00:00
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
| score MAE | 0.8333 |
| quadratic weighted kappa | 0.7442 |
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
| pass-flight-hotel | pass/5 | pass/5 | yes | 所选航班和酒店均符合经济舱与王府井区域要求，480 元/晚住 1 晚，合计 1160 元，未超 2000 元预算，且差标校验通过、无需审批，摘要与结构化数据一致，已完整回应用户需求。 |
| pass-hotel-only | pass/5 | pass/5 | yes | 方案符合仅需酒店、王府井区域和1500元预算要求，且与差标及无需审批结论一致。 |
| pass-flight-only | pass/5 | pass/4 | yes | 已按需求选择经济舱机票且价格在预算内，政策与审批状态一致；但未明确航班日期及是否需返程，信息略有不足。 |
| pass-approval-approved | pass/5 | pass/5 | yes | 方案覆盖往返机票与王府井酒店，商务舱超标已提交并获批，总价2400元在3000元预算内，与审批结果一致。 |
| pass-budget-exact | pass/4 | pass/5 | yes | 已按需求选择上海至北京经济舱航班和王府井酒店，总价1400元符合预算，差标通过且无需审批，无明显遗漏或矛盾。 |
| pass-hotel-area | pass/5 | pass/5 | yes | 机票与酒店均符合用户需求（经济舱、王府井区域）、政策合规免审批，合计1120元在2000元预算内，无遗漏或矛盾。 |
| pass-two-options | pass/4 | pass/5 | yes | 所选航班和酒店均符合经济舱、王府井区域及1800元预算要求，合计1100元，且差标通过无需审批，回应完整无矛盾。 |
| pass-no-approval | pass/5 | pass/5 | yes | 方案满足上海至北京往返差旅需求，机票700元加酒店400元共1100元未超1500元预算，王府井酒店符合区域要求，舱位与差标一致且无需审批。 |
| pass-cheap | pass/5 | pass/4 | yes | 已按需求选择上海-北京经济舱机票与王府井酒店，合计800元在1000元预算内，差标通过且无需审批，方案无明显矛盾；仅机票未注明单程/往返略欠清晰。 |
| pass-long-summary | pass/4 | pass/5 | yes | 方案与需求完全一致：经济舱上海至北京、王府井酒店1晚（460元），合计1180元未超2000元预算，差标通过且无需审批，摘要无矛盾。 |
| pass-single-day | pass/4 | pass/4 | yes | 方案选择了经济舱航班和王府井酒店，合计1100元在1500元预算内，政策通过且无需审批，整体符合需求；但总结称往返而仅列一个航班，返程信息略不完整。 |
| pass-high-budget | pass/4 | pass/5 | yes | 商务舱机票2000元加王府井酒店1晚1200元共3200元，符合5000元预算与差标，舱位和酒店区域均与需求一致，无需审批。 |
| fail-missing-destination | fail/0 | pass/4 | no | 方案按经济舱机票680元+王府井酒店480元/晚预订，合计约1160元未超2000元预算，差标合规且无需审批，与用户需求一致；但请求中未给出目的地城市，回答直接认定为北京，属轻微信息缺口。 |
| fail-missing-dates | fail/1 | fail/2 | yes | 请求未提供起止日期，无法核对行程与住宿晚数；总结中的“11月10日至11日”无依据，预算是否合规也无法完全确认。 |
| fail-budget-violation | fail/1 | fail/2 | yes | 机票900元加一晚酒店500元合计1400元，超出1000元预算，却显示差标校验通过且未说明超预算处理，存在明显矛盾。 |
| fail-selected-not-in-options | fail/2 | fail/1 | yes | 所选酒店为国贸酒店，与指定王府井区域及备选王府井酒店不符，且摘要称已选王府井酒店、价格720，与结构化选择明显矛盾。 |
| fail-flight-over-budget | fail/1 | fail/1 | yes | 机票1500元已超出总预算1000元，加酒店后总价约1800元，但摘要却称“符合预算”，方案与预算明显矛盾。 |
| fail-hotel-missing | fail/1 | fail/1 | yes | 用户明确需要酒店且指定王府井区域，但酒店选项为空、未选中任何酒店，总结却声称已预订机票和酒店，与事实矛盾且遗漏核心需求。 |
| fail-approval-pending | fail/1 | fail/1 | yes | 审批状态仍为pending、政策判定未通过，摘要却称商务舱已获批准并完成预订；且机票1800+酒店480=2280超预算2000，存在明显矛盾与超支。 |
| fail-policy-contradiction | fail/1 | fail/2 | yes | 差标校验结果自相矛盾：passed=true 且摘要称“校验通过”，但 violations 明确列出“酒店超差标”，且审批状态为 not_required 未做处理，方案与差标/审批结论不一致。 |
| fail-empty-summary | fail/2 | pass/3 | no | 航班与酒店均符合需求（经济舱、王府井区域）且总价 1160 元未超 2000 预算、政策通过无需审批，但 summary 为空，缺少航段时间、入住夜数与总费用等行程说明，回应不够完整。 |
| fail-no-selection | fail/2 | pass/4 | no | 方案选用经济舱机票680元与王府井酒店480元/晚（共1晚），合计1160元未超2000元预算，符合差标且无需审批，与摘要一致；但selected字段为空，未明确记录已选资源，存在轻微信息缺失。 |
| fail-hotel-area | fail/1 | fail/2 | yes | 酒店选为“国贸酒店”，与用户指定的王府井区域不符，且摘要称其位于王府井附近存在明显矛盾，未满足核心住宿区域需求。 |
| fail-status-inconsistent | fail/1 | fail/3 | yes | 机票和酒店方案符合预算与差标，但任务状态为WAITING_HUMAN却在summary中称已完成确认，状态描述矛盾。 |

> 当前标签包含 seed 基线；正式校准前应替换为人工标注。

