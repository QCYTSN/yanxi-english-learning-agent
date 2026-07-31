# 高质量四科内容补充计划

状态：2026-07-30 实测盘点。本文只管理题库数量、来源、质量门槛和导入顺序；
工程完成度由 `SYSTEM_COMPLETENESS_PLAN.md` 管理。

实时缺口可通过以下命令查看：

```powershell
ielts-coach content readiness --home <path-to-ielts-home>
```

## 1. 内容权威边界

- 项目仓库不打包、不分发 Cambridge IELTS 或商业课程材料。
- 用户合法持有的材料可以作为 `licensed_private` 保存在本机数据目录。
- OCR、Transcript 和页面角色识别只生成待审核草稿，不能直接进入正式题库。
- 每道正式题都必须保留来源、版本、页码或时间戳、文件哈希、权利状态和审核记录。
- `official_external`、高质量民间题、项目原创题必须分层显示，不能把民间题称为官方题。
- IELTS Academic 与 General Training 分开；本产品的正式训练池只接收 Academic。

## 2. 当前本地正式题库缺口

| 科目 | 当前 | 最低可用目标 | 推荐目标 | 当前关键缺口 |
|---|---:|---:|---:|---|
| Reading 完整套题 | 0 套 | 8 套 | 20 套 | 3 篇 / 40 题 / 60 分钟的审核 Pack |
| Reading 篇章 | 0 篇 | 24 篇 | 60 篇 | 原文、题目、答案、定位证据 |
| Reading 客观题 | 16 题 | 320 题 | 800 题 | diagram、flow chart、matching endings、note |
| Listening 完整套题 | 0 套 | 8 套 | 20 套 | 4 Part 音频、Transcript、答案 |
| Listening 音频 Part | 0 个 | 32 个 | 80 个 | 音频与题目、时间戳的稳定绑定 |
| Listening 客观题 | 0 题 | 320 题 | 800 题 | 全部正式题型覆盖 |
| Writing Task 1 | 3 题 | 56 题 | 105 题 | line、bar、pie、map、mixed |
| Writing Task 2 | 8 题 | 100 题 | 200 题 | 主题与题型均衡 |
| Speaking Part 1 主题组 | 0 组 | 30 组 | 60 组 | 日常高频主题组 |
| Speaking Part 2–3 关联组 | 4 组 | 60 组 | 120 组 | Cue Card 与 Part 3 关联 |

这些数量是产品的抗重复与覆盖目标，不是 IELTS 官方规定。

## 3. 本地私有材料盘点

私有材料只执行本机文件级盘点、哈希检查和页数或时长读取，不复制进仓库。
用户确认有权使用后，系统仍只按 `licensed_private`、`local_private` 处理：
可以复制到本机私有 inbox 供个人审核，但不得打包进仓库或公开再分发。

初步判断：

- 文件名覆盖 Cambridge 4–21；当前优先范围 15–21。
- 15–19 同时存在大体积版本和较小的“真题”版本；没有发现 SHA-256 完全相同的
  文件，但是否为内容重复或不同扫描版本仍需人工选择。
- Academic 15–19 的较小 PDF 均未加密，适合作为首批私有审核源。
- Cambridge 20 当前只有 Test 1–3 PDF，缺 Test 4。
- Cambridge 20 当前音频文件名只有 Test 1 Section 1、3、4，缺 Section 2，
  因此不能组成完整 Listening Test。
- Cambridge 21 Academic PDF 共 146 页，内部带 Standard Security 权限字典，
  但空用户密码即可解锁；打开、渲染和文字提取均已实测成功，不需要用户另行
  提供密码。General Training 文件不进入 Academic 正式池。
- Cambridge 21 音频有 Test 1–4、每套 Part 1–4，共 16 个文件，是当前最完整的
  Listening 音频批次。
- 当前外部目录没有从文件名可确认的高质量民间题库包；这部分仍需单独收集、
  标注来源并人工审查。

已登记的首批本地私有内容：

- 剑15–19 Academic PDF 各一批；
- 剑20 Academic Test 1–3 PDF 各一批；
- 剑21 Academic PDF 一批；
- 剑21 Listening Test 1–4 音频四批，每批四个 Part；
- 剑20 Listening Test 1 现有 Part 1、3、4 三批。

共 16 个本地私有批次、853,804,961 bytes，占 10 GiB inbox 配额约 7.95%。
其中 9 个 PDF 批次已生成分科 `draft_ready` 审核草稿；音频批次仍保持独立审核状态。
所有内容均尚未进入正式 Corpus。

PDF 预分析结果：

| 材料 | 页数 | 需要 OCR |
|---|---:|---:|
| 剑15 Academic | 145 | 1 |
| 剑16 Academic | 144 | 144 |
| 剑17 Academic | 144 | 0 |
| 剑18 Academic | 147 | 147 |
| 剑19 Academic | 147 | 147 |
| 剑20 Test 1 | 34 | 34 |
| 剑20 Test 2 | 35 | 35 |
| 剑20 Test 3 | 31 | 31 |
| 剑21 Academic | 146 | 146 |

剑21的权限字典允许空密码读取；系统已正确标记为
`empty_password_permissions`，而不是 `password_required`。

### 剑15–21 三科首轮处理结果

已完成：

- 剑15、16、17、18、19、21 每册四套，以及剑20 Test 1–3，共 27 套；
- 对 353 个 Reading 页面统一使用英文识别模型重新 OCR；本轮不以 Listening
  音频完整性作为阻断；
- 27 套均生成独立 Reading、Writing Task 1/2、Speaking Part 1–3 和 Answer Key
  审核草稿；
- 27/27 套 Reading 均确认 3 篇与完整 1–40 题号范围，共 81 篇、1080 个题号；
  所有题组已映射到正式 IELTS 题型族，没有 unknown 题型、题号重叠或漏号；
- 26/27 套 Reading 已完成 1–40 答案候选映射；
- 54 个 Writing Task 均完成人工题干清理与 150/250 字标记复核；27 个 Task 1
  视觉均已登记到本地 Media Registry 并通过哈希解析；
- 27 套 Speaking 均检测到 Part 1–3，27 个 Part 2 均已结构化为 Cue Card
  主题与提示点；草稿固定保留“模考中不纠错”策略；
- 剑15 Test 4、剑16 Test 3、剑19 Test 2 的答案键 OCR 漏号已通过 PDF
  页面核图修正，修正记录仍保持 `needs_review`；
- OCR 连写的 `Questions 1822` 等题号标题已按当前 Passage 合法题号范围
  确定性还原；整篇计时说明不会被误识别为题组；
- 内容工作台现在显示材料级审核问题、页码、证据和 blocker 数量。

已确认的阻断项：

- 剑20 Test 3 的来源答案页重复显示题号 28、缺少题号 27，必须用独立可靠
  答案源复核，不能按推断静默修正；
- 剑20 Test 1 的 Speaking Part 3 源页声明六个问题，但当前文件只包含第一个，
  必须由完整可靠来源补齐，不能由模型编造。

已记录但不阻断结构审核的事项：

- 剑20 Test 1 的阅读答案 1–10 与阅读题共页，已通过人工证据覆盖完成映射，
  保留跨页切分记录；
- 剑20 Test 3 的若干题号段已通过页面证据和确定性范围覆盖恢复，保留人工
  结构覆盖记录；
- 剑20 三份 PDF 混有考生样文、中文点评和口语示范回答，这些页不进入默认
  学习流程；同页混排处已显式标记人工切分；
- 剑17、剑19 存在第三方水印或插页，正式批准前需与干净版本抽样核对。

### 剑15–21 私有结构化导入状态（2026-07-30）

第一轮 OCR 草稿已经经过确定性结构检查，并以 `licensed_private`、
`local_private` 形式进入用户本机 Corpus。仓库不包含这些题目或原文。

- 已索引 75 篇 Reading Passage、1000 道 Reading 题；
- 其中 21 套满足当前三篇、40 题和篇章字数轮廓，另 4 套只标为
  `section_practice`，不会冒充完整可计分模考；
- 已索引 54 道 Writing Task，27 道 Task 1 均引用 Media Registry 原图；
- 已索引 283 道 Speaking 题，包含 26 张结构化 Cue Card 及其 Part 3 关联；
- 共生成 78 个 Assessment Pack，全部保持 `in_review` / provisional，
  未经本地人工内容批准前不得用于正式 Band 换算。

仍被隔离、没有猜测补全的内容：

- 剑20 Test 1 Reading：题组 7–13 的来源页缺少可确认的作答词数说明；
- 剑20 Test 1 Speaking：Part 3 来源不完整；
- 剑20 Test 3 Reading：答案页缺 27、重复 28。

答案页视觉复核还修正了三组 “IN EITHER ORDER” 以及剑15 Test 4 第 7 题
“两个词共同计一分”的约束。结构化包保存正确答案、可接受变体和禁止重复
选项规则，但 UI 在提交前继续隐藏答案。

### 剑21 Test 1 初期工作流留档

初期样例曾完成：

- 在用户的 `IELTS_HOME` 下安装隔离本地 OCR 运行时；
- OCR 封面/目录小样、Test 1 全部题页以及对应 Audioscript、Answer Key 和
  Sample Writing 边界页；
- Test 1 主体 22 页 OCR 全部成功，平均置信度约 0.977；
- 保存 3 个 Reading Passage、15 个逐页 Question、1 个 Task 1 Visual、
  1 个 Transcript 和 1 个 Answer Key 草稿；
- 将 Test 1 Audioscript 初步拆分并绑定到四个本地音频 Part。

此后 Reading、Writing 和 Speaking 已纳入上面的 27 套统一审核。Listening
仍需人工完成：

- 在音频播放器中校对四份 Transcript 并添加题目证据时间戳；
- 把 Listening Answer Key 映射到 40 道题；
- 通过音频、Transcript、时间戳和答案的完整一致性检查后，才能生成正式
  Listening Assessment Pack。

当前所有草稿仍为 `needs_review`、`eligible_for_import=false`。

## 4. 首批私有内容导入顺序

### Batch A：Cambridge 21 Academic

1. 用户确认拥有材料；该 PDF 可用空密码读取，不需要额外解密密码。
2. 登记 Academic PDF 和 16 个音频文件的哈希与权利状态。
3. PDF 按 Test / Listening / Reading / Writing / Answer 分页分类。
4. 对扫描页运行本地 OCR，生成 Passage、Question、Answer Key、Task Visual 草稿。
5. 为 Listening 音频校对 Transcript 和题目证据时间戳。
6. 人工复核四套 Pack，只有四个 Part 或三篇 Reading 完整时才标记 full mock。

### Batch B：Cambridge 20

1. 先导入 Test 1–3 PDF 作为不完整审核批次。
2. 在补齐 Test 4 和 Test 1 Section 2 音频之前，不进入完整套题池。
3. 大体积音频需先核对是否为正确导出、是否包含多段拼接。

### Batch C：Cambridge 15–19

1. 每个版本先选择一个清晰、可提取、页码稳定的 PDF，避免重复 OCR。
2. 按 15 → 19 顺序，每卷逐 Test 审核，不一次性把整批标为已验证。
3. 缺少 Listening 音频时，只能先完成 Reading 与 Writing 内容；Listening Pack
   保持不完整状态。

### Batch D：高质量民间题与项目原创题

1. 优先补官方私有批次仍缺少的题型和主题。
2. 民间题必须记录发布者、链接或文件来源、权利状态和审核者。
3. 项目原创题至少经过一次独立作答、答案证据检查和难度复核。
4. 未经完整复核的内容只能进入 `skill_drill` 或 `guided_practice`，不能用于
   正式 Band 换算。

## 5. 四科正式内容质量门槛

### Reading

- 完整套题必须是 3 篇、40 题、60 分钟。
- 题型必须映射到 IELTS 正式题型族，不自创“排序题”名称。
- 每题保存 instructions、word limit、options、answer key、accepted variants、
  evidence location 和 explanation。
- 提交前保持答案锁；完整套题与单篇题型训练分开。

### Listening

- 完整套题必须是 4 Part、40 题，并绑定可播放的本地音频。
- 每 Part 保存 Transcript、题目证据时间戳、答案、word limit。
- 正式模考保留一次播放约束；高频语料库仍是独立 `skill_drill`。

### Writing

- Task 1 必须有完整可读图表或结构化数据、单位、时间范围和最少字数。
- Task 2 需要题型和主题均衡；题目质量与范文质量分开审核。
- 模型评分只作带置信度的估分，继续执行 V1 → 证据反馈 → V2 → 可选范文。

### Speaking

- Part 1 按主题组保存，不存成互不关联的孤立问题。
- Part 2 使用结构化 Cue Card；Part 3 必须通过 `speaking_set_id` 关联。
- Mock 中途不纠错；外部 Voice/Live 的 Transcript 和报告需导回同一 Session。

## 6. 工程导入链

```text
用户上传或登记本地文件
→ 哈希、来源、权利与隐私登记
→ PDF 解析 / 隔离 OCR / 音频波形
→ 页面角色、Transcript、时间戳审核
→ Passage / Question / Answer / Media 草稿
→ Schema 与 IELTS conformance 检查
→ 人工复核
→ 正式本地 Corpus
→ Assessment Pack
→ 按资格进入 full mock / practice / skill drill
```

失败任务可以重试或在明确确认后批量删除；内容工作区默认配额为 10 GiB。导入
完成的正式 Corpus 不允许通过“删除上传任务”旁路删除，必须走题库治理流程。

## 7. 完成标准

“补充正式高质量四科内容”只有同时满足以下条件才算完成：

1. 达到上表最低可用目标；
2. 四科正式题型与主要主题没有关键空白；
3. 每条内容具备来源、权利、哈希和人工复核证据；
4. Reading/Listening 完整 Pack 可在 Runner 中从开始、暂停限制、提交到复盘走通；
5. 没有把商业原文打包进仓库或公开发布物；
6. UI 能区分官方私有、高质量第三方、原创、草稿和不完整内容。
