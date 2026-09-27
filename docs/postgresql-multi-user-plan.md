# 晨风量化 PostgreSQL 多用户系统设计方案

## 1. 设计结论

晨风量化第一版只设计“用户”，不引入租户、组织、团队和成员关系。

系统遵循两条硬规则：

```text
共享行情数据：不带 user_id
用户私有数据：全部带 user_id
```

目标是让所有用户共用一套行情、指标和计算缓存，尽可能减少 TickFlow 调用；用户只隔离账号、自选股、策略、监控、报告、任务、套餐和订单。

## 2. 系统边界

### 2.1 全平台共享数据

以下数据不属于任何用户，不进入多用户隔离范围：

- 股票、ETF、指数基础信息
- 日 K、分钟 K
- 实时行情快照
- 复权因子
- 财务数据
- enriched 指标数据
- 市场概览和公共板块数据
- 内置策略源码
- 回测市场矩阵缓存
- TickFlow 客户端、限流器和能力探测结果

这些数据继续使用当前的 Parquet、DuckDB、Polars 和进程内缓存。

### 2.2 用户私有数据

以下数据进入 PostgreSQL，并且每张表必须包含 `user_id`：

- 用户账号和登录会话
- 自选股
- 用户偏好
- 策略参数覆盖
- 自定义、AI 和组合策略
- 自定义信号
- 监控规则
- 告警和已读状态
- 个股、财务和市场复盘报告
- 回测、优化和 AI 任务
- 用户密钥和通知渠道
- 套餐、订阅、订单和用量

### 2.3 禁止的实现

- 不为每个用户复制行情文件。
- 不为每个用户启动一套 `DataStore`、`KlineRepository` 或 `QuoteService`。
- 不因用户打开页面而直接调用 TickFlow。
- 不通过修改全局 `settings.data_dir` 切换用户。
- 不接受前端传入的任意 `user_id` 作为数据归属依据。
- 不在缓存键中无必要地加入 `user_id`，导致共享行情缓存碎片化。

## 3. 总体架构

```text
用户浏览器
   -> FastAPI API
       -> 登录会话解析 -> CurrentUser
       -> 套餐与用量检查
       -> 用户私有服务 -> PostgreSQL（全部带 user_id）
       -> 共享行情服务 -> Parquet / DuckDB / Polars
       -> 共享任务队列 -> Worker
       -> 全局 QuoteService -> 按 user_id 分发监控结果
       -> TickFlow（统一调用）
```

### 3.1 请求身份

登录成功后，每个请求得到只读的用户上下文：

```python
@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str
    role: str
    session_id: UUID
```

业务服务只能从已验证会话取得 `CurrentUser.id`。页面请求体即使包含 `user_id` 也必须忽略或拒绝。

### 3.2 后台任务身份

后台任务没有 HTTP 会话，因此任务消息必须显式携带：

```text
user_id
job_id
task_type
request_payload
```

Worker 只能把任务结果写回任务所属的 `user_id`。

## 4. 新增模块

为了减少现有量化代码改动，用户系统集中在新模块中：

```text
backend/app/user_system/
├── context.py             # CurrentUser
├── dependencies.py        # require_user / require_admin
├── security.py            # 密码、会话、重置令牌
├── models.py              # 用户相关模型
├── service.py
└── api.py

backend/app/persistence/
├── database.py            # 连接池和事务
├── migrations/            # Alembic
└── repositories/
    ├── users.py
    ├── watchlists.py
    ├── preferences.py
    ├── strategies.py
    ├── monitors.py
    ├── reports.py
    ├── jobs.py
    └── billing.py

backend/app/billing/
├── entitlements.py
├── usage.py
├── service.py
├── api.py
└── providers/

backend/app/tasks/
├── queue.py
├── worker.py
└── handlers/
```

现有行情、指标、选股和回测模块不直接写用户表，通过 Repository 协议访问用户私有数据。

## 5. PostgreSQL 数据模型

建议使用 UUID 主键、`timestamptz` 时间字段和 JSONB 配置字段。金额统一使用最小货币单位整数，例如人民币分。

### 5.1 用户和会话

```text
users
  id UUID PRIMARY KEY
  email TEXT UNIQUE NOT NULL
  password_hash TEXT NOT NULL
  display_name TEXT
  role TEXT NOT NULL             user / admin
  status TEXT NOT NULL           active / disabled / deleted
  email_verified_at TIMESTAMPTZ
  created_at TIMESTAMPTZ NOT NULL
  updated_at TIMESTAMPTZ NOT NULL
  last_login_at TIMESTAMPTZ

sessions
  id UUID PRIMARY KEY
  user_id UUID NOT NULL REFERENCES users(id)
  token_hash TEXT UNIQUE NOT NULL
  expires_at TIMESTAMPTZ NOT NULL
  revoked_at TIMESTAMPTZ
  ip TEXT
  user_agent TEXT
  created_at TIMESTAMPTZ NOT NULL
```

会话只保存 token 哈希。禁用用户、修改密码或执行“退出全部设备”时，撤销该用户全部会话。

### 5.2 自选股和偏好

```text
watchlist_items
  id UUID PRIMARY KEY
  user_id UUID NOT NULL REFERENCES users(id)
  symbol TEXT NOT NULL
  asset_type TEXT NOT NULL
  note TEXT
  position INTEGER NOT NULL
  added_at TIMESTAMPTZ NOT NULL
  UNIQUE (user_id, symbol, asset_type)

user_preferences
  user_id UUID NOT NULL REFERENCES users(id)
  key TEXT NOT NULL
  value_json JSONB NOT NULL
  updated_at TIMESTAMPTZ NOT NULL
  PRIMARY KEY (user_id, key)
```

### 5.3 策略

```text
strategy_overrides
  user_id UUID NOT NULL REFERENCES users(id)
  strategy_id TEXT NOT NULL
  overrides_json JSONB NOT NULL
  version INTEGER NOT NULL
  updated_at TIMESTAMPTZ NOT NULL
  PRIMARY KEY (user_id, strategy_id)

user_strategies
  id UUID PRIMARY KEY
  user_id UUID NOT NULL REFERENCES users(id)
  strategy_id TEXT NOT NULL
  source TEXT NOT NULL            custom / ai / composite
  name TEXT NOT NULL
  description TEXT
  definition_json JSONB
  source_code TEXT
  version INTEGER NOT NULL
  status TEXT NOT NULL
  created_at TIMESTAMPTZ NOT NULL
  updated_at TIMESTAMPTZ NOT NULL
  UNIQUE (user_id, strategy_id)

custom_signals
  id UUID PRIMARY KEY
  user_id UUID NOT NULL REFERENCES users(id)
  signal_id TEXT NOT NULL
  name TEXT NOT NULL
  definition_json JSONB NOT NULL
  status TEXT NOT NULL
  created_at TIMESTAMPTZ NOT NULL
  updated_at TIMESTAMPTZ NOT NULL
  UNIQUE (user_id, signal_id)
```

内置策略仍由代码提供，不写入每个用户的数据。用户修改内置策略参数时，只写 `strategy_overrides`。

### 5.4 监控和告警

```text
monitor_rules
  id UUID PRIMARY KEY
  user_id UUID NOT NULL REFERENCES users(id)
  name TEXT NOT NULL
  rule_type TEXT NOT NULL
  definition_json JSONB NOT NULL
  enabled BOOLEAN NOT NULL
  created_at TIMESTAMPTZ NOT NULL
  updated_at TIMESTAMPTZ NOT NULL

alert_events
  id UUID PRIMARY KEY
  user_id UUID NOT NULL REFERENCES users(id)
  rule_id UUID REFERENCES monitor_rules(id)
  symbol TEXT NOT NULL
  event_type TEXT NOT NULL
  payload_json JSONB NOT NULL
  dedupe_key TEXT NOT NULL
  triggered_at TIMESTAMPTZ NOT NULL
  read_at TIMESTAMPTZ
  UNIQUE (user_id, dedupe_key)
```

### 5.5 报告和任务

```text
analysis_reports
  id UUID PRIMARY KEY
  user_id UUID NOT NULL REFERENCES users(id)
  report_type TEXT NOT NULL
  symbol TEXT
  title TEXT NOT NULL
  content TEXT NOT NULL
  metadata_json JSONB
  created_at TIMESTAMPTZ NOT NULL

jobs
  id UUID PRIMARY KEY
  user_id UUID NOT NULL REFERENCES users(id)
  job_type TEXT NOT NULL
  status TEXT NOT NULL
  request_json JSONB NOT NULL
  result_json JSONB
  artifact_key TEXT
  error_code TEXT
  queued_at TIMESTAMPTZ NOT NULL
  started_at TIMESTAMPTZ
  finished_at TIMESTAMPTZ
```

大体积回测结果可以存对象文件，数据库只保存归属、摘要和受控对象键；不得保存客户端提供的任意文件路径。

### 5.6 套餐、订单和用量

```text
plans
  id UUID PRIMARY KEY
  code TEXT UNIQUE NOT NULL
  name TEXT NOT NULL
  price_minor INTEGER NOT NULL
  currency TEXT NOT NULL
  billing_period TEXT NOT NULL
  enabled BOOLEAN NOT NULL

plan_entitlements
  plan_id UUID NOT NULL REFERENCES plans(id)
  capability TEXT NOT NULL
  value_json JSONB NOT NULL
  PRIMARY KEY (plan_id, capability)

subscriptions
  id UUID PRIMARY KEY
  user_id UUID NOT NULL REFERENCES users(id)
  plan_id UUID NOT NULL REFERENCES plans(id)
  status TEXT NOT NULL
  current_period_start TIMESTAMPTZ
  current_period_end TIMESTAMPTZ
  cancel_at_period_end BOOLEAN NOT NULL
  provider TEXT
  provider_subscription_id TEXT

orders
  id UUID PRIMARY KEY
  user_id UUID NOT NULL REFERENCES users(id)
  order_no TEXT UNIQUE NOT NULL
  amount_minor INTEGER NOT NULL
  currency TEXT NOT NULL
  status TEXT NOT NULL
  provider TEXT NOT NULL
  provider_trade_no TEXT
  paid_at TIMESTAMPTZ
  created_at TIMESTAMPTZ NOT NULL

usage_counters
  user_id UUID NOT NULL REFERENCES users(id)
  metric TEXT NOT NULL
  period_key TEXT NOT NULL
  used INTEGER NOT NULL
  reserved INTEGER NOT NULL
  updated_at TIMESTAMPTZ NOT NULL
  PRIMARY KEY (user_id, metric, period_key)
```

## 6. 数据访问规则

所有私有 Repository 方法必须显式接收 `user_id`：

```python
class StrategyOverrideRepository(Protocol):
    async def get(self, user_id: UUID, strategy_id: str) -> dict: ...
    async def save(self, user_id: UUID, strategy_id: str, value: dict) -> None: ...
```

API 典型调用：

```python
@router.post("/api/strategies/config")
async def save_config(
    req: SaveConfigRequest,
    user: CurrentUser = Depends(require_user),
):
    await strategy_service.save_override(user.id, req.strategy_id, req.overrides)
```

请求体不增加 `user_id`，前端现有策略保存契约基本不变。

## 7. 策略保存设计

### 7.1 参数保存

当前页面继续调用：

```text
POST /api/strategies/config
```

改造后：

```text
页面提交 strategy_id + overrides
  -> 后端从会话取得 user_id
  -> 去掉与默认值相同的字段
  -> UPSERT strategy_overrides
  -> 失效该用户对应策略缓存
```

唯一键为：

```text
(user_id, strategy_id)
```

### 7.2 自定义、AI 和组合策略

页面 API 地址保持不变：

```text
POST /api/strategies/code/save
POST /api/strategies/composite/save
```

保存流程：

```text
取得登录 user_id
  -> 校验策略 ID、META 和安全规则
  -> 检查 (user_id, strategy_id) 冲突
  -> 写入 user_strategies
  -> version + 1
  -> 编译并验证策略
  -> 更新该用户策略缓存
```

缓存键至少包含：

```text
user_id + strategy_id + version
```

一个用户保存的策略不能注入全局策略注册表供其他用户直接读取。

## 8. TickFlow 统一调用设计

### 8.1 唯一调用入口

TickFlow 只能由以下全局服务调用：

- 统一数据同步任务
- 全局实时行情服务
- 统一分钟数据补齐任务
- 管理员触发的数据维护任务

普通用户页面 API 原则上只读取共享缓存和本地数据。

### 8.2 请求合并

用户请求的股票集合先求并集：

```text
用户 A：600000、000001
用户 B：000001、600519
用户 C：600519、300750

实际请求：600000、000001、600519、300750
```

相同数据集、股票、周期和时间窗口的并发请求只能产生一次上游调用，其余请求等待同一个结果。

### 8.3 缓存层

```text
L1：QuoteService 实时内存快照
L2：进程共享计算缓存
L3：Parquet / DuckDB 持久化行情
L4：TickFlow 上游
```

读取顺序固定为 L1 -> L2 -> L3 -> L4。只有数据不存在或明确过期时才允许访问 TickFlow。

### 8.4 更新策略

- 日 K：盘后统一增量同步。
- 财务数据：后台统一增量同步。
- 实时行情：统一订阅或按全局活跃股票集合批量轮询。
- 分钟 K：按活跃股票集合并、去重、限流后补齐。
- 页面刷新：只刷新本地查询，不直接重复调用 TickFlow。
- TickFlow 失败：保留上一份有效快照，并返回明确的 `as_of` 和过期状态。

### 8.5 防重复调用指标

平台必须记录：

- 每数据集 TickFlow 请求次数
- 请求涉及的去重前、去重后 symbol 数量
- 缓存命中率
- 合并中的相同请求数量
- 上游限流、超时和错误次数
- 每个页面动作是否触发上游调用

验收时应证明用户数量增长不会使 TickFlow 请求量按用户数线性增长。

## 9. 共享实时监控

`QuoteService` 保持全局唯一：

```text
统一获取 symbol 行情一次
  -> 查找所有启用并订阅该 symbol 的用户规则
  -> 按 user_id 执行规则
  -> 写入各自 alert_events
  -> 推送到对应 user_id 的 SSE 连接
```

监控规则可建立内存索引：

```python
rules_by_symbol = {
    "600000.SH": [(user_a, rule_1), (user_b, rule_8)],
}
```

新增、修改、启停或删除规则时只增量更新索引，不为每个行情 tick 全表扫描 PostgreSQL。

## 10. 套餐和用量控制

商业套餐与 TickFlow 数据源能力分开：

```text
用户套餐允许
  ∩ 平台 TickFlow 能力允许
  ∩ 平台当前资源允许
  = 最终可用功能
```

统一能力入口：

```python
entitlements.require(user.id, "backtest.run")
entitlements.get_limit(user.id, "watchlist.symbols")
usage.reserve(user.id, "ai.analysis", 1)
```

建议首批限制：

- 自选股数量
- 自定义策略数量
- 监控规则数量
- 每日回测次数
- 并发回测数量
- 最大回测范围
- 每月 AI 调用次数
- 是否允许实时监控
- 是否允许导出

前端隐藏或禁用功能只改善体验，后端必须重复校验。

## 11. 敏感配置

用户 TickFlow Key、AI Key、Webhook 和通知凭据使用加密字段保存：

- 数据库只保存密文和密钥版本。
- 主密钥来自环境变量或 KMS。
- API 默认只返回是否配置和脱敏值。
- 日志与异常不得包含明文。
- 支持密钥轮换。

如果平台使用统一 TickFlow 账号，则普通用户不需要配置 TickFlow Key，可隐藏对应设置入口。是否允许平台账号服务多用户必须先确认 TickFlow 服务条款。

## 12. 现有单用户数据迁移

提供幂等迁移命令：

```text
uv run python -m app.persistence.migrate_single_user \
  --source-data-dir <明确路径> \
  --target-user <邮箱> \
  --dry-run
```

迁移内容：

```text
user_data/watchlist.parquet             -> watchlist_items
user_data/preferences.json              -> user_preferences
user_data/strategy_overrides/*.json     -> strategy_overrides
user_data/monitor_rules/*.json          -> monitor_rules
user_data/custom_signals/*.json         -> custom_signals
user_data/*reports*.json                -> analysis_reports
strategies/custom/*.py                  -> user_strategies
strategies/ai/*.py                      -> user_strategies
strategies/composite/*.py               -> user_strategies
```

迁移要求：

- `--dry-run` 不写数据库。
- 不删除或覆盖原始文件。
- 重复执行不产生重复记录。
- 校验记录数、策略 ID、schema 和内容摘要。
- 生成成功、跳过、冲突和失败清单。
- 目标路径和源路径必须经过边界验证。

## 13. 兼容模式

为了不破坏现有本地用户，保留两种模式：

```text
APP_MODE=standalone
  单用户本地模式
  保留当前文件存储和访问密码
  PostgreSQL 可选

APP_MODE=multi_user
  多用户模式
  PostgreSQL 必需
  所有私有数据按 user_id 隔离
```

两种模式共享同一套行情和计算业务逻辑。文件版和 PostgreSQL 版 Repository 只处理持久化，不复制业务规则。

## 14. 实施阶段

### 阶段 0：自选股垂直验证

- 引入 PostgreSQL、SQLAlchemy、asyncpg 和 Alembic。
- 建立 users、sessions、watchlist_items。
- 实现 `CurrentUser`。
- 为自选股定义 Repository 协议。
- 保留现有文件实现，新增 PostgreSQL 实现。
- 完成两个用户并发隔离测试。
- 确认页面读取自选股仍共用行情数据。

退出标准：用户 A 和用户 B 自选股完全隔离，但相同股票只读取同一份行情缓存。

### 阶段 1：认证与偏好

- 注册、登录、退出、邮箱验证、找回密码。
- 分布式登录限流和会话撤销。
- 用户偏好迁移。
- 退出登录时清理前端用户查询缓存。
- 管理员用户列表、启用和禁用。

### 阶段 2：策略

- 策略参数覆盖迁移。
- 自定义、AI、组合策略迁移。
- 用户策略版本化和缓存隔离。
- 删除、重命名、复制和导入权限检查。
- 用户 Python 策略进入受限 Worker。

### 阶段 3：监控与报告

- 监控规则和告警迁移。
- 全局行情一次获取、按用户规则分发。
- SSE 按 user_id 隔离。
- AI 报告和复盘报告迁移。
- 通知渠道加密存储。

### 阶段 4：任务化与配额

- 回测、优化、AI 分析进入共享 Worker 队列。
- 任务显式携带 user_id。
- 用户级和平台级并发限制。
- 超时、取消和失败释放配额。
- 任务结果权限检查。

### 阶段 5：套餐、收费和上线

- 套餐、权益、订阅、订单和用量。
- 一个支付渠道的服务端回调。
- 回调验签、幂等、退款和对账。
- 管理后台和审计日志。
- 备份恢复、安全测试和灰度发布。

## 15. 测试矩阵

### 15.1 用户隔离

- 用户 A 无法读取、修改或删除用户 B 的任何私有资源。
- 伪造请求体、URL 和请求头中的 `user_id` 无效。
- 所有私有表查询都包含用户边界。
- 批量更新、删除、导出和后台任务同样隔离。
- 管理员接口与普通接口分开授权。

### 15.2 共享行情

- 两个用户查询相同股票时命中同一行情缓存。
- 多用户自选股和监控标的正确求并集。
- 页面重复刷新不重复调用 TickFlow。
- 并发相同请求被合并。
- TickFlow 失败时不清空上一份有效行情。
- 缓存键覆盖资产类型、周期、日期和其他结果维度。

### 15.3 数据一致性

- 自选股重复添加和排序并发。
- 策略保存版本冲突。
- 告警去重和冷却。
- 用量预占、结算和释放。
- 支付回调重复和乱序。
- 单用户文件迁移幂等。

### 15.4 回归

- 共享行情、指标和回测金融口径保持不变。
- 数据源插件化边界保持不变。
- standalone 模式不依赖 PostgreSQL 也能启动。
- 多用户模式数据库不可用时 fail-closed，不返回其他用户或虚假数据。

## 16. 风险控制

| 风险 | 控制方式 |
| --- | --- |
| 查询漏加 user_id | Repository 强制参数、代码审查、越权测试；可选数据库 RLS 双保险 |
| 用户策略污染全局引擎 | 用户策略缓存键包含 user_id 和 version，不写入全局可变注册表 |
| 后台任务错写用户 | 任务显式携带 user_id，结果表同时校验 job_id 与 user_id |
| 用户增加导致 TickFlow 调用增长 | 统一同步、symbol 求并集、请求合并、多级缓存和调用指标 |
| 单用户占满计算资源 | 用户配额、平台配额、公平队列、超时和内存限制 |
| 密钥泄露 | 加密存储、日志脱敏、受控解密和密钥轮换 |
| 旧数据迁移失败 | dry-run、幂等导入、保留原文件和迁移报告 |
| 商业授权不明确 | 收费上线前确认 TickFlow、第三方数据和代码的商业授权 |

## 17. 第一批开发任务

第一批只做最小闭环，不直接改造全部业务：

1. 确认本方案为多用户唯一数据边界。
2. 增加 PostgreSQL 开发服务和迁移框架。
3. 创建 `users`、`sessions`、`watchlist_items`。
4. 实现 `CurrentUser` 和登录会话。
5. 定义 `WatchlistRepository`。
6. 保留文件版实现，新增 PostgreSQL 实现。
7. 只改造自选股 API 使用新 Repository。
8. 验证两个用户的数据隔离。
9. 验证两个用户相同股票共用行情查询和缓存。
10. 记录改造前后 TickFlow 调用次数和接口耗时。

完成这十项并通过评审后，再迁移偏好和策略。这样可以先证明“私有数据按用户隔离、行情仍然全局共享”确实可行，再扩大修改范围。

## 18. 上线验收标准

1. 所有用户私有表都有 `user_id`、外键和必要索引。
2. 所有用户私有 API 通过登录会话确定 `user_id`。
3. 两个用户不能互相访问任何私有资源。
4. 行情、指标、财务和市场矩阵没有用户副本。
5. 相同实时行情请求在全平台只调用一次上游。
6. 用户数量增加时，TickFlow 调用量不按用户数线性增长。
7. 回测、AI 和监控任务的用户归属可追踪且不可越权。
8. 套餐和用量限制在后端强制执行。
9. 旧单用户数据可幂等迁移并保留原文件。
10. PostgreSQL 备份恢复、灰度和回滚演练完成。
# 实施状态（2026-08-10）

当前 `codex/multi-user-foundation` 分支已经完成可运行 MVP：

- PostgreSQL 用户、会话和首位注册用户管理员引导；
- 自选股、用户策略、策略参数、监控规则、告警和回测记录按 `user_id` 隔离；
- 行情、K 线、指标与 TickFlow 调用保持全局共享；
- 监控规则共用行情循环，告警按 `user_id` 写库并定向推送 SSE；
- 免费版/专业版套餐、订阅期限、策略与监控规则额度；
- 管理员用户状态、角色和套餐管理页面；
- 单机模式继续使用原文件存储，不强制 PostgreSQL。

当前收费采用管理员手工开通模式。第三方支付下单、回调和退款属于后续支付渠道集成，
不会改变本计划的数据隔离和套餐授权模型。
