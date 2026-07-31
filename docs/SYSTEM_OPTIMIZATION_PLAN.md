# IELTS AI Coach 系统优化与扩展计划

更新日期：2026-07-24

本文是产品完整性、运行流畅度和技术演进的执行基线。视觉方案不在本文范围内。

## 1. 冻结的系统边界

```text
React + TypeScript UI
        ↓ HTTP / SSE
FastAPI Local App Service
        ↓
Python IELTS Runtime ── Agent Gateway
        ↓                    ↓
SQLite / Session / Corpus    CLI / Manual Adapter
```

- SQLite、Session Markdown、Corpus 和 Media Registry 是数据真源。
- UI 不实现第二套 IELTS 评分、答案或教学规则。
- FastAPI 是本地应用服务；模型和 Agent 连接统一经过 Inference Broker。
- Agent 输出必须通过 Schema、语义、revision 和幂等校验后才能写入正式记录。
- 明确操作直接路由到专用 Skill；自由输入才使用总路由。

## 2. 性能目标

本机基准以持续使用三年以上为设计范围：

| 场景 | 目标 |
|---|---:|
| 普通只读 API p50 | 小于 80 ms |
| 普通只读 API p95 | 小于 250 ms |
| 本地写入 p95 | 小于 400 ms |
| 首页可交互 | 小于 1.5 s |
| 10,000 Session 历史检索 | 不全表扫描、不一次性传输 |
| 100,000 题题库浏览 | 分页、过滤和批量读取 |
| Agent / PDF 等重任务 | 不阻塞 UI 请求线程 |

设置页的“本地运行容量”显示滚动请求延迟、慢路由、SQLite 模式、数据库大小和主要表规模。性能结论必须来自这些数据和可复现基准，不凭语言偏好判断。

## 3. 当前已完成的性能底座

- Schema v18；
- SQLite WAL、10 秒 busy timeout、NORMAL synchronous、32 MiB page cache；
- `sessions`、`errors`、Media owner 等增长路径索引；
- 修复 Python `sqlite3.Connection` 上下文只提交不关闭的句柄泄漏；
- Reading 整篇和选项批量读取，取消逐题连接；
- 题库与套题审核状态批量解析，取消列表 N+1 查询；
- Agent Run 列表单次查询；
- Bootstrap 直接查询最新活动 Session；
- 未变化的内置 Corpus 启动时只做完整性计数，不再重复逐题索引（本机复测约 3 秒降至 0.15 秒）；
- CLI 版本探测 60 秒缓存；
- 有界内存性能监视器，不记录作文、题目或提示词；
- Media Asset 与 owner 解耦，同一文件可绑定多个 Session。

## 4. 当前已完成的学习闭环修正

- 模考时间到后冻结答案并自动提交，提交区域不再消失；
- 完整 Writing 评分不再默认预填 6 分，必须导入真实评阅来源、两项证据和全部标准分项；
- Reading 三级提示返回实际策略内容，并绑定当前题目，始终标记 `answer_revealed=false`；
- Speaking 仅导入转写时进入 `awaiting_feedback`，可继续调用 `speaking-evaluation@1`；
- Session 媒体会进入 Agent request 的结构化证据清单；不支持图片/音频的 Adapter 明确标记证据不可用；
- 设置页提供无 Token 的 CLI、版本与代理继承预检，并明确它不等于真实模型连通。

## 5. V1.1 已完成的可信学习闭环

- `writing-mock-review@1` 将 Task 1 与 Task 2 的证据、四项标准分和重点问题分开保存，由 Runtime 计算 1:2 总分；
- Task 1 图片只从 Media Registry 复制到一次性受控附件目录。OpenCode 使用 CLI `--file`，Manual 生成包含清单的任务包；Claude Code 本机 CLI 不支持本地路径附件，因此保持 `image_input=false`；
- Task 1 没有实际图片附件或结构化数据时，TA 必须为 `null`，AssessmentRun 保持待复评且不生成完整总分；
- Listening 使用 AssessmentRun 专属的 20 分钟播放租约，允许浏览器 Range 请求、刷新续租和断点续播，旧租约会撤销且不能跨运行复用；
- Speaking 外部 Voice / Live 报告只作为来源证据，必须再运行 `speaking-evaluation@1`，最后在同一 AssessmentRun 中结束；
- Schema v15 新增播放租约持久化，V1.0 数据可向后兼容迁移。

## 6. V1.2 已完成的学习编排层

- `PracticeUnit`、`AssessmentRun`、`ReviewTask` 已成为独立、可持久化、可关联的一等领域对象；
- Today 的主任务、巩固任务和摸底入口会幂等创建正式学习单元，而不是只生成一个页面链接；
- Session、完整模考和 Diagnostic 可以反向绑定所属 PracticeUnit，完成时同步关闭相关学习单元；
- 统一 Review Queue 从正式数据自动汇总活动错误、到期 Listening 语料、Writing V2 和 Reading 错题；
- Today 显示前三项到期复习，History/Progress 提供完整队列、开始和完成操作；
- Settings 对旧版或部分性能响应进行安全归一化，全局页面错误边界提供可恢复入口。

## 7. V1.3 已完成的进度决策闭环

- 四科 Progress 使用真实折线图展示趋势，可信成绩与训练观察使用不同视觉和统计口径；
- 趋势方向、阶段均值与目标差距只由统一 ScoreResult 准入后的成绩计算；
- 七天结构化周报汇总正式 Session、PracticeUnit、复习完成量、证据充分性、进展与风险；
- 周报按 ISO 周幂等保存到 Schema v17 `weekly_reports`，支持本地历史回看；
- 错误收件箱合并科目、标签、状态与出现次数，不再只显示状态总数；
- “下一步”根据到期复习、摸底状态、目标差距和 70/30 分配生成，并幂等创建正式 PracticeUnit。

## 8. 仍需完成的产品工作

### V1.4 已完成的执行架构

- 八个内部 Capability 将教学工作流与模型、CLI 和页面解耦；
- Execution Profile 持久化后端类型、传输、认证、模型和推理强度，但不保存密钥；
- Inference Broker 统一托管 managed runtime、外部 CLI、Manual 和 Mock；
- 官方 Codex app-server 支持独立 ChatGPT/API Key 登录、模型列表、结构化输出、媒体和取消；
- 独立 `CODEX_HOME` 避免修改其他终端的 Codex 认证；
- Schema v18 为 Agent Run 增加能力和执行来源追踪；
- SQLite WAL 继续作为本地正式数据库，Docker/WSL 只作为未来可选 worker/CI 边界。

### P1：从工具集合升级为学习系统

1. Learner Library 与 Content Studio 分离；
2. Content Studio 增加 PDF 预览、结构化进度、校验错误定位和人工审核工作台；
3. 所有长列表改为游标分页，前端使用虚拟列表或窗口化渲染；
4. 大型导入、PDF 解析、备份和媒体分析进入可恢复后台任务队列。

### P2：规模化和桌面体验

1. 建立 10k Session / 100k Question 合成数据基准；
2. 增加 SQLite 查询计划回归测试和慢查询阈值；
3. 前端路由分包、懒加载、资源预算和长任务监控；
4. 增量备份、数据库维护建议与存储配额；
5. 快捷方式启动器显示服务、Agent、模型和代理状态；
6. 视觉设计系统和最终交互优化。

## 9. 是否新增 Rust、Go 或其他语言

当前不新增语言。原因不是 Python/TypeScript 永远足够，而是现有瓶颈来自连接生命周期、N+1 查询、无分页和重任务边界；这些问题换语言仍然存在。

满足以下条件之一才启动原生技术评估：

- 相同输入的 CPU profile 显示单个纯计算热点长期占用超过 30% 总运行时间；
- 100k 题基准在索引、分页和批量查询后仍无法达到 p95 目标；
- PDF/OCR/音频处理单任务超过 5 秒且影响其他本地请求；
- 需要跨进程可恢复任务，而 Python worker 无法达到稳定性目标。

候选边界：

- Rust：PDF 文本归一化、音频特征、哈希/去重、CPU 密集解析，优先以可选 Python 扩展或独立 worker 接入；
- Go：只有在需要长期运行的多进程任务调度或独立本地守护进程时评估；
- 前端继续 TypeScript。WebAssembly 只用于经 profile 证明的浏览器 CPU 热点。

无论新增何种语言，都不能复制 IELTS 规则、绕过 Schema、直接写数据库或改变数据权威关系。

## 10. 验收闸门

每一阶段必须同时通过：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest -q
ielts-coach init
ielts-coach sync-skills
ielts-coach doctor
cd frontend
npm run typecheck
npm run test
npm run build
```

性能相关改动还必须提供测试规模、p50/p95、查询次数或 CPU profile 证据。
