# 10k Session / 100k Question 性能基准

初始日期：2026-07-29
最近复测：2026-08-09（Schema v30）
环境：Windows 本地 SQLite，合成非版权数据，基准结束后临时数据目录自动删除。

运行命令：

```powershell
ielts-coach benchmark scale --sessions 10000 --questions 100000 --repeats 5
```

## 结果

| 路径 | 中位数 | 预算 | 结果 |
|---|---:|---:|---|
| Session 首屏 | 3.815 ms | 250 ms | 通过 |
| Session 深分页 | 5.467 ms | 500 ms | 通过 |
| Question 首屏 | 4.245 ms | 250 ms | 通过 |
| Question 组合筛选 | 4.494 ms | 250 ms | 通过 |
| Question 深分页 | 87.989 ms | 500 ms | 通过 |
| Question 文本搜索 | 15.003 ms | 750 ms | 通过 |
| 随机抽题 | 145.532 ms | 500 ms | 通过 |
| 数据库状态统计 | 7.126 ms | 750 ms | 通过 |

最近复测中，建库和填充 10,000 个 Session、100,000 道 Question 共耗时
3.299 秒。随机抽题的 Python 峰值额外内存为 20.2 KiB。所有查询计划检查
通过；Session 首屏使用 `idx_sessions_occurred`，Question 组合筛选使用
`idx_questions_module_type_id`。

## 本次优化

旧实现会先把最多 100,000 道候选题加载到 Python，再随机选择。当前实现改为：

```text
数据库统计候选数量
→ 根据 seed 选择一个 offset
→ 只读取一条 Question
```

因此题库扩大时不会因随机抽题产生与候选数量线性增长的 Python 列表。

## 解释与后续触发条件

- 当前规模不需要 Docker、PostgreSQL、向量数据库或新增后端语言。
- SQLite 仍是本地单用户学习记录的正确权威存储。
- Session 首屏查询当前会扫描 10k 行并临时排序，但实测仍低于 34 ms；暂不为
  了理论优化引入新迁移。
- 学习历史全文检索已经使用 SQLite FTS5；当真实数据连续出现首屏 P95 超过
  250 ms、文本检索超过 750 ms，或数据库达到百万题级别时，再分别评估时间游标
  分页、独立索引 worker 或其他经基准证明必要的实现。
- 基准只测数据库与 Python 数据路径；完整页面流畅度仍由浏览器 E2E、资源预算和
  长列表分页共同验收。
