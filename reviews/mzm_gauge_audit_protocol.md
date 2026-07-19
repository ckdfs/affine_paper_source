# MZM 无反馈规范漂移诊断协议

版本：2026-07-16 v1.0（在首个真实 gauge-audit 运行前冻结）

本诊断不属于 acceptance 证据，不选择控制增益，也不更新论文 headline。它只回答
v1.3 全网格预检无法区分的三个机制：物理 MZM `V0` 漂移、重新配置前端后 AC
observer 规范变化、以及偏压阶跃后的首次 acquisition 瞬态/慢滞回。

## 固定流程

1. 新建不可变目录 `data/exp/diagnostics/gauge_audit/<run-id>/`，记录器件、固件、
   仪器、温度、会话和代码 SHA-256。
2. 执行新鲜双向 151 点 Vpi 扫描和 181 点、`n_blocks=16`、`n_avg=4` 的无标签
   椭圆标定。Vpi 与 refit 标定质量门沿用 v1.3；本诊断同时记录 ellipse 对 primary
   scan map 的 concurrence，但不以它停止，因为该差异本身正是诊断对象。
3. 从同一 calibration sweep 的冻结 `B` 与偏压坐标内插出四个基点
   `0, pi/2, pi, 3pi/2` 的固定目标偏压。每个目标都从相对 `-1 rad` 和 `+1 rad`
   的预偏压接近；预偏压 acquisition 也保存。
4. 到达同一冻结目标偏压后，连续采集 6 个 `n_avg=1` acquisition。每次保存时间戳、
   `I1,Q1,I2,Q2`、选定二维观测、board DC 与同步 DMM DC；不得丢弃第 1 次。
5. 三个条件依次为：标定后不重置的 `continuous`、重新执行一次
   `prepare_mzm_frontend` 的 `frontend_reset`、再次重置并固定等待 60 s 的
   `post_reset_delay60`。条件、目标和双侧接近的全部记录都必须保留。
6. 结束后生成 manifest/checksums，执行 `gen reset` 与 `dac 0`。通信故障也保留
   partial NPZ 和失败 manifest。

## 预先规定的判别

- 若只有每次阶跃后的第 1 次二维相位偏离，而第 2--6 次恢复：支持固定 pre-bias
  discard；后续协议必须在 calibration、预检和所有控制器中一致应用。
- 若第 2--6 次仍随接近方向分离：支持慢 settling/滞回，不能用一次 discard 修复。
- 若 DMM 功率峰/局部曲线与二维零点共同移动：支持物理 `V0` 漂移。
- 若 DMM 在同一冻结偏压基本不变而二维相位在 reset 后发生共同旋转：支持 AC
  observer gauge 变化。
- 若 `continuous` 条件已相对 calibration 大幅漂移，则优先评价标定耗时内/后的
  时间漂移，不能把问题归因于 reset。

任何结果都不得用于追认 `20260716_gain_v13_board2`。诊断完成后才能冻结 v1.4；
0.35 rad 终点门和 50/200 mrad 标定预算不因本诊断结果改变。
