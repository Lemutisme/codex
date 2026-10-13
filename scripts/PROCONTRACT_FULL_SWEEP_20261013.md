# Luna/max 新版全量验证协议

授权来源：用户在 2026-10-13 的全量预算选项之后明确回复“开始”“只跑新版”。
本轮不是旧研究的续费、重跑或追加搜索。

## 冻结矩阵

- ProgramBench 官方 200 个实例，排除 `testorg__` 测试夹具；固定 metadata、测试
  revision、镜像内容摘要和每题允许的预装依赖。图片/测试包已在本机，不下载或安装。
- `gpt-5.6-luna / max`，仅新版 ProContract successor 臂，固定 seed P。
- 每题一次任务：最多 18,000 秒，其中 native 最多 14,400 秒，包含验收与最多三个
  后继 session；官方评分最多 3,600 秒。整个 episode 另受同一个 5 小时 watchdog 约束。
- 总上限：200 task reservations、0 RSI research reservations、3,600,000 分配秒。
  Draft/probe/review 与后继执行都计入实际 native token；不因换 session 重置预算。
- 顺序为 `sha256(succession-full-v1:<instance>)`；4 个 episode 并发。
- 每个容器默认 4 CPU、32 GiB、512 PID、network=none；更小的既有内存限制保留。
  容器标记独立 study/episode 所有权；不清理其他用户的容器或镜像。
- 磁盘不足 50 GiB 时停止新 admission，不静默跳题。完成评分、确认 native 退出后，
  对本 study 自己的 `codex-home` 做带摘要的无损压缩，保留 workspace、提交、评分及
  私有 trace。旧研究和用户项目不删除。

## 接入不靠“换一个二进制”

旧 pilot 只选前三题，benchmark settings 默认仍是一次同会话 repair。本入口独立
枚举全部 200 题，在 manifest 中绑定 successor grant 与 settings 摘要，运行后核对
原始 deadline、session IDs、次数与一次 Issue。后继 session 的 usage 单列，但它已经
包含在 `workers` 合计中，不再次累加。完整 200 槽的 supervisor 在无模型测试中走完。

每题使用独立 canonical registry/pins，避免每次评分都重新核查全部 200 题。
官方评分仍使用同一已冻结适配器、eligible 分母和既有确定的基础设施重试规则；
这是同一冻结提交的评分重试，不是重新购买 agent rollout 或取最高成绩。

## 终态与失败

- 正常交付或可识别的预算停止：在执行者退出后冻结最终 workspace 评分。
  预算停止时的功能分数不等于合同通过。
- Provider、进程生命周期、grant、输入摘要或评分有效性异常：保留未评分/失败记录，
  不填 0、不重跑、不退款；停止新的 admission，已启动的其他 episode 受各自原始上限
  约束完成清理。模型编译失败是否为 0 沿用 canonical 定义，不另行重解释。
- 已终结的 sweep 不能直接再次 `run`。未启动名额与已花名额始终区别记录。
- 任务质量低不是提前停止条件。不能以先看成绩再换实例/版本的方式挑选结果。

输出：`supervisor.json`、`budget.sqlite`、每题 `result.json`、`SUMMARY.json`、
`results.csv`、`terminal.json`。报告给出 scored-only 均值及完整 200 题在缺失值下的
数学边界，明确有效分数数量；边界不是填零或置信区间。

## 解释范围

“冻结版”指 ProContract 责任与独立验收仍开启、策略固定、没有 RSI 更新和这次的
跨 session 自动接续；它不是裸 Codex。本轮按授权不运行冻结版或 vanilla。

旧版、OpenCode 和榜单只能作注明模型、预算、依赖及版本差异的历史参照。
单臂全量结果不构成自动接续的独立因果净收益证明，更不证明研究方法/运行时的通用 RSI。
作者历史标量曝光、peco/silver 的事后细节分析已披露；不称 globally unseen。
官方 grader 反馈不进入执行者；各实例不共享学习谱系。

此处 1,000 小时是 task allocation 上限，不是实际耗时或账单估算。
