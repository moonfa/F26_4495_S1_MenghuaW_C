---
title: "Personal Investment Workbench v2 — 设计文档"
subtitle: "Thesis Tracker：从一次性报告到持续跟踪系统"
date: "2026-10-01"
---

# 1. 设计目标

| 旧版问题 | v2 的回应 |
|---|---|
| 报告是一整块 markdown，历史不可比 | 每次分析产出**结构化论点状态**（核心假设 + 状态 + 证伪条件），可逐项对比 |
| 两套互相矛盾的变化检测，股价波动误判为基本面变化 | 单一实现 `core/signals.py`，**先剔除价格效应**再判断 |
| 每次都全量重写，token 浪费，缓存命不中 | 静态层只生成一次；更新只看"上期论点 + 增量"；无变化则**零 LLM 调用** |
| 前端 5 层补丁、暴露内部 ID | 以 4 页信息架构重建（Phase B） |

核心原则：**投资论点是一等公民**，报告只是它的叙述载体。

# 2. 架构

```
OpenBB adapter ──► Snapshot ──► signals.compute_delta / classify
                                     │ none → Review(kind=check)  ← 免费、确定性
                                     │ minor/material
                                     ▼
                         prompts + provider (Gemini) ──► Review(kind=baseline|update|rebaseline)
                                                              │
                         API (FastAPI) ◄──────────────────────┘ ──► 4 页前端
```

目录：`app/core/signals.py`（纯 Python 变化检测）、`app/ai/`（schemas / prompts / provider）、`app/service.py`（编排）、`app/api/routes.py`、`app/models.py`。旧版的 OpenBB adapter 原样保留。

# 3. 数据模型（4 张表）

| 表 | 作用 |
|---|---|
| `companies` | ticker、名称、报告语言 |
| `snapshots` | 每次刷新的归一化证据 + 价格 + 指纹（不存原始 provider 载荷） |
| `reviews` | **核心表**。每行是一份完整、自包含的论点状态：`kind`（baseline / rebaseline / update / check）、`level`（none / minor / material）、`view`、`view_change`、`one_liner`、`state`（profile + assumptions + monitor）、`changes`、`narrative`、`delta`、`usage` |
| `notes` | 个人笔记，可挂在某次 review 上 |

因为每个 Review 自包含，**时间线 = reviews 列表，版本对比 = 两行 state 的 diff**，不再需要旧版的 Thread / ThreadVersion / ThreadAction 与人工审批。

## 论点状态（`reviews.state`）

- **assumptions**（3–5 条）：`id`、`statement`、`status`（holding / strengthened / weakened / broken / unverified）、`evidence`、`kill_criteria`、`confidence`
- **profile**（静态层，只在 baseline / rebaseline 生成）：分类、商业模式、护城河、驱动、风险机制、**看空论证**、估值隐含预期
- **monitor**：监控指标 + 触发阈值

`view`（constructive / neutral / cautious）是**跟踪立场**，不是买卖建议；prompt 仍禁止目标价和买卖建议。`view_change` 由代码对比前后 `view` 得出，不采信模型自报。

# 4. 变化检测规则（`core/signals.py`）

比较对象是**最近一次被分析的锚点**，而不是上一次刷新，避免小幅漂移永远累积不到阈值。

1. **价格效应剥离**：估值倍数的变化先除以股价变化（收益率类取倒数关系）。股价涨 20%、P/E 涨 20% → 无新信息。
2. **基本面**：`financial_health.*`、`analyst_consensus.*` 相对变化 ≥3% 记为 minor，≥15% 记为 material。
3. **估值（剔除价格后）**：≥8% minor，≥20% material。
4. **新闻**：硬关键词（指引、并购、业绩超/不及预期、CEO 变动、中英文）→ material；软关键词或 ≥3 条新标题 → minor。
5. 阈值集中在 `Thresholds`，可调。

结果 `none` → 写一行 `check`（连续的 check 合并为一行）；否则调用模型。

# 5. Token 与成本策略

| 手段 | 效果 |
|---|---|
| 无变化不调用模型 | 大多数刷新成本为 0 |
| 静态层只生成一次 | 更新输入只含上期论点摘要（假设的 id/陈述/状态/证伪条件）+ delta |
| 缓存键 = prompt 版本 + 模型 + 语言 + 锚点 + **基本面指纹** + 新新闻标题 | 股价 tick 不再击穿缓存 |
| 紧凑 JSON、去 null、描述截断、新闻只带标题 | 降低输入 token |
| `system_instruction` 独立传入 | 为 context caching 留出口 |
| 分任务设 `max_output_tokens`（baseline 7000 / update 2500），截断检测 + 一次短版重试 | 避免旧版 6000 token 截断导致整次浪费 |
| 单语言生成 | 不再中英文各调用一次 |

# 6. Prompt 设计

- 两个 prompt：`BASELINE`（建立论点）与 `UPDATE`（只回答"变了什么、哪些假设受影响、立场是否变化"），共享一套规则。
- 规则：证据只能来自输入；每个判断必须带数字或可验证事实；先论证最强看空理由再定立场；价格波动本身不是论点变化；禁止套话。
- 输出由 Pydantic schema 约束，字段长度有上限，UI 组件与字段一一对应。
- 版本号 `PROMPT_VERSION` 参与缓存键，改 prompt 必须改版本号。

# 7. API

| 接口 | 用途 |
|---|---|
| `POST /companies/{t}/refresh` | **唯一入口**：系统决定做 baseline、更新或免费检查，返回是否调用了 LLM |
| `GET /companies/{t}/brief` | 第 1 页数据 |
| `GET /companies/{t}/thesis` | 第 2 页：假设 + 每条假设的状态历史 |
| `GET /companies/{t}/fundamentals` | 第 3 页：指标时间序列、价格序列、自身历史分位 |
| `GET /companies/{t}/timeline` | 第 4 页：事件节点 + 假设变化 |
| `GET /companies/{t}/compare?a=&b=` | 两个版本的差异 |
| `GET /reviews/{id}` | 展开某次完整内容（含 token 用量等详情） |
| `GET/POST /companies/{t}/notes` | 笔记 |

# 8. 前端信息架构（Phase B 规格）

单一渲染管线，一个公司一个工作区，顶部一个主按钮"更新"（旁边显示"X 小时前检查，无论点变化"）。

1. **简报**：立场徽章 + 一句话结论 + 论点健康度（每条假设一个状态点）+ "自上次以来的 3 个变化" + 监控指标。一屏读完。
2. **论点**：假设卡片（状态、证据、证伪条件、状态历史小时间线）+ 静态画像与看空论证；完整报告折叠。
3. **基本面**：多期指标 sparkline、估值在自身历史中的位置；风险。
4. **时间线**：纵向节点只显示"日期 + 触发原因 + 立场变化 + 受影响假设"，价格曲线叠加标记，点击展开；选两个节点做差异对比。

视觉：一个主色 + 三个语义色（强化 / 持平 / 弱化）+ 灰阶；亮暗双主题；内部 ID、模型、prompt 版本、token 全部收进"详情"折叠。

# 9. 当前状态与已知限制

- **已验证**：`core/signals.py` 的 7 个单元测试通过（纯 Python）。其余模块通过了语法编译检查。
- **未运行**：本环境没有 FastAPI / SQLAlchemy / Pydantic，也无法联网，所以 API、数据库、Gemini 调用和 `tests/test_service.py` **我没有运行过**。首次运行如遇报错，请把报错贴给我。
- **Gemini 参数**：`AI_MODEL` 请填你账号可用的模型 id（旧版默认值 `gemini-3.8-flash` 我无法确认，所以新版不设默认值）。`response_schema` 对嵌套 / 带约束的 Pydantic 模型的支持因 SDK 版本而异，若报 schema 错误，需要简化约束。
- **数据仍然偏薄**：adapter 没有多期财务序列、价格历史，第 3 页目前只能用自己积累的快照做趋势；补数据是下一步（见路线图）。
- **无数据迁移**：v2 是新库，不读取旧版表；旧版历史报告不会自动导入。
- **无鉴权**：仅适合本地个人使用。

# 10. 路线图

| 阶段 | 内容 |
|---|---|
| A（本次交付） | 后端、数据模型、prompt、变化检测、测试、本文档 |
| B | 4 页前端（单一渲染管线）+ 暗色主题 |
| C | adapter 补多期财务与价格历史；价格叠加时间线 |
| D | 旧版报告导入、季度自动 rebaseline 提醒、导出 |
