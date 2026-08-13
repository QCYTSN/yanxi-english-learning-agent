# 言蹊 v2 框架决策记录 (Yanxi v2 Decision Record)

> 归档日期：2026-08-13
> 范围：产品重塑决策（通用英语 + IELTS 双轨道）、品牌系统、词汇闭环、练习入口。
> 状态：已锁定并落地（除标注"预留"项）。

## 一、已拍板的主决策

| 维度 | 锁定内容 |
|---|---|
| 产品名 | 言蹊（Yanxi），内部标识符（包名、track_id、能力契约名）保留不变 |
| 双轨道 | 通用英语（默认，CEFR A1–C2）+ IELTS Academic（可选备考模块） |
| 标语 | 不言之教，自成其蹊（贯穿所有触点） |
| Logo | 行书对角 wordmark——「言」左上、「蹊」右下，笔势即"蹊"；小尺寸降级为单「言」字闲章 |
| 中文字体 | 霞鹜文楷 LXGW WenKai（Logo/标题子集化） |
| 英文字体 | EB Garamond（标题配衬，功能位回落等宽/无衬线） |
| 配色 | 纸白 #FBFCFA / 墨 #18211F / 牛津蓝 #254C61 / 证据青 #0D6B62；错处用墨色圈批，不用红绿对错 |
| 对话讲词入表 | 默认入候选 + 近期撤销 + "已识破"去重（P0 咽喉） |
| 词表种子 | 起步 100 · 可扩 1000/3000 三档（公版 GSL，只含词形+自评分档） |
| 打字练习 | 一等公民入口；成蹊式反馈（对则朱砂印章亮一格，错则墨色淡描"再来"） |
| 听言 | 独立入口：TTS 朗读 → 简答/复述；与口语两步式区分（"我先听再说"） |
| 口语两步 | 两步明示 + 中间占位续接（sessionStorage 保留"录音去了"状态） |
| 错误双向利用 | 打字错 → spelling_weakness 记忆 → 对话主动解释（P3 护城河） |

## 二、落地位置

- 品牌：`frontend/src/assets/fonts/`（子集 woff2）、`workspace.css` 字体/色板 token、
  `Shell.tsx` 对角 wordmark 与标语、`OnboardingPage.tsx` CEFR 初见卡。
- 词表：`resources/words/yanxi-starter-100.json`（公版 GSL 词形）、`seed_words.py`、
  `GET /api/v1/vocabulary/seed`。
- 讲词入表：`vocabulary.ingest_taught_words`（candidate 状态）、契约 schema
  `words_taught` 字段、`persist_agent_contract` 钩子、`GET/POST /api/v1/vocabulary/ingested*`。
- 打字/听言：`/practice/typing`、`/practice/listen`（Web Speech API，无云端 TTS）。
- 口语两步：`SpeakingWorkspace.tsx`。
- 错误利用：`vocabulary.record_typing_mistake` → learner_memories
  （`spelling_weakness`，track 感知上下文注入）。

## 三、边界与约束（防回归）

1. **种子边界**：公开构建的空题库约束 ≠ "空词频种子"。题库=受版权保护的
   真题语料（必须空）；词频种子=公版词形列表（可带）。种子不含释义/例句，释义一律
   BYO-API 现场生成。
2. **听言不膨胀**：TTS 朗读一段短料 + 一两个简答；不重建题目池、不追分、不计时。
   一膨胀就回到被拆掉的 IELTS 练习机器。
3. **字体加载**：只打包子集（Logo 3 KB + GB2312 标题 851 KB），不整包加载；fallback
   链中文→思源宋体→系统衬线，英文→Georgia→serif。
4. **守则**：每个新功能要么喂闭环（对话收词→复习→打字/听言→对话运用），要么是进入
   闭环的特殊入口；不建立独立的"语法练习机器"式大块。
5. **品牌人设下沉**：agent 语气是"种桃李者"——指事实、留白、少夸少催；开场不寒暄，
   错处墨色批注不红叉。

## 四、预留（v2.x 待决策）

- 1000/3000 档种子解锁（结构已留）。
- 内置词典 / 释义来源（决策：词形公版 + 释义 BYO-API，不捆绑商业词典）。
- 听言进阶（跟读评测、语音输入）需重新评估本地语音识别方案。
