# MZM 生产路径稠密 V0 稳定性诊断

版本：2026-07-16 v1.0（在首个真实运行前冻结）

本诊断用于替代失败的 direct-DAC 四点 monitor。它复制 `stage_vpi` 的真实输出与
测量路径：`gen bias`、0.15 V/1 kHz pilot、`acq run 6 blocks`，随后读取 DMM。
它不运行闭环、不更新 `data/exp/results.json` 或论文 headline，也不追认旧数据。

## 固定采集

- 固定 `Vpi=5.222139048 V`、参考 `V0=0.814763571 V`；扫描范围为
  `V0±Vpi = [-4.407375, 6.036903] V`。
- 正向 81 点、逆向 81 点，步进约 0.13055 V；3 个 epoch 连续执行，每个 epoch
  均从低到高再从高到低，共 486 个正式点。
- 正式扫描前从 0 V 以不大于正式步长的小步进移动到下边界；conditioning 点全部
  保存但不进入稳定性评分，避免首次约 4.4 V 大跳变混入 epoch。
- 每点保存 epoch、方向、索引、命令偏压、绝对时间戳、DMM、board DC、
  `I1/Q1/I2/Q2`。异常保留 partial CSV、summary、manifest 与 SHA-256。
- 每个方向均在冻结 Vpi 下拟合
  `P=a+c*cos(pi*V/Vpi)+d*sin(pi*V/Vpi)`；V0 对齐到同一参考分支。

## 预先规定的通过门

所有条件必须同时成立：

1. 六个方向拟合均有限、幅度为正且 `RMSE/amplitude <= sin(0.05)`；
2. 每个 epoch 的正/逆 V0 分裂折算相位不超过 0.05 rad；
3. 三个 epoch 平均 V0 的峰峰值折算相位不超过 0.05 rad；
4. 以 epoch 中点的两两斜率中位数外推 30 min，相位漂移不超过 0.05 rad。

本协议没有按首块结果早停；除硬件故障/通信异常外必须完成 3 个 epoch。失败后不
增加等待、不减点、不放宽门。只有本诊断通过，才允许重新设计 gauge audit；
v1.4 preflight 和 acceptance 仍需另行冻结。
