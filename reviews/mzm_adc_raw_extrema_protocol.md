# MZM CH0 同窗 raw ADC 可观测性协议

版本：2026-07-17 v1.0（在固件和主机实现前冻结）

目的仅是证明产生 H1/H2 I/Q 的 ADS131M02 CH0 在每次 `acq run` 窗口内没有到达或
逼近 ±1.2 V rail。DM858E 继续提供 DC truth；CH1 `dc_board` 只作 monitor advisory，
不得代替 CH0 证据。本协议不授权闪写、真实实验、gauge audit、v1.4 或 acceptance。

## 1. 固件输出合同

保持现有 `ACQ n=... dc=... | ...` 行逐字符兼容，在其后新增两行：

```text
RAWADC v=1 scope=acq expected=<u32> used=<u32> read_fail=<u32> blocks=<u32> complete=<0|1> timeout=<0|1> gain=1 fs_uv=1200000 guard=8381618 crc=0
RAWADC_CH v=1 scope=acq ch=0 min=<i32> max=<i32> rail_lo=<u32> rail_hi=<u32> guard_lo=<u32> guard_hi=<u32>
```

字段顺序、名称和整数语义冻结。每行必须短于固件 256-byte UART buffer。统计只在
`acq run` 的成功 `ads131m02_read_sample()` 后、把同一个 `smp.ch0` 送入 Goertzel
之前或同时更新；不得另起一次 `adc N` 冒充同窗证据。所有打印均在 acquisition 与
pilot 停止后执行，不得在活跃采样循环中调用 UART。

- `expected=n_blocks*1280`；`used` 为实际进入 CH0 Goertzel 与统计的样本数；
- `read_fail` 为 DRDY 已到但 sample read/valid 失败数；
- `complete=1` 当且仅当 block、样本、read 和 timeout 合同全部完整；
- `rail_lo/hi` 分别计数 raw code 等于 `-8388608/+8388607`；
- `guard_lo/hi` 分别计数 code `<=-8381618` 和 `>=+8381618`，对应 gain=1 下
  `|V|>=1.199 V`；
- `crc=0` 如实记录当前 driver 尚未校验 frame CRC，不得写成 1。

首版只冻结 CH0，因为它直接生成 H1/H2。CH1 可后续以相同格式追加，但不是本协议
accepted 的必要条件。

## 2. 主机与文件合同

旧 helper 可以忽略新行；论文侧 parser 必须从原始命令文本解析可选 `rawadc` 子结构。
缺少新行的旧固件仍可用于历史只读 replay，但新协议真实运行必须在输出偏压前拒绝。

`n_avg=4` 时，每个短窗分别验证，聚合记录保存：expected/used/read_fail 和所有计数之
和、min 的最小值、max 的最大值，以及全部窗口 `complete` 的逻辑与。CSV/NPZ 每点
至少保存这些聚合字段；不得只保存四次中的最后一次。

## 3. 通过门

每个正式点和 conditioning 点均必须满足：

- telemetry 两行存在且版本/`scope/gain/fs_uv/guard` 与冻结值一致；
- `complete=1`、`timeout=0`、`read_fail=0`、`used=expected>0`；
- CH0 `rail_lo=rail_hi=guard_lo=guard_hi=0`；
- `min>-8381618` 且 `max<8381618`，并且 `min<=max`。

全部正式点通过才可令 `adc_raw_extrema_available=true`。该门只是 time-calibration
accepted 的必要项；只有方向/漂移、无标签 concurrence 和观察映射稳定性也全部通过
时，才可进一步讨论 `v1_4_authorization_ready`。CRC 未校验作为明确限制保留，但本轮
不把它新增为拒绝项。

## 4. 实现与验证边界

1. 先做 host parser/aggregate 合成测试：健康、missing line、read failure、timeout、
   exact rail、guard-only 和四窗中单窗失败。
2. 交叉编译固件，确认原 ACQ 行不变、新行长度安全、无 warning；运行现有全部 host
   tests。
3. time-calibration `--sim` 必须生成可 replay 的完整 raw telemetry 并通过；旧 A28
   replay 必须明确显示 raw telemetry unavailable，而不能伪造字段。
4. 本阶段不刷写硬件。只有源码、host tests、固件 build、协议与 A31 记录全部完成后，
   才可请求单独的 flash/bench 授权。
