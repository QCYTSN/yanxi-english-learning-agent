# IELTS AI Coach

面向 **IELTS Academic** 的本地优先、Agent 原生开源学习系统。

Claude Code、Codex 或 OpenCode 负责模型推理；本项目提供六个 Agent
Skills、结构化学习流程、本地 SQLite、题库索引、错误与能力画像、动态
70/30 计划和版权安全的 BYOC（Bring Your Own Corpus）机制。

它不是剑桥雅思盗版资源包，也不会启动后再额外调用一个模型 API。

## V0.3.0 已实现

### 六个 Skill

- `ielts`：统一入口、摸底、每日任务和路由
- `ielts-writing`：审题、证据估分、主动修改、V1/V2、结构化分项记录
- `ielts-speaking`：个人故事库、模考、Voice 交接、报告导入和复盘
- `ielts-reading`：引导做题、错题精讲、题型专项、精读和语境解析
- `ielts-progress`：四科记录、听力复盘、错误/能力/行为画像和动态分配
- `ielts-corpus`：语料登记、题目索引、检索、抽题、去重和来源管理

### 本地系统

- `IELTS_HOME` 初始化与 SQLite 数据库
- Claude Code、Codex、OpenCode 三端 Skill 同步
- 题目、文章、选项、答题尝试与题目级 Provenance
- Writing V1/V2/Final 与 TA/TR、CC、LR、GRA 结构化存储
- Reading 逐题答案、定位、耗时和错误标签
- Speaking Voice/Live 观察、来源模型临时估分、本地 IELTS 标准复评三层分离
- Session 自动创建、状态迁移、完成、查看和列表
- 首次使用 onboarding 状态与目标/最低要求/基线配置
- 分数来源、证据类型、置信度与官方 Rubric 记录
- 错误 `active / monitoring / resolved` 状态
- 错误、能力、行为三层学习画像
- 分数、分项和阅读题型趋势报告
- 受控 70/30 动态分配及历史记录
- 评分校准结果登记与 MAE/±0.5 通过率报告
- 原创 Starter Corpus：Writing、Speaking，以及 4 篇原创阅读文章和 16 道阅读题

## 明确不包含

- Cambridge IELTS 原题、音频或机构付费题库
- 盗版资料下载入口
- 独立模型 API 后端
- 前端、登录、云同步或多用户系统
- 自动语音识别和真实声学发音评分
- RAG、向量数据库、微调或自主多 Agent 编排
- 未经校准便冒充官方考官的分数

## 安装

```powershell
cd D:\Github_Ku\ielts-ai-coach
conda create -n ielts-coach python=3.12 -y
conda activate ielts-coach
python -m pip install -e .

[Environment]::SetEnvironmentVariable("IELTS_HOME", "D:\IELTS_AI\data", "User")
```

重新打开 PowerShell：

```powershell
cd D:\Github_Ku\ielts-ai-coach
conda activate ielts-coach
ielts-coach init
ielts-coach sync-skills
ielts-coach doctor
```

贡献者如需运行测试，请安装开发依赖：

```powershell
python -m pip install -e ".[dev]"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest -q
```

## 启动学习

Claude Code：

```text
/ielts
```

Codex：

```text
$ielts 读取我的目标和最近记录，开始今天的训练。
```

OpenCode：从项目根目录启动后，让 Agent 加载 `ielts` skill。

## 常用命令

```powershell
# 题库
ielts-coach corpus list
ielts-coach corpus stats
ielts-coach question search "technology" --module reading
ielts-coach question draw --module writing --task task2 --exclude-completed
ielts-coach question show START-R-003

# Session
ielts-coach session start reading --question-id START-R-003
ielts-coach session transition D:\IELTS_AI\data\sessions\reading\R-YYYYMMDD-001.md learner_working
ielts-coach session finish D:\IELTS_AI\data\sessions\reading\R-YYYYMMDD-001.md
ielts-coach session list

# 首次设置
ielts-coach onboarding status
ielts-coach onboarding complete --setup-file onboarding.yaml

# 分析
ielts-coach summary --days 14
ielts-coach learning-profile
ielts-coach trends
ielts-coach allocation
ielts-coach weekly-report

# 错误、故事与校准
ielts-coach error list
ielts-coach error set-status GRA_ARTICLE resolved
ielts-coach story add story.yaml
ielts-coach speaking import-report voice-report.md
ielts-coach calibration record calibration.yaml
ielts-coach calibration report
```

## 核心策略

默认目标：Listening 8.0、Reading 8.0、Writing 6.5、Speaking 6.0、Overall
7.0。默认学习时间为 35/35/20/10，保持“听读拉总分、写口守单项”，但系统
会根据最低单项、近期成绩、分项风险、练习间隔和上一周期分配进行受控调整。

## 文档

- [产品范围](docs/00_PRODUCT_SCOPE.md)
- [快速开始](docs/GETTING_STARTED.md)
- [从 V0.1 升级](docs/UPGRADE_V0.1_TO_V0.2.md)
- [系统架构](docs/ARCHITECTURE.md)
- [资料来源](docs/CORPUS_SOURCES.md)
- [资料导入](docs/CORPUS_IMPORT.md)
- [使用工作流](docs/USAGE_WORKFLOWS.md)
- [评分完整性与官方标准](docs/SCORING_INTEGRITY.md)
- [隐私与版权](docs/PRIVACY_AND_COPYRIGHT.md)
- [路线图](docs/ROADMAP.md)

## 许可证

- 程序代码与 Skills：MIT
- `starter-corpus` 原创数据：CC BY 4.0
- 第三方资料：不包含在仓库中，不受本项目许可证覆盖
