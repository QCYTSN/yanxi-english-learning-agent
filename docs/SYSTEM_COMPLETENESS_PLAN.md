# IELTS AI Coach 系统完整性优化计划

状态：V1.4 Architecture V2 已落地，继续作为功能建设权威计划
范围：系统逻辑、四科闭环、Agent、数据治理、可靠性和发布  
不包含：题库内容采购与最终视觉风格

题库数量和题型覆盖由 [CONTENT_ACQUISITION_PLAN.md](CONTENT_ACQUISITION_PLAN.md)
单独管理；最终颜色、字体、动效和品牌视觉在本计划完成主要功能闭环后另行决定。

## 1. 当前产品定位

V1.4 是可发布候选的本地优先 IELTS Academic 学习系统，已经具备：

- 四科入口和结构化 Session；
- SQLite、Session Markdown、Corpus 和 Media 等本地数据真源；
- Writing/Reading 的结构化反馈闭环；
- Speaking Voice/Live 交接和报告导回；
- 高频 Listening `skill_drill`；
- IELTS 内容契约、Assessment Pack、Mock/Manual Adapter；
- revision、幂等、Schema 验证、隐私门和原子保存。

Assessment Pack、完整 Reading/Listening/Writing 运行器、持久化 Tutor 对话和
四科复习闭环均已进入 UI。当前主要缺口是可再分发或用户自有内容、正式安装包发布
验收，以及持续的真实材料可用性和无障碍验证。

本计划的完成目标是：

> 在不改变本地优先和数据权威原则的前提下，通过 Capability 与 Inference Broker
> 解耦学习流程和模型连接，把系统推进为“逻辑完整、结果可信、可恢复、可发布的
> AI IELTS Academic 系统”。

## 2. 不可破坏的产品原则

后续实现必须继续满足以下约束：

1. Runtime、SQLite、Session、Corpus 和 Media 是数据真源，Agent 对话不是。
2. UI 不重复实现 IELTS 教学和评分规则。
3. Writing 保持“证据与估分 → 学习者修改 → 模型替代答案”的顺序。
4. Reading 保持逐级提示、提交后揭晓答案和原文证据解释。
5. Speaking 模考过程中不纠错；Voice/Live 可以是外部主持方。
6. 高频 Listening 只属于 `skill_drill`，不能冒充正式 Listening 测试。
7. AI 分数是带置信度和证据范围的训练估分，不是官方成绩。
8. 未经 Schema、语义和来源验证的 Agent 输出不能写入正式记录。
9. 私有材料未经一次性同意不能交给远程 Agent。
10. 不捆绑 Cambridge IELTS 或商业课程版权内容。

## 3. 完整性的统一定义

一项功能只有同时满足下列条件，才可以标记为“完成”：

- **可进入**：用户能从 Today、Practice、History 或明确入口开始或继续；
- **可执行**：整条流程无需手工编辑数据库、Session 或终端文件；
- **可恢复**：刷新、重复点击、进程重启和 revision 冲突不会静默丢失数据；
- **可验证**：输入、输出、评分、来源和权限均有可执行校验；
- **可解释**：UI 能说明结果来自本地规则、答案键、外部 Agent 还是本地复评；
- **可测试**：正常路径、失败路径和降级路径有自动化验证；
- **可追踪**：正式结果能够追溯到内容版本、Agent/模型、Rubric 和证据。

只有数据库表、Schema、接口或页面空壳，不算功能完成。

## 4. 关键依赖顺序

```text
备份与迁移保护
  ↓
内容审核记录 + Agent 执行来源
  ↓
统一 AssessmentRun / SectionRun / Response
  ↓
Reading / Writing / Listening / Speaking 完整执行器
  ↓
统一 ScoreResult + 校准准入
  ↓
Today / Diagnostic / Progress 闭环
  ↓
真实 Agent Adapter + 发布验收
  ↓
最终视觉设计
```

其中：

- Audio Media Registry 是正式 Listening 的前置条件；
- 内容复核记录是 verified Assessment Pack 的前置条件；
- Agent/模型来源记录是真实 Adapter 的前置条件；
- 备份和迁移保护是新增运行态数据表的前置条件。

## 5. V0.8：可信系统底座

目标：先保证“数据可信、来源可知、失败可恢复”，再扩展完整模考。

### 5.1 数据备份、恢复与迁移保护

实施状态：已完成。已交付可校验 ZIP 快照、SQLite 在线备份/恢复、CLI、Settings
入口、恢复前安全备份、篡改拒绝、旧库迁移前自动备份、跨存储一致性检查和恢复后
健康审计。自动化验收覆盖历史版本迁移、迁移中断后的快照恢复，以及包含四科 Session、
草稿和私有媒体的跨目录恢复。

交付物：

- `ielts-coach backup create/list/verify/restore`；
- UI 中显示数据目录、数据库健康、最近备份和备份按钮；
- Schema 迁移前自动创建可验证备份；
- SQLite、Session、Corpus Manifest、Media metadata 一致性检查；
- 恢复前预检、恢复后 `doctor` 验证；
- 从历史 Schema 版本到当前版本的迁移矩阵测试。

验收条件：

- 可在新临时目录恢复一个包含四科 Session、草稿和私有媒体的数据集；
- 失败恢复不会覆盖原数据；
- 中断迁移后仍能回到迁移前状态。

### 5.2 内容人工审核与可信 Provenance

实施状态：已完成 V0.8 验收。Schema v11 包含独立 `content_reviews` 审核账本；导入文件中的
`review_status` / `conformance_status` 仅保留为来源声明；本地批准绑定完整内容哈希和检查清单；
文章或题目变化会使相关题目与 Pack 自动降级；Library 已提供逐题、逐篇和整套审核工作台；
Import Job 与 Manifest 的 source、authenticity、rights 已强绑定。PDF 页码级证据、音频时间戳
审核和大批量审核效率属于内容获取与 P1 增强，不是 V0.8 可信准入的阻塞项。

交付物：

- 独立的 `content_reviews` 审核记录；
- reviewer、reviewed_at、content_hash、检查项、备注和审核版本；
- Passage、题干、选项、答案、证据定位、说明和版权检查清单；
- 内容哈希变化后自动撤销 verified 状态；
- 逐题/逐篇审核工作台；
- Pack 审核必须引用全部已通过的内容审核记录；
- Import Job 的 source_type、rights_status、authenticity 与 Manifest 强绑定。

验收条件：

- 导入文件不能只靠自声明 `review_status=reviewed` 进入 verified 池；
- UI 中不能通过单个无证据按钮完成整套审核；
- 每个 verified Pack 都能追溯审核人、审核时间和内容哈希。

### 5.3 Agent 和模型执行来源

实施状态：已完成。Schema v11、Agent Gateway、Manual/Mock Adapter、反馈页和 Settings
共同保存并展示运行身份；无法确定的 Provider 或模型保持为“未知”，不会根据启动方式猜测。

每次 AgentRun 至少记录：

```text
adapter_id
agent_provider
agent_version
model_id
model_display_name
agent_session_id
launcher_kind
capabilities_snapshot
started_at / completed_at
token_usage（可获得时）
calibration_status
```

UI 增加运行身份卡：

- 快捷方式直接启动：显示“未连接可调用 Agent”；
- Manual Adapter：显示用户声明的 Agent、模型和结果来源；
- Process Adapter：显示实际 probe 和运行时返回的身份；
- 无法确定模型时明确显示“未知”，不得推测。

验收条件：

- 任一 AI 反馈都能回答“哪个 Adapter、哪个 Agent、哪个模型、何时生成”；
- 本地确定性操作不错误显示为 AI 生成；
- 模型身份未知时仍可使用本地功能，但不能伪造模型名称。

### 5.4 Onboarding、Settings 和 Diagnostic UI

实施状态：已完成。桌面快捷方式会自行初始化/迁移本地数据并启动 UI；首次使用可在浏览器
完成 Academic Profile，之后可在 Settings 修改，并可创建、继续和完成 quick/full Diagnostic。

交付物：

- UI 内完成 Academic 确认、考试日期、目标分、最低单项、当前基线和隐私偏好；
- 用户可以跳过摸底并稍后继续；
- quick/full Diagnostic 在 UI 中创建、附加 Session、显示缺失证据并完成；
- Settings 可修改 Profile，并展示 Rubric、Agent、Storage、Telemetry 和 `doctor` 状态。

验收条件：

- 新用户只使用桌面快捷方式和浏览器即可完成初始化；
- 不要求用户手工运行 `ielts-coach init` 或编辑 YAML；
- 已完成 onboarding 的用户不会被重复询问。

## 6. V0.9：完整考试执行器

目标：让 verified Assessment Pack 从“可登记”变成“可完成、可恢复、可评分”。

实施状态：已完成 V0.9 工程验收。Schema v12 增加统一 `assessment_runs`、
`section_runs` 与 `question_responses`；四科 verified full mock 均通过同一
Runtime 冻结内容、保存进度和提交。Reading/Listening 的答案只在提交后解锁；
Writing 的 1:2 权重由 Runtime 校验和汇总；Speaking 继续由外部 Voice/Live
主持计时，但任务包和结果绑定到同一权威 Session。高质量正式题目与音频的补充
仍按 `CONTENT_ACQUISITION_PLAN.md` 独立推进，不把题量冒充为工程完成度。

### 6.1 统一运行模型

新增或明确以下运行实体：

```text
AssessmentRun
├─ SectionRun
├─ QuestionResponse
├─ TimerState
├─ NavigationState
├─ MediaPlaybackState
├─ SubmissionState
└─ ScoreResult
```

共同要求：

- 统一开始、暂停规则、提交、恢复和超时语义；
- 客户端计时只用于显示，服务端保存权威时间状态；
- 草稿和回答具备 revision 与幂等保护；
- full mock 与 guided practice 的提示、答案、暂停权限严格区分；
- Assessment Pack 内容在开始时固定版本，运行中不能被导入更新替换。

### 6.2 Academic Reading Runner

交付物：

- 三篇文章、40题、统一60分钟；
- Passage 和题号导航、未答标记、检查模式；
- 官方题型对应的输入控件和共享选项池；
- strict 模式禁止提示和提前揭晓；
- guided 模式保留逐级提示；
- 整套提交后统一判分和逐题证据复盘。

答案引擎补充：

- word limit；
- 多选数量和答案顺序规则；
- accepted variants；
- 数字、日期、货币、连字符和大小写正规化；
- 拼写/语法严格度；
- 一题多空和 Matching 选项复用规则。

验收条件：

- verified Reading Pack 可以完整完成并恢复；
- 未提交前不能通过 API 或 UI 获得答案；
- 非完整套题不得生成 Reading Band。

### 6.3 Academic Writing Runner

交付物：

- 同一60分钟 AssessmentRun 中包含 Task 1 和 Task 2；
- 两个独立编辑器状态、字数、草稿、版本和媒体引用；
- 建议20/40分钟但不强制切断任务；
- 分别进行 Task 1/Task 2 证据化评分；
- 最终按1:2汇总 Writing 训练估分；
- 继续保持 V1 → 反馈 → V2 → 可选模型替代的主动学习流程。

验收条件：

- 刷新后两项作文均可恢复；
- Task 2 权重由 Runtime 计算，UI 不自行计算；
- 缺少 Task 1 图片时不能给出完整 TA 估分。

### 6.4 Academic Listening Runner

前置交付：Audio Media Registry。

需要管理：

- 音频文件类型、哈希、时长、路径和隐私状态；
- audio_media_id 与 Part、Transcript、时间戳的关联；
- 是否允许交给当前 Agent；
- 文件变化和丢失检测。

Runner 交付物：

- 四部分、每部分10题；
- 一次播放状态由服务端持久化，刷新不能重置；
- 题目按音频进度展示，支持正式答题和提交后复盘；
- Transcript、证据时间戳、干扰项和错因解释；
- 高频语料库继续作为独立间隔复习模块。

验收条件：

- verified Listening Pack 可以完成40题正式练习；
- 音频只播放一次的规则不能靠刷新绕过；
- 无注册音频的 Pack 不能成为 verified full mock。

### 6.5 Speaking 完整运行记录

保持外部 Voice/Live 为主要主持方式，不强制内置录音或实时语音模型。

交付物：

- 将 Part 1–3 Pack、外部任务包、时间要求和导回结果绑定到同一 AssessmentRun；
- Part 2 与 Part 3 主题关联校验；
- 模考任务包明确要求中途不纠错；
- Transcript、外部模型观察和本地复评分层保存；
- 只有音频或明确 voice-model observation 时才允许 PRON 数字估分。

可选后续：本地 STT 或音频证据导入，不作为 V0.9 阻塞项。

验收条件：

- 一次完整 Speaking 模考只有一个权威 Session/AssessmentRun；
- 外部模型分数不会直接冒充本地 IELTS 复评；
- 只有文字证据时明确标记 Pronunciation 证据不足。

## 7. V1.0：AI 学习闭环与发布

实施状态：已完成当前本地工程实现并升级到 Schema v32。统一 ScoreResult 准入、
九类 Agent 输出契约、持久化后台任务、Claude/OpenCode 本地进程边界、
Writing 双任务复评、Task 1 受控图片附件、Listening 播放租约、Speaking 同运行复评、
Runtime 驱动的 Today、`PracticeUnit / AssessmentRun / ReviewTask`、统一待复习队列、
真实趋势图、结构化周报、Capability Registry、Execution Profile、Inference Broker
和隔离的 Codex managed runtime 已交付。正式题库数量仍由
`CONTENT_ACQUISITION_PLAN.md` 独立管理；最终品牌视觉仍按原计划后置。

### 7.1 统一 ScoreResult 与评分准入

实施状态：已完成。所有正式分数趋势、学习画像、近期 Band 与分项分配均调用
`score_results.build_score_result` 的同一准入规则。训练观察仍保留，但会与
`eligible_for_progress` 可信样本分开显示。

统一结果结构：

```text
raw_score
band / band_range
score_kind
confidence
rubric_version
conversion_source
evidence_scope
evaluator_model
calibration_status
eligible_for_progress
```

规则：

- 只有 verified full mock 和有来源的转换表可以将 Reading/Listening raw score 转为 Band；
- Writing 完整测试按 Task 1/Task 2 的1:2结果汇总；
- Speaking 本地总分必须具备四项标准和足够语音证据；
- 低置信度或未校准 AI 估分不进入正式趋势，只进入训练观察；
- 所有页面使用同一评分准入函数，不各自判断。

### 7.2 扩展 Agent 输出契约

实施状态：已完成。七类 `@1` 契约均具备 JSON Schema、语义校验、明确的未知
版本拒绝策略，以及 `tests/fixtures/agent_contracts` 中的 golden/failure 样例。

在现有契约之外增加：

- `listening-review@1`；
- `speaking-evaluation@1`；
- `study-plan@1`；
- `diagnostic-summary@1`；
- `weekly-coaching@1`。

所有契约需要 JSON Schema、语义验证、版本兼容策略、golden fixtures 和失败样例。

### 7.3 真正的 Agent 生命周期

实施状态：已完成。Agent 请求使用 SQLite 状态作为真源并在后台线程执行，
具备超时、取消、重试、幂等、heartbeat、恢复动作、服务重启中断识别以及
支持 `Last-Event-ID`/`after` 游标的 SSE。

统一状态：

```text
queued → running → validating → persisting → persisted
                  ↘ failed / cancelled / awaiting_import
```

交付物：

- 后台任务而不是请求内同步执行；
- 进程句柄、超时、取消、重试、幂等和恢复；
- UI 关闭后任务可继续；
- 服务重启后可识别未完成任务；
- SSE 发送真实运行进度；
- 错误给出恢复动作，而不是只显示通用失败。

### 7.4 Process Adapter

实施状态：已完成受控本地进程边界。Claude Code 与 OpenCode 仅在 CLI probe
可用且用户显式点击、完成隐私同意时启动；使用参数数组而非 shell，限制工具
权限，并把结果送回统一 Schema/语义/原子保存链。Codex 桌面会话仍不被猜测或
反向控制，继续使用 Manual Adapter。

建议顺序：

1. MockAdapter；
2. ManualAdapter；
3. 经能力和安全测试的 OpenCode Adapter；
4. 经能力和安全测试的 Claude Adapter；
5. Codex 只有在发现稳定可调用本地接口后再评估原生 Adapter。

每个 Adapter 必须验证 probe、结构化输出、隐私、超时、取消、恢复、图片/音频能力和
模型身份。桌面快捷方式继续只启动本地 UI，不静默启动未知 Agent。

### 7.5 Today、Progress 和学习决策闭环

实施状态：已完成。Today 使用 `study-context` v2 产生 70% 弱项任务与 30%
巩固任务，并显示原因、时长、目标差距、内容可用性与降级路径。Progress
提供四科样本/趋势、写口分项、阅读题型/耗时、听力场景/错因、错误状态和
下一周期分配；不把未准入 AI 观察冒充可信趋势。

Today 必须真正使用 Runtime 的 `study-context`，而不是只提供四科静态入口。

应显示：

- 今日优先科目和推荐任务；
- 推荐原因、预计时间和目标差距；
- 70%弱项任务与30%巩固任务；
- 当前内容是否可用；
- 没有 verified Pack 时的明确降级任务。

Progress 应展示：

- 四科趋势和样本量；
- Writing/Speaking 分项；
- Reading 题型正确率和耗时；
- Listening 场景、拼写、定位和干扰项错误；
- active/monitoring/resolved 错误；
- 周报、目标差距和下一周期分配。

### 7.6 发布质量门

实施状态：已建立并收紧自动门禁。CI 覆盖 Windows/Linux 与 Python 3.10–3.12；
Python 兼容矩阵与单独的全量回归任务分开执行；前端 typecheck/lint/Vitest/build
和真实 Chromium Playwright 不再允许因缺少启动地址而静默跳过；wheel 版本从构建
产物动态读取，不再硬编码。CLI doctor、Skill 同步和 wheel 安装冒烟均保留；本地
故障测试覆盖迁移中断、备份篡改、磁盘写满、Agent 超时、服务重启与 revision 冲突。

V1.0 发布前必须通过：

- Python 3.10–3.12 基础矩阵；
- Windows 和 Linux Runtime 测试；
- 前端 typecheck、lint、Vitest 和 production build；
- Playwright：onboarding、恢复、Writing V1/V2、Reading strict、Listening 一次播放、
  Speaking 导回、隐私确认、revision 冲突和备份恢复；
- 每个 Schema 版本到当前版本的迁移测试；
- 数据库损坏、磁盘写满、Agent 超时和服务中断测试；
- wheel 安装、静态文件、Windows 快捷方式和卸载说明；
- `init`、`sync-skills`、`doctor` 全通过。
- 全部 Agent Contract 正反例通过，并保存不含学习正文的评测记录；
- 10k Session / 100k Question 合成规模门通过。

全量 Python 回归已设置独立超时并输出慢测试排行；下一步根据 CI 数据继续拆分
unit、integration 和 UI API，不再让兼容矩阵重复承担完整回归成本。

## 8. P1/P2 持续优化清单

这些工作不能遗忘，但不应打断上面的关键路径。

### P1：功能完整性

- PDF 准备、隔离 OCR、页角色审核、页码级来源、Passage/Question/Answer Key 草稿
  转换已经交付；草稿仍须人工审核后才能进入正式题库；
- 音频波形、Transcript 和时间戳审核已经交付；
- 阅读逐题耗时、文章级耗时和改答记录；
- stale revision 的“载入新版/比较差异”恢复界面；
- 内容导入的重试、确认删除、批量处理、流式暂存和磁盘配额已经交付；
- 可发现的键盘快捷键和完整键盘操作；
- 报告中区分真实进步、样本不足和题目难度变化。

### P2：发布和长期维护

- 结构化、无学习正文的诊断包已经交付；后续只按真实支持案例扩充诊断字段；
- Agent 延迟、失败率和可选 token metadata 统计；
- 自动检查文档声明与代码能力是否一致；
- 可选桌面壳评估；
- 有足够真实学习数据后再考虑只读 Dashboard；
- 最终视觉系统、暗色模式和动效规范。

## 9. 明确不进入当前路线的事项

以下内容继续保持 deferred，除非另行进行产品决策：

- 账号、登录、支付、云同步和多用户；
- RAG、向量数据库、微调；
- 自主多 Agent 编排；
- 自动启动或控制没有稳定编程接口的桌面 Agent；
- 强制内置实时语音模型；
- 移动端原生应用。

## 10. 进度维护规则

为避免计划再次失真：

1. 本文是系统完整性建设的权威清单；`ROADMAP.md` 只保留版本摘要和链接。
2. 每项进入开发前，需要拆成可独立验收的任务，并引用本文章节。
3. 标记完成时必须同时更新代码、测试、本文状态和 `ROADMAP.md`。
4. 只有满足第3节完整性定义和对应验收条件，才能写入 Delivered。
5. 题库数量只更新 `CONTENT_ACQUISITION_PLAN.md`，避免和工程完成度混写。
6. 最终 UI 视觉方案单独成文，不在功能实现过程中被临时决定。

## 11. 推荐执行顺序

当前已完成：

1. 依据 Architecture V2 重构稳定 Workspace Shell 和 feature modules；
2. Learner Library 与 Content Studio 分离，学习主导航不暴露内容工程控件；
3. AI 与内容导入采用持久化后台任务状态，备份保持独立可恢复流程；
4. 主要路由懒加载、长列表分页与前端资源预算基础；
5. PDF 页级预览、解析、隔离 OCR、页角色审核和结构化草稿；
6. 音频波形、Transcript 和时间戳审核；
7. 导入重试/删除、批量处理、流式上传、磁盘配额和媒体垃圾回收；
8. 10k Session / 100k Question 性能基准；
9. SQLite FTS5 历史检索、预算化 Context Engine 与来源追踪；
10. Provider 重试、流式响应、健康状态、熔断、进程隔离和脱敏诊断包。
11. Learning Agent Kernel、版本化记忆、教学状态机和教学质量发布门。

下一批按以下顺序推进：

1. 正式题库内容按 `CONTENT_ACQUISITION_PLAN.md` 独立补充并人工审核；
2. 使用真实长文章、完整套题、长对话和大附件完成端到端验收；
3. 完成键盘、200% 缩放、低分辨率和辅助技术走查；
4. 根据真实使用数据补齐阅读计时、revision 冲突比较和报告置信度表达；
5. 在独立干净 Windows 环境验收安装、升级、快捷方式与卸载；
6. 只在性能预算被真实数据突破时评估新语言、独立服务或桌面壳。
