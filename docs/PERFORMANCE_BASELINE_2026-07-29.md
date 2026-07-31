# 10k Session / 100k Question 性能基准

日期：2026-07-29
环境：Windows 本地 SQLite，合成非版权数据，基准结束后临时数据目录自动删除。

运行命令：

```powershell
ielts-coach benchmark scale --sessions 10000 --questions 100000 --repeats 5
```

## 结果

| 路径 | 中位数 | 预算 | 结果 |
|---|---:|---:|---|
| Session 首屏 | 33.790 ms | 250 ms | 通过 |
| Session 深分页 | 37.009 ms | 500 ms | 通过 |
| Question 首屏 | 14.596 ms | 250 ms | 通过 |
| Question 组合筛选 | 14.019 ms | 250 ms | 通过 |
| Question 深分页 | 23.089 ms | 500 ms | 通过 |
| Question 文本搜索 | 24.104 ms | 750 ms | 通过 |
| 随机抽题 | 93.786 ms | 500 ms | 通过 |
| 数据库状态统计 | 17.395 ms | 750 ms | 通过 |

建库和填充 10,000 个 Session、100,000 道 Question 共耗时 2.825 秒。随机抽题
的 Python 峰值额外内存为 23.8 KiB。

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
- 当真实数据连续出现首屏 P95 超过 250 ms、文本检索超过 750 ms，或数据库达到
  百万题级别时，再分别评估时间游标分页、FTS5 和独立索引 worker。
- 基准只测数据库与 Python 数据路径；完整页面流畅度仍由浏览器 E2E、资源预算和
  长列表分页共同验收。
