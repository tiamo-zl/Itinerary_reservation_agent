# LLM-as-judge 校准报告

- 时间：2026-11-04T13:53:37+00:00
- 数据集：`tests/eval/judge_calibration_auto.jsonl`
- 用例数：50
- 标签来源：{'auto-rule': 50}
- prompt：judge v1
- 模型：deepseek/deepseek-flash

## 指标

| 指标 | 值 |
|---|---|
| 有效评审 | 50/50 |
| verdict 一致率 | 0.9000 |
| score MAE | 0.5600 |
| quadratic weighted kappa | 0.8307 |
| fail precision | 0.9545 |
| fail recall | 0.8400 |
| fail F1 | 0.8936 |

## 混淆矩阵

| 人工 \ judge | pass | fail |
|---|---|---|
| pass | 24 | 1 |
| fail | 4 | 21 |

## 逐条结果

| case | 人工 | judge | 一致 | 理由 / 错误 |
|---|---|---|---|---|
| pass-flight-hotel | pass/5 | pass/5 | yes | 航班与酒店均符合出发地/目的地、日期、经济舱与王府井区域要求，合计1160元未超2000元预算，差标通过且无需审批，摘要与结构化数据一致。 |
| pass-hotel-only | pass/5 | pass/5 | yes | 仅需酒店的需求已满足，所选王府井酒店480元/晚（住1晚）在1500元预算内，位于指定王府井区域，政策校验通过且无需审批，摘要与方案一致无矛盾。 |
| pass-flight-only | pass/5 | pass/5 | yes | 已按用户仅需机票的需求选择经济舱航班，价格在预算内且差标通过、无需审批，方案与审批结果一致。 |
| pass-approval-approved | pass/4 | pass/5 | yes | 方案回应了上海至北京商务舱机票与王府井酒店需求，舱位超标已按流程审批通过，总价2400元在3000元预算内，无遗漏或矛盾。 |
| pass-budget-exact | pass/5 | pass/5 | yes | 方案选择经济舱航班和王府井酒店，合计 1400 元符合预算与差标，审批状态一致，无明显遗漏或矛盾。 |
| pass-hotel-area | pass/5 | pass/4 | yes | 机票与酒店均符合用户城市、日期、王府井区域和舱位要求，政策通过且总价1120元在2000预算内；唯一疑点是两晚行程仅按一晚房费计（520元），若住宿为两晚合计应为1640元，摘要未说明住宿晚数，存在轻微不清。 |
| pass-two-options | pass/5 | pass/5 | yes | 所选航班与酒店均来自候选且符合经济舱、王府井区域要求，合计1100元在1800元预算内，差标校验通过且无需审批，总结一致无明显遗漏。 |
| pass-no-approval | pass/5 | pass/5 | yes | 方案满足北京出差需求，航班经济舱、王府井酒店均符合差标，总价1100元未超1500元预算且无需审批，信息一致无明显遗漏。 |
| pass-cheap | pass/5 | pass/5 | yes | 方案满足上海至北京、王府井住宿及经济舱要求，机票500元加一晚酒店300元合计800元未超1000元预算，政策通过且无需审批，无明显矛盾。 |
| pass-long-summary | pass/5 | pass/5 | yes | 已按上海至北京、2026-11-10 至 11-11 的行程完成经济舱机票与王府井酒店预订，合计 1180 元未超 2000 元预算，差标校验通过且无需审批，与用户需求及审批结果完全一致。 |
| pass-single-day | pass/4 | fail/2 | no | 总结称“往返”但仅提供一段航班，且同日行程又订酒店，存在明显矛盾与遗漏，虽预算和审批一致。 |
| pass-high-budget | pass/5 | pass/5 | yes | 方案与用户需求一致，机酒均符合预算和差标，审批无需，无明显遗漏或矛盾。 |
| fail-missing-destination | fail/2 | pass/4 | no | 已按王府井（北京）需求预订机票和酒店，总费用1160元在2000元预算内，政策通过且无需审批，无明显遗漏或矛盾。 |
| fail-missing-dates | fail/1 | fail/2 | yes | 机票与酒店均符合预算和王府井区域要求、政策也已通过，但请求中的出行日期为空，回复却自行编造了“11月10日至11日”的行程并称已完成预订，属于与输入矛盾、缺少确认。 |
| fail-budget-violation | fail/2 | fail/2 | yes | 方案已覆盖用户对机票和王府井酒店的需求，且机票和酒店均符合差标，但机票 900 元加上 500 元/晚的住宿合计 1400 元，明显超出 1000 元预算上限；总结却称“差标校验通过”，也未提示超预算，这与预算约束矛盾，需要澄清预算定义或更换方案。 |
| fail-selected-not-in-options | fail/1 | fail/1 | yes | 所选酒店为国贸酒店而非用户要求的王府井区域，且摘要称已选王府井酒店、价格720元/晚，与所选国贸酒店720元/晚明显矛盾。 |
| fail-flight-over-budget | fail/2 | fail/1 | yes | 预算上限 1000 元，但机票 1500 元本身已超预算，加上酒店 300 元合计 1800 元，摘要却称“符合预算”，存在明显矛盾。 |
| fail-hotel-missing | fail/1 | fail/1 | yes | 用户明确需要酒店且指定王府井，但酒店未选、无候选且总结谎称已订酒店，与结构化结果矛盾。 |
| fail-approval-pending | fail/1 | fail/1 | yes | 总结声称商务舱已获批并完成预订，但审批状态为 pending、政策判定舱位超标需审批，存在矛盾；且机票1800+酒店480=2280元超出2000元预算。 |
| fail-policy-contradiction | fail/2 | fail/2 | yes | 差标校验结果自相矛盾：violations 列表含“酒店超差标”，但 passed=true 且总结称“差标校验通过”，未对该违规做说明或处理，方案与审批结论不一致。 |
| fail-empty-summary | fail/2 | pass/4 | no | 所选经济舱机票和王府井酒店与需求一致，总价 1160 元未超 2000 元预算，政策校验通过且无需审批；但 summary 为空，缺少面向用户的汇总说明。 |
| fail-no-selection | fail/1 | fail/3 | yes | 机票680元加酒店480元共1160元，在2000元预算内，城市、日期和王府井区域均与需求一致，且无需审批；但 selected 为空，与摘要中已选择和完成预订的表述相矛盾，没有明确输出具体的机票和酒店选择。 |
| fail-hotel-area | fail/2 | fail/2 | yes | 用户要求王府井区域，实际选的国贸酒店不在王府井，且摘要谎称“位于王府井附近”；虽然预算与审批均合规，但住宿区域与需求不符并存在表述矛盾，需要更正。 |
| fail-status-inconsistent | fail/2 | fail/2 | yes | 方案与差标一致且总价1160元在预算内，但任务状态为WAITING_HUMAN，摘要却称机票酒店均已确认完成，存在明显矛盾。 |
| pass-two-night-hotel | pass/5 | pass/5 | yes | 方案符合用户全部需求（京沪往返、11月10-12日、王府井住宿、经济舱），合计1640元未超2000元预算，与差标通过及无需审批的结论一致，无遗漏或矛盾。 |
| pass-business-approved | pass/4 | pass/5 | yes | 方案回应了上海至北京差旅需求，航班与酒店选择符合预算和王府井区域要求，商务舱超标已提交并获批，合计2280元在3000元预算内，无明显遗漏或矛盾。 |
| pass-cheaper-option | pass/5 | pass/4 | yes | 已按北京出差需求选择更便宜的经济舱航班和王府井酒店，合计1160元在1500元预算内，且与差标通过、无需审批的结论一致。 |
| pass-hotel-only-two-nights | pass/5 | pass/5 | yes | 仅需酒店，已预订王府井区域酒店 2 晚共 960 元，符合 1500 元预算，且未超差标、无需审批，与需求一致且无遗漏。 |
| pass-flight-only-no-hotel | pass/5 | pass/5 | yes | 已按需选择经济舱 CA1501（680 元），未预订酒店符合 need_hotel=false，预算与政策审批均一致，无明显遗漏或矛盾。 |
| pass-exact-budget | pass/5 | pass/5 | yes | 方案符合上海至北京出差需求，机票与王府井酒店均在经济舱和预算内，合计1200元与差标及无需审批结果一致，无明显遗漏或矛盾。 |
| pass-hotel-area-exact | pass/5 | pass/5 | yes | 航班为经济舱、酒店在王府井区域，1晚合计1160元未超2000预算，与差标及免审批结论一致，回应了用户需求且无矛盾遗漏。 |
| pass-high-budget-business | pass/4 | pass/5 | yes | 方案覆盖上海至北京商务舱机票和王府井酒店，总价3200元在5000元预算内，商务舱超差标已提交并获批，与审批结果一致。 |
| pass-single-day-flight | pass/4 | pass/5 | yes | 仅需机票且已选 CA1501（600 元）在 1000 元预算内，差标通过、无需审批，摘要与方案一致，无遗漏或矛盾。 |
| pass-no-approval-required | pass/5 | pass/5 | yes | 方案完全符合需求：经济舱机票600元、王府井酒店520元、合计1120元未超1500元预算，差标校验通过且无需审批，摘要与选项一致。 |
| pass-two-hotels-selected-one | pass/5 | pass/4 | yes | 方案选 CA1501 机票 600 元加王府井酒店 480 元/晚共 1080 元，在 1800 元预算内，符合经济舱与王府井区域要求，政策通过且无需审批，摘要与明细一致；仅两家候选酒店同名不同价，略有歧义。 |
| pass-policy-violation-approved | pass/4 | pass/5 | yes | 方案覆盖上海至北京机票和王府井酒店，合计2100元未超3000元预算；酒店超标已按流程审批通过，与差标及审批结果一致。 |
| pass-hotel-not-needed | pass/5 | pass/5 | yes | 已按用户需求仅安排上海至北京经济舱机票 CA1501（700 元），在 1000 元预算内且符合差标、无需审批，与用户明确不需要酒店一致。 |
| fail-budget-overrun | fail/2 | fail/1 | yes | 总价 1500 元（机票 900 + 酒店 600）明显超出 1000 元预算，摘要却称未超预算，结论与数据矛盾。 |
| fail-selected-flight-not-in-options | fail/2 | fail/3 | yes | 预算和差标均符合，但选中航班号 CA999 与候选/摘要中的 CA1501 矛盾，存在明显不一致。 |
| fail-selected-price-mismatch | fail/2 | fail/3 | yes | 酒店价格在所选方案（400元/晚）与候选列表（480元/晚）中不一致，导致合计1080元的预算结论无法核实，存在明显矛盾。 |
| fail-approval-rejected | fail/1 | fail/1 | yes | 审批结果为 rejected、差标校验未通过，但总结却声称商务舱申请已获批，方案与审批结果直接矛盾，不能作为可执行差旅安排。 |
| fail-hotel-area-mismatch | fail/2 | fail/2 | yes | 用户明确要求住宿在王府井，但所选“国贸酒店”位于国贸区域，总结中还称其“位于王府井附近”，这与用户需求矛盾；其余航班、预算和差标均无问题。 |
| fail-policy-failed-but-passed | fail/2 | fail/1 | yes | 差标校验结果为不通过（酒店超出差标），但总结却称“差标校验通过、无需审批”，与 policy 字段直接矛盾，且未给出超标酒店的处理或替代方案。 |
| fail-missing-budget | fail/2 | fail/3 | yes | 机票与酒店方案符合经济舱、王府井区域和差标要求，但总结先称用户未提供预算，又称合计 1160 元在 2000 元预算内；预算上限为空却虚构了 2000 元额度作为免审批依据，前后矛盾。 |
| fail-missing-return-flight | fail/2 | pass/4 | no | 方案满足北京出差、经济舱与王府井住宿需求，合计1160元未超2000预算，与差标及无需审批结果一致；仅摘要中“往返机票”表述与实际只含一段航班价格略有不符。 |
| fail-hotel-missing-despite-needed | fail/2 | pass/5 | no | 方案覆盖机票和王府井酒店，合计1160元在2000元预算内，政策通过且无需审批，无明显遗漏或矛盾。 |
| fail-empty-options | fail/1 | fail/1 | yes | 摘要声称已预订机票和酒店共1160元，但 selected 与 options 中的航班、酒店列表均为空，无任何具体方案可核对，且与差标/预算一致性无法验证，属明显矛盾与遗漏。 |
| fail-wrong-destination-summary | fail/2 | fail/2 | yes | 行程摘要将目的地北京误写为上海，与用户请求明显矛盾；其余航班、酒店、预算和审批均一致。 |
| fail-status-waiting-human | fail/2 | fail/2 | yes | 任务状态为 WAITING_HUMAN，但总结声称“已完成预订并确认”，且未说明待人工处理事项，存在明显矛盾。 |
| fail-cabin-mismatch | fail/1 | fail/1 | yes | 所选航班为商务舱 CA1502（1800 元），与用户经济舱需求和摘要所述 CA1501（680 元）矛盾，且机票加酒店共 2280 元超出 2000 元预算，与“符合差标”结论不一致。 |

> 当前标签由确定性规则生成（silver labels），不能替代人工校准。

