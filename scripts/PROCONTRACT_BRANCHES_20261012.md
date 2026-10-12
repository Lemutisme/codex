# ProContract / ProCodex 分支与证据索引（2026-10-12）

## 先选哪个分支

**日常试用和后续修复：`procontract/recommended`。**

- 代码基线 `4669bf71cd897a9ce0e4bd3eb6f6fd23d0ded33a`，之后仅增加本次交接说明。
- Native ProContract 开启，交互式自动 RSI 关闭；RSI 研究须显式启动。
- 包含已验证的重启恢复修复：恢复同一合同，保留修复额度，不重放中断动作。
- 它不是“最新代码已经重新刷出最佳分数”的声明，也不声称已同步最新 upstream。
- 本机安装的 native 发布版本仍标记 `4669bf71cd89`；文档提交不重标记旧二进制。

**查看实测表现更好的冻结控制：`procontract/frozen-e2e-20261011`。**

- 精确指向控制器 `dbc0b5241d7f9b5f2d4d6eadfc88259e4027a032`。
- 实验 native 来源 `d434ba042f9391615abca9e16d103192a5e4ef93`；两者的 Rust 源码树相同。
- “冻结”指始终使用固定种子执行策略、不调用 RSI；不是删掉研究代码的特殊发行版。
- 该历史版本尚有后来修复的 resume 缺陷，因此不建议为了复现成绩而回退日常安装。

## 关键分支地图

| 分支 | 固定提交 / 代码基线 | 用途与边界 |
|---|---|---|
| `procontract/recommended` | `4669bf71cd` + 交接文档 | 推荐使用入口；ProContract-only；不是新的收益认证 |
| `procontract/frozen-e2e-20261011` | `dbc0b5241d` | 这轮较好的实测固定策略控制，保留原实验版本 |
| `procontract-resume-fix/20261012` | `4669bf71cd` | 精确恢复修复与原生回归版本 |
| `procodex-rsi-mechanism/20261011` | `dbc0b5241d` | 递归方法、请求消费见证、coverage / deployment 区分；收益未成立 |
| `procodex-bandit/20261010` | `d434ba042f` | 有界回报选择器与 fixture 路径修复；分支日期不等于最后提交日期 |
| `procodex-online/20261010` | `3ff60ba241` | 在线原生研究、请求证据与早期 dropbear 记录的 native 基线 |
| `procodex-local/20261009` | `03798072c0` | 原本地安装版本，保留作回滚历史 |
| `rsi/live-engine-20261008` | `fc8c485494` | 早期 live engine、进程资源边界与传输失败记录 |
| `procontract-rsi` | `11262cad4f` | 早期研究设计/实现线，保留历史而非推荐默认 |
| `procontract-essential` | `776164115f` | Essential 设计与评测协议 |
| `procontract-essential-impl` | `95332dce91` | 责任 kernel / 原生自动化的基础实现 |
| `procontract-next` | `8a7220d216` | 另一条早期 kernel 硬化与证据坐标设计线 |
| `codex-procontract-policy-split` | `87f47b4e6c` | 独立的 native settlement kernel 历史线 |
| `codex-procontract-native-envelope` | `7f0ffe58c8` | 并行 native/UI/API 开发线；本次仅保留已提交部分，不能冒充本轮 benchmark 版本 |

不是把所有 373 个局部分支都当成独立产品。高层分支保留其可达提交历史，
旧里程碑保持精确指针，不通过 force-push 重写。

## 实测事实，而非版本宣传

以下均为 Luna/max；每组每题一次，5 小时总上限含研究与评分。

| 实例 | 固定 ProContract 控制 | 实验 RSI | 描述性差异 |
|---|---:|---:|---:|
| sox | 569/1196 = 47.58% | 474/1196 = 39.63% | −7.94 pp |
| peco | 891/1215 = 73.33% | 626/1215 = 51.52% | −21.81 pp |
| silver_searcher | 724/1004 = 72.11% | 签约失败，无评分 | 未知，不填 0 |

- 五个有分数的运行，ProContract 均为 `did_not_pass`。功能分数不是合同结清或穷尽合规证明。
- 两代 M 递归和真实请求消费有证据；完整机制验收 FAIL，收益 NOT_ESTABLISHED。
- 前两题是预声明 coverage 探针，不是自然部署收益估计；没有证明 P/M/H 的独立因果收益。
- 历史 dropbear 的一次本地 504/667（75.56%）在当时数值上超过公开最高
  502/667（75.26%）。该次选择 hold，没有 RSI 研究；不是官方榜单提交或 RSI 收益。
- 后补 vanilla/OFF 首题运行 2854 秒后因凭据过期、HTTP 401 终止；后两题未启动。
  没有有效 vanilla 对照分数，不能宣称已战胜裸 Codex。

## 如何核查和继续

- 机器索引：[procontract_handoff_20261012.json](procontract_handoff_20261012.json)。
- 原理与缺口：[responsibility kernel](PROCONTRACT_RESPONSIBILITY_KERNEL.md)。
- 学习定义：[reward selection](PROCONTRACT_REWARD_SELECTION.md) 与
  [finite acceptance](PROCONTRACT_RSI_ACCEPTANCE.md)。
- 设计教训与下一步：[insights](PROCONTRACT_INSIGHTS_20261012.md)。
- 原始运行根目录名、计划摘要与 native 摘要保留在机器索引中；原始轨迹和产物没有公开上传。

主工作树中的未提交 UI/API 改动未被混入这些提交。本机保留了私有 WIP patch
和未跟踪文件清单；清单不等于未跟踪文件内容的远端备份。开始新工作树，不要强行
切换或清理已有脏工作树。普通 upstream 安装命令不会安装本分支的 ProCodex。
