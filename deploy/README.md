# 多实例部署说明

三件事需要在应用外配好：**共享状态（Redis）**、**指标抓取（Prometheus）**、**日志汇聚（Fluent Bit）**。

## 拓扑

```
               ┌────────────┐
  客户端 ─────▶│ 负载均衡    │
               └─────┬──────┘
          ┌──────────┼──────────┐
          ▼          ▼          ▼
      doc-qa-1   doc-qa-2   doc-qa-3      # 无状态，镜像一致
          │          │          │
          └──────────┼──────────┘
                     ▼
                 Redis            # 限流令牌桶 / 幂等结果 / 日 token 预算
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
   Prometheus                 Fluent Bit ──▶ Loki / ES
   （抓 /metrics）             （采 stdout 或 audit.jsonl）
```

## 应用配置

三个实例使用同一份环境变量，**只有 `REDIS_PREFIX` 必须一致**（默认 `rag`）：

```bash
REDIS_URL=redis://:password@redis.internal:6379/0
REDIS_TIMEOUT_S=1.5
LOG_SINK=both
ADMIN_TOKEN=<强随机值>
KB_APPROVAL=on
# 知识库目录需要共享存储（NFS/对象存储同步），或只让一个实例处理审批
```

## 注意

- **知识库目录**：`data/kb/` 必须挂共享卷，且同一时间只让一个实例执行审批/回滚（当前是本地文件锁）。上传只写 `pending/`，不写活动目录，所以并发上传本身安全。
- **索引目录**：每个实例可各自构建（启动/首次查询时），也可把 `data/index/` 放共享只读卷；manifest 的 fingerprint 会校验一致性。
- **Redis 高可用**：至少主从 + 哨兵；`maxmemory-policy` 不要用 `allkeys-lru`，否则限流键被淘汰会短暂放大流量。
- **审计落盘**：本地 JSONL 是副本，集中检索以 Loki/ES 为准；`LOG_SINK=stdout` 时不再写本地文件。
- **灰度**：`CANARY_PERCENT` 仍来自各实例 `logs/runtime.json`，多实例需要共享卷或改配置中心；否则各实例灰度比例可能不一致。
