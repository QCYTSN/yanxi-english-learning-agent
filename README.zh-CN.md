# 言蹊 (Yanxi)

<p align="center">
  <img src="docs/assets/yanxi-logo.svg" alt="言蹊 logo · 现代印章风" width="340">
</p>

[![Tests](https://github.com/QCYTSN/ielts-ai-coach/actions/workflows/tests.yml/badge.svg)](https://github.com/QCYTSN/ielts-ai-coach/actions/workflows/tests.yml)
[![Python 3.10–3.12](https://img.shields.io/badge/Python-3.10--3.12-3776AB.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/Code-MIT-0f766e.svg)](LICENSE)
[![Release: 1.5.0](https://img.shields.io/badge/release-1.5.0-334155.svg)](RELEASE_NOTES.md)

> **English version: [README.md](README.md)** · 本文档同时提供英文版。

本地优先（local-first）、Agent 原生（agent-native）的英语学习软件。

言蹊把浏览器学习工作台、本地 Python 教学运行时（Teaching Runtime）、结构化
Skills 与学习者自选的模型供应商组合在一起。模型可以讲解与评估，但**不能直接
写入权威学习记录**——候选输出必须先通过 Schema 与语义校验，才能由本地运行时
落库。

默认学习轨道是通用英语（日常与职场），底层是可复用的 Learning Agent Kernel，
它负责目标、活动、技能证据、掌握度估算与复习调度。雅思学术（IELTS Academic）
作为第一个可选考试 Domain Pack 发布，拥有自己的课程体系与评分政策。

> 本项目为独立作品，未获得 IELTS、剑桥大学出版社与考评院、英国文化协会或
> IDP Education 的任何背书。

## 交付内容

- 以对话为先的学习工作台：今天、练习、资料库、进度与设置五大界面；
- 持久化教师对话，支持图片、PDF、Word 与文本附件；
- 词汇自动摄入：对话中老师讲解过的词会成为可确认的候选词，支持撤销与
  "已认识"去重，进入间隔复习；
- 富词卡：约 2900 个高频词自带离线预设词卡（音标、词性、释义、词形变化），
  其余单词可按需调用模型补全，全部带来源标注；
- 自适应间隔复习：答对的词沿 1-2-4-7-14-30-60 天阶梯推进，答错的词次日回归；
- 自动本地备份：每周检查一次备份新鲜度，滚动保留最近 5 份自动备份，另有
  手动备份与迁移前快照；
- 一等公民的打词与听言练习（打字 + 听写），词库来自你自己的词表加内置的
  公版起步 100 词；
- 阅读、写作、口语、听力学习流程，以及词汇与语法支持；
- 本地 SQLite 学习记录、Session、语料库与媒体登记表；
- ChatGPT 登录桥、OpenAI 兼容 API 与本地 HTTP 模型三种供应商；
- 有界的长期对话上下文、可索引的本地历史、可恢复的后台 OCR/内容任务；
- 带版本、可过期、显式解决冲突的学习者记忆；
- 打词失误会写入学习者记忆，后续对话会主动讲解你拼不好的词；
- 运行时掌控教学周期，以及隐私安全的教学策略回归测试；
- 面向学习者的教学路径、可编辑的学习目标、技能证据视图与学习者可控的
  教师记忆；
- Windows 桌面安装包与面向技术用户的 Python 包。

## 不交付什么

公开发行的应用以**空题库**启动。不捆绑剑桥雅思真题、历年试卷、商业课程题目、
音频、答案键、用户作文、凭据或私人学习记录。用户自行导入有权使用的材料。

项目测试可能使用少量项目原创夹具；发布校验确保这些夹具不会进入 wheel 或
Windows 安装包。

## 架构

```text
浏览器学习 UI
        ↓
对话运行时 ──> 有界 Tutor Agent ──> 白名单 Skill 工具
        │
        └──────────────> 正式教学运行时 ──> 练习 / 评估
                                      │
                         通用英语（默认）/ 雅思学术
                                      ↓
                   Learning Agent Kernel / 权威本地数据
                                      ↓
                         SQLite / Session / 语料库 / 媒体
```

模型供应商与教学运行时是两个独立概念：

- **模型供应商**为教学流程提供推理（自带的 OpenAI 兼容 API、ChatGPT 登录桥
  或本地 HTTP 模型）；
- **教学运行时**负责轨道规则、隐私、校验与持久化；
- 外部 CLI Agent 不是教学供应商，也不属于主要学习体验的一部分。

详见 [Architecture V2](docs/ARCHITECTURE_V2.md) 与
[Tutor Agent 架构](docs/TUTOR_AGENT_ARCHITECTURE.md)。可复用的学习状态边界定义在
[Learning Agent Kernel](docs/LEARNING_AGENT_KERNEL.md)。

### Learning Agent Kernel

内部学习层刻意比通用自主 Agent 更窄：

- 通用英语轨道定义六维技能图（听、读、写、说、词汇、语法）与 CEFR 对齐的
  教学政策；雅思学术作为可选考试 Domain Pack，拥有自己的四模块技能图、
  证据映射与评分政策；
- 运行时从经过校验的学习记录推导目标、活动、掌握证据与复习时机；
- Skills 只加载当前教学阶段所需的参考文档；规划失败会降级为一次直接回答，
  而不是让整个回合报错；
- 学习者记忆保存在本地，带版本、可过期，冲突时对 Tutor 隐藏；
- 教学周期按诊断、讲授、引导练习、独立练习、评估、复习、巩固七个阶段推进；
- 模型只能建议动作，只有学习者或运行时才能变更正式学习状态；
- 发布检查覆盖结构化输出契约与教学策略正/负向控制，且不保留原始学习者内容。

该架构可支持未来的英语学习轨道。默认轨道是通用英语；雅思学术是第一个可选
考试 Domain Pack。新增轨道需要自己的课程、Skills、契约与评估集。

## Windows 安装

发布版本请从 [GitHub Releases 页面](https://github.com/QCYTSN/ielts-ai-coach/releases)
下载 Windows x64 安装程序并双击安装。安装包自带 Python 运行时，普通用户无需
安装 Python、Node.js、Git、Docker、WSL 或 CLI Agent。若暂未列出安装包版本，
请使用下方的源码安装方式。

首次启动时，应用会在以下位置创建私有数据目录：

```text
%LOCALAPPDATA%\Yanxi\data
```

已有的 `IELTS_HOME` 配置与旧版 `~/.ielts` 目录会被保留。

完整说明：[安装文档](docs/INSTALLATION.md)。

## 源码安装

需要 Python 3.10–3.12；仅在重建前端时需要 Node.js。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[ui]"
xiyan init
xiyan ui open
```

可选本地 OCR 依赖：

```powershell
python -m pip install -e ".[ui,ocr]"
```

安装开发者桌面快捷方式：

```powershell
xiyan ui shortcut-install
```

快捷方式会启动或复用本地服务并打开浏览器界面。

## 模型连接

核心确定性功能（打词、听言、词表、复习调度）不需要模型。教师对话、写作反馈
与基于证据的讲解需要配置以下任一方式：

1. OpenAI 兼容 API（自带密钥，任意厂商与模型）；
2. 通过隔离托管运行时登录 ChatGPT；
3. 本地 OpenAI 兼容 HTTP 模型。

## 开发

```powershell
python -m pip install -e ".[ui,dev]"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest -q

cd frontend
npm ci
npm run typecheck
npm run lint
npm test
npm run build
```

发布前：

```powershell
python scripts/verify_release.py --source-only
xiyan evaluation release --cases tests/fixtures/agent_contracts
```

发布命令会运行契约符合性检查、内置的正/负向教学质量套件与本地规模性能门。

Windows 发布构建：

```powershell
.\scripts\build-windows-release.ps1 -Version 1.5.0
```

参见[发布清单](docs/RELEASE_CHECKLIST.md)。

## 文档

- [产品边界](PRODUCT.md)
- [架构 V2](docs/ARCHITECTURE_V2.md)
- [Tutor Agent 架构](docs/TUTOR_AGENT_ARCHITECTURE.md)
- [安装说明](docs/INSTALLATION.md)
- [隐私与版权](docs/PRIVACY_AND_COPYRIGHT.md)
- [贡献指南](CONTRIBUTING.md)
- [安全政策](SECURITY.md)

## 数据、隐私与许可

- 应用代码与 Skills：MIT 许可。
- 项目原创文档与测试夹具：CC BY 4.0（另有说明者除外）。
- 用户材料与第三方内容归各自权利人所有。
- 凭据存储在 SQLite 之外：Windows 使用 DPAPI，其他平台优先系统钥匙串，
  兜底为本机属主私有文件。
- 本地服务仅监听 `127.0.0.1`，并使用随机启动令牌。

参见[数据许可](DATA_LICENSE.md)、[第三方声明](THIRD_PARTY_NOTICES.md)与
[隐私与版权](docs/PRIVACY_AND_COPYRIGHT.md)。
