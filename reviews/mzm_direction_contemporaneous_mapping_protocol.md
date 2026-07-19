# MZM 方向同时性观察映射稳定性协议

版本：2026-07-17 v1.0（在实现和任何新真实运行前冻结）

本协议承接 A28--A29，只诊断二维 H1/H2 观察映射是否可在一次 ABA 标定期间视为
静态。它不替代 time-resolved DMM truth，不运行闭环，不更新
`data/exp/results.json` 或论文 headline，也不授权 gauge audit、v1.4 preflight 或
acceptance。

## 1. 输入与防泄漏

输入必须满足 `mzm-time-resolved-calibration-v1.1` 的完整 ABA 合同：三条 leg 固定为
`up(0) -> down(1) -> up(2)`，每条 81 点；每条 72 个 formal、9 个 sentinel。逐点
相位标签只能来自 formal 拟合的 time-resolved DMM 模型
`phi_truth(t_i)`。不得使用静态 scan map。

对每条 source leg，phase-reference 仿射映射
`z=A[cos(phi),sin(phi)]^T+b` 只用该 leg 的 formal 点拟合。source sentinel、其他
leg 的 formal 和所有其他 sentinel 均不得进入该映射拟合。通道选择仍只使用全体
formal raw I/Q，不能按 leg 或结果改选。

## 2. 预注册评估矩阵

对三个 source-leg 映射逐一计算：

- own-leg formal concurrence（拟合内诊断）和 own-leg sentinel concurrence；
- 两条同方向 up leg 的双向交叉：`0 -> 2`、`2 -> 0`；
- up/down 的四个有向交叉：`0 -> 1`、`2 -> 1`、`1 -> 0`、`1 -> 2`。

每个有向交叉都分别在 target leg 的 formal 和 sentinel 上报告绝对 wrapped phase
error 的 median/P95/RMS。不得只报告较有利方向、只合并两条 up，或删除端点附近
误差。

同时保存每条映射的 `c0`、`A_hat`、条件数，以及每对映射的
`||A_i-A_j||_F/||A_i||_F` 和 `||c0_i-c0_j||_2`。这些矩阵差异只作机理诊断，不单独
决定通过，因为高条件数下很小的矩阵变化也可能产生较大相位误差。

## 3. 冻结通过门

所有 own-leg formal、own-leg sentinel、同方向交叉和跨方向交叉的 median/P95 都
必须分别不超过 50/200 mrad。两个阈值继承 A26--A28 的 primary/contemporaneous
concurrence 门，不根据 A28 结果调整。总门分解保存为：

- `own_leg_mapping_pass`；
- `same_direction_mapping_pass`；
- `cross_direction_mapping_pass`；
- `observer_mapping_stability_pass`，为前三者逻辑与。

任一子门失败即证明本次 ABA 期间没有证据支持单一静态仿射观察映射。即使其他
time-truth 门通过，也禁止把一条 leg 的椭圆用于后续闭环。

本门不检查 ADC clipping。CH1 board DC 只保留 monitor advisory；CH0 raw extrema
和 clip count 是另一项独立的 v1.4 可观测性要求。

## 4. 实现前验证

1. 静态仿射映射、健康 DMM time truth 的确定性 ABA 合成数据必须全部通过。
2. 只对 down leg 施加已知 affine center/matrix perturbation 时，DMM truth 拟合应
   保持不变，而 `cross_direction_mapping_pass` 必须失败。
3. sentinel-only I/Q 污染不得改变任何 source-leg calibration，但必须在相应
   target sentinel gate 被发现。
4. A28 真实 NPZ 只读回放必须报告两条 up 大体可互换而 up/down 明显不兼容；不得
   改写 A28 的 manifest、analysis 或 checksums。
5. 缺少 leg、leg/direction 不一致、每条 leg formal/sentinel 数量错误或非有限 I/Q
   均硬失败。

只有协议、纯离线实现、自测和 A28 回放全部完成并写入主交接记录后，才可设计包含
CH0 raw-extrema 遥测的下一次真实诊断；本协议本身不构成运行授权。
