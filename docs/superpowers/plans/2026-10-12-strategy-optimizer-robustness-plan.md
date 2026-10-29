# 跨时期稳健策略优化代码实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution, or superpowers:subagent-driven-development only when the user selects delegation. Steps use checkbox syntax for tracking.

**Goal:** 在现有策略优化插件中增加跨时期稳健模式，以固定参数跨段搜索、邻域检查、推荐冻结和隔离留出测试形成可解释的推荐。

**Architecture:** gateway 保留旧模式，新增稳健编排器；时间计划、评分、邻域生成分别为纯函数模块。所有成交继续交给 StrategyBacktestService，manager/store 管理不可变运行快照和恢复，前端使用现有插件 API 与页面。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic v2、Polars、React 18、TypeScript、现有 uv/pnpm 测试工具。不新增第三方依赖。

**Spec:** `docs/superpowers/specs/2026-10-12-strategy-optimizer-robustness-design.md`（已确认）。本计划定义的类型与函数均为拟新增，非现有 API。

## Global Constraints

- 同一候选在三个开发段使用同一套参数和信号；留出结果不得反馈搜索或重排。
- 仅支持 position 资金模式；旧模式及历史记录保持原行为。
- 主候选最多 500、邻域中心最多 10、每中心最多 20 个邻居、推荐最多 3、固定额外参考最多 2。
- 独立分段与连续资金回测分别展示；不可用指标不得变成零分或成功状态。
- 使用实际交易日历和历史数据资格检查，不从某一只股票有行情的日期推断全市场交易日。
- 不覆盖已有工作区修改；不自动提交、推送或合并。下列任务的完成节点仅做 diff 检查，提交需另外获得授权。
- 执行前完整重读 CONTRIBUTING.md、secondary-development.md、设计和本计划。当前文件只提供计划，没有实现或已通过测试声明。

## Review Focus

1. 策略在任务排队后被编辑或删除：冻结快照仍可运行，不能静默换用新策略（任务 1、4）。
2. 浮点网格和跨参数约束：邻居必须属于合法搜索域，不能生成越界值（任务 3）。
3. 留出已执行但结果写盘前中断：恢复不重复宣称首次独立验证（任务 5）。
4. 某段无交易或缺价格：候选失败与数据集整体失败区分，不能返回优秀推荐（任务 2、4）。
5. 启动两个使用同一留出区间的任务：在用户范围内串行登记用途，第二个标记重复（任务 5）。

## 文件职责与调用链

| 文件 | 改动与职责 |
| --- | --- |
| `backend/app/strategy_optimizer/contracts.py` | 新增冻结配置与结果 dataclass；旧配置字段追加默认值 |
| `backend/app/strategy_optimizer/time_plan.py` | 新增日期切分、交易日归一和滚动窗口 |
| `backend/app/strategy_optimizer/robust_scoring.py` | 新增绝对门槛、百分位、段分数与最终分数 |
| `backend/app/strategy_optimizer/neighborhood.py` | 新增合法数值邻居生成 |
| `backend/app/strategy_optimizer/robustness.py` | 新增分阶段执行编排，不含撮合计算 |
| `backend/app/strategy_optimizer/gateway.py` | 模式分发、回测适配、数据资格与缓存指纹 |
| `backend/app/strategy_optimizer/validation.py` | 请求白名单与联合验证 |
| `backend/app/strategy_optimizer/manager.py` | 阶段、快照、用途登记与恢复 |
| `backend/app/strategy_optimizer/store.py` | 复用原子写；保存稳健 checkpoint 与留出登记 |
| `backend/app/custom/strategy_optimizer.py` | RunRequest、预览接口、授权和保存推荐边界 |
| `frontend/src/custom/strategy-optimizer/api.ts` | 强类型配置、预览、结果和事件 |
| `frontend/src/custom/strategy-optimizer/RobustnessConfig.tsx` | 新增模式配置与时间预览 |
| `frontend/src/custom/strategy-optimizer/RobustnessResults.tsx` | 新增分段表、诊断与留出展示 |
| `frontend/src/custom/strategy-optimizer/StrategyOptimizerPage.tsx` | 模式选择与新旧结果分发 |

调用链：插件 API → 校验/快照/时间预览 → manager → gateway 模式分发 → 稳健编排器 → 既有回测服务 → 指标及评分 → checkpoint/result → SSE/页面。旧 `score_candidates` 与 `validate_oos` 不改变语义。

## 公共数据契约

```python
# contracts.py：拟新增的类型；内部比例统一小数制。
@dataclass(frozen=True)
class EvaluationWindow:
    id: str
    start: date
    end: date
    role: str  # development / holdout / diagnostic

@dataclass(frozen=True)
class RobustTimePlan:
    development: tuple[EvaluationWindow, ...]
    holdout: EvaluationWindow | None
    diagnostics: tuple[EvaluationWindow, ...]

@dataclass(frozen=True)
class RobustGates:
    max_drawdown: float = 0.20
    min_trades: int = 30
    min_baseline_delta: float = -0.03
    min_positive_segments: int = 2
    all_segment_percentile: float = 0.50
    strong_segment_percentile: float = 0.70
    min_stability: float = 0.60

@dataclass(frozen=True)
class SegmentMetrics:
    annualized_return: float
    max_drawdown: float  # 正数幅度
    trade_count: int
    baseline_delta: float

@dataclass(frozen=True)
class SegmentObservation:
    window_id: str
    metrics: SegmentMetrics | None
    failure: str | None = None

@dataclass(frozen=True)
class RobustCandidate:
    candidate_id: str
    parameters: dict
    buy_signals: tuple[str, ...]
    sell_signals: tuple[str, ...]
    segments: tuple[SegmentObservation, ...]

@dataclass(frozen=True)
class RankedCandidate:
    candidate: RobustCandidate
    segment_scores: tuple[float, ...]
    segment_percentiles: tuple[float, ...]
    base_score: float | None
    robust_score: float | None
    stability: float | None
    eligible: bool
    failures: tuple[str, ...]
```

API 新增 `evaluation_mode: legacy | robust`，默认 legacy；`robust_config` 仅在 robust 可用，含 layout（holdout/diagnostic）、四个边界日期、holdout_usage（used/declared_unused/unknown）、gates、reference_strategy_ids。请求不接受客户端提供的冻结顺序、快照摘要或重用状态。旧 weights/train_fraction/test_days 在 robust 模式不参与计算，前端隐藏，接口将其记为 legacy 字段而非误用。

响应顶层原有 top3/candidates 保留，新增 `robust_result`：version、time_plan、coverage、baseline、references、candidates、frozen_candidate_ids、continuous_development、diagnostics、holdout、budgets。保存推荐继续使用冻结 top3；失败候选只存在明细中。holdout 状态为 not_applicable/pending/passed/failed/insufficient；usage 独立于性能状态。

## Task 1：契约、交易日计划和冻结配置

**Files:** 修改 contracts.py、validation.py、custom/strategy_optimizer.py、gateway.py；新增 time_plan.py、`backend/tests/test_strategy_optimizer_time_plan.py`；扩展 contracts/API 测试。

**Interfaces:** `build_time_plan(start: date, end: date, trading_dates: tuple[date, ...], boundaries: tuple[date, ...], layout: str) -> RobustTimePlan`；`preview_robust_config(raw: dict) -> dict` 为 gateway 新方法。预览新增 POST `/api/custom/strategy-optimizer/preview`，必须使用与启动相同授权与校验。

- [ ] 写测试：下述纯函数测试及非法模式、参考超过两套、非有限门槛、参考策略越权、排队后源码变化测试。

```python
def test_split_uses_trading_dates_and_is_disjoint():
    days = tuple(date(2020, 1, n) for n in range(1, 11))
    plan = build_time_plan(days[0], days[-1], days, (days[0], days[3], days[6], days[8]), "holdout")
    assert [(w.start, w.end) for w in plan.development] == [
        (days[0], days[2]), (days[3], days[5]), (days[6], days[7])]
    assert (plan.holdout.start, plan.holdout.end) == (days[8], days[9])
```

- [ ] 在 backend 执行 `uv run pytest tests/test_strategy_optimizer_time_plan.py tests/test_strategy_optimizer_contracts.py tests/test_strategy_optimizer_api.py -q`，确认新用例未实现时失败。
- [ ] 实现日期计划：四个边界表示三段的起点和留出起点；诊断模式使用三个段起点、无留出。起点归一为不早于输入日期的首个交易日；上一段止于该日前最后交易日；段无交易日拒绝。默认留出起点为 end 向前两日历年（闰日降至 2 月 28 日），开发交易日按商余数分配为三段，余数优先前段。

```python
cuts = [bisect_left(trading_dates, boundary) for boundary in boundaries]
if cuts != sorted(set(cuts)) or cuts[0] != 0:
    raise ValueError("invalid normalized boundaries")
# 三个 development 窗口分别取 trading_dates[left:right]；holdout 取余下日期。
```

- [ ] 查找实际可用交易日历入口后给 gateway 注入交易日读取 callable；不存在权威日历时预览返回明确错误，不用工作日或单只股票日期替代。记录真实适配入口于代码注释及开发文档。
- [ ] 冻结策略源码/声明、默认参数、参考快照、股票池及成本。明确现有 engine 是否可实例化快照：若只能按 ID 查实时定义，在 gateway 私有实例上下文执行快照，禁止修改全局注册；测试证明结果仍使用旧快照。将快照适配作为本任务完成条件，不留给后续猜测。
- [ ] 重跑上述测试及 Ruff；检查 diff，保持旧 RunRequest 默认行为。

## Task 2：稳健指标和评分纯函数

**Files:** 新增 robust_scoring.py、`backend/tests/test_strategy_optimizer_robust_scoring.py`；扩展现有 scoring 测试验证旧模式。

**Interfaces:** `annualize(ending_nav: float, elapsed_days: int) -> float`；`percentile_ranks(values: tuple[float, ...]) -> tuple[float, ...]`；`score_development(candidates: tuple[RobustCandidate, ...], gates: RobustGates) -> tuple[RankedCandidate, ...]`；`score_neighborhood(center: RankedCandidate, neighbors: tuple[RankedCandidate, ...], gates: RobustGates) -> RankedCandidate`。邻居评分使用冻结主候选分布插值，与主候选平均名次规则一致；函数内部提供固定分布转换，不重新计算主候选。

- [ ] 写实际数值用例：

```python
def test_ties_and_single_candidate_are_neutral():
    assert percentile_ranks((4.0,)) == (0.5,)
    assert percentile_ranks((1.0, 2.0, 2.0)) == (0.0, 0.75, 0.75)

def test_annualization_rejects_invalid_nav():
    with pytest.raises(ValueError):
        annualize(0.0, 365)
    assert annualize(1.1, 365) == pytest.approx(0.1)
```

- [ ] 增加三段均衡与一段暴涨样例，分别断言 min(Q)、B、门槛失败原因和 R；加入无交易、缺失指标、收益负数、回撤零、排名同分、零推荐测试。相对收益差 -0.03 边界通过，低于边界失败。
- [ ] 执行 `uv run pytest tests/test_strategy_optimizer_robust_scoring.py tests/test_strategy_optimizer_scoring.py -q`，确认新用例失败后实现：

```python
annualized = ending_nav ** (365.0 / elapsed_days) - 1.0
calmar = annualized / max(abs(max_drawdown), 0.01)
q = 0.6 * return_percentile + 0.4 * calmar_percentile
b = 0.625 * min(segment_scores) + 0.375 * sum(segment_scores) / 3
r = 0.5 * min(segment_scores) + 0.3 * sum(segment_scores) / 3 + 0.2 * stability
```

- [ ] 指标采用以区间 start/end 日历跨度计算的 elapsed_days（含首尾，至少一天），禁止按交易日数量当自然年。缺任何段数据则 base_score=None，不参与百分位。排名分布由满足回撤及样本门槛的完整候选构成；所有失败原因持久化。
- [ ] 重跑测试/Ruff/diff 检查。

## Task 3：合法邻域与预算

**Files:** 新增 neighborhood.py、`backend/tests/test_strategy_optimizer_neighborhood.py`；复用 contracts.py 的合法值规则。

**Interfaces:** `generate_neighbors(center: Candidate, parameters: tuple[ParameterSpec, ...], constraints: tuple[dict, ...], base_values: dict, limit: int = 20) -> tuple[Candidate, ...]`；Candidate 复用 search.py 的现有类型。

- [ ] 测试中心 x=1.4、步长 0.1、范围 1.3～1.5，邻居恰好 1.3/1.5；布尔不翻转；参数顺序不影响输出；跨参数约束淘汰；浮点 0.1 累加不重复。

```python
def test_boundary_does_not_create_illegal_neighbor():
    spec = ParameterSpec("x", "x", "int", 1, 1, 3, 1)
    rows = generate_neighbors(Candidate({"x": 1}), (spec,), (), {})
    assert [r.parameters for r in rows] == [{"x": 2}]
```

- [ ] 执行 `uv run pytest tests/test_strategy_optimizer_neighborhood.py tests/test_strategy_optimizer_search.py -q` 确认失败。
- [ ] 实现以最小值为原点的网格索引加减一，保留整数类型，浮点采用与 search.py 一致的八位规范化；复用约束判定。按 ID、负方向、正方向排序，去重后截断，记录合法总数与已测数量。稳定性分母仅包括成功评估的合法邻居；有失败邻居则将 S 标为证据不足，不用缩小分母提高分数。
- [ ] 无邻居返回空 tuple；稳健结果标记未验证，不进入完整 R 推荐。主候选缓存命中邻居也必须计入邻域覆盖，费用预算记录命中而非重复计算。
- [ ] 重跑测试、Ruff 和 diff 检查。

## Task 4：跨段搜索与回测适配

**Files:** 新增 robustness.py、`backend/tests/test_strategy_optimizer_robustness.py`；修改 gateway.py，扩展 gateway 测试。

**Interfaces:** `RobustnessRunner.run(request: dict, progress_cb, cancel_event) -> dict`；注入 `evaluate(candidate: Candidate, window: EvaluationWindow, include_curve: bool) -> SegmentObservation` 和既有 AdaptiveSearchService。gateway 新方法 `run_robust_optimization` 构建适配器；`run_optimization` 根据模式分发。

- [ ] fake evaluate 记录每次日期、参数和信号，测试每候选完整三段、早段失败时原因保留、下一轮按累计 B 反馈、固定参考只评估一次、预算终止、留出零调用。

```python
# fixture runner 的 evaluate 将调用记录到 calls；配置有三开发段和一个留出段。
def test_search_never_evaluates_holdout(runner, robust_request, calls):
    runner.search_development(robust_request)
    assert calls
    assert all(call["role"] == "development" for call in calls)
```

- [ ] 执行 `uv run pytest tests/test_strategy_optimizer_robustness.py tests/test_strategy_optimizer_gateway.py -q` 确认新用例失败。
- [ ] 实现阶段 `preflight → baselines → search → neighborhood → frozen`；每轮累积去重候选，重算整个累计池 B，传递满足绝对门槛的 elite；没有合格 elite 时按失败门槛数量、B 排序探索，但不能推荐。停止原因仅 budget_exhausted/search_space_exhausted/cancelled，不依赖百分位收敛。
- [ ] 回测适配复用 StrategyBacktestConfig、完整资金曲线与现有结果策略；预热只生成指标，所有入场必须在窗口内；从资金净值计算年化和回撤，不使用 full 模式超额曲线。段末非成交强平，不新增虚构成交；未平仓交易数采用既有统计口径并在页面说明。
- [ ] 每个窗口检查数据覆盖和矩阵 generation；输入缺口导致不可可靠撮合则任务停止，单候选计算异常记候选失败。历史股票池缺陷输出 coverage 提示，不能伪造退市完整性。
- [ ] 完成十中心邻域后按 R 和约定决胜规则冻结前三名；复用既有去重，但必须证明不改变冻结排序。指纹加入模式、评分版本、快照摘要、日期计划、曲线要求和执行全部输入。
- [ ] 加入 `holdout 数据变化不改变冻结 ID` 的测试（开发适配只提供开发数据），并跑现有训练/旧模式 gateway 测试。

## Task 5：留出用途登记、连续诊断和恢复

**Files:** 修改 robustness.py、manager.py、store.py；新增 `backend/tests/test_strategy_optimizer_robust_recovery.py`；扩展 store/manager 测试。

**Interfaces:** 编排器增加 `run_post_freeze(frozen: tuple[RankedCandidate, ...], plan: RobustTimePlan, progress_cb, cancel_event) -> dict`；store 新增 `claim_holdout(run_id: str, usage_key: str) -> str`，返回 first/repeated，同一 run_id 恢复幂等。使用用户独立 store 根目录隔离权限。

- [ ] 测试冻结后留出失败不替换第四名；无留出显示 not_applicable；取消不能变成完整成功；恢复必须校验快照/评分版本/data generation，一项不一致就拒绝恢复并要求新任务。

```python
def test_holdout_claim_is_idempotent_and_detects_reuse(store):
    assert store.claim_holdout("run1", "strategy:2024:2026") == "first"
    assert store.claim_holdout("run1", "strategy:2024:2026") == "first"
    assert store.claim_holdout("run2", "strategy:2024:2026") == "repeated"
```

- [ ] 执行 `uv run pytest tests/test_strategy_optimizer_robust_recovery.py tests/test_strategy_optimizer_manager.py tests/test_strategy_optimizer_store.py -q` 确认失败。
- [ ] 在首次留出回测前原子登记窗口用途；登记 key 为用户范围内策略稳定 ID、资产类型和归一留出日期，不使用搜索范围变化绕开重复检测。并发任务在 manager 短锁内登记，磁盘操作按现有持久化模式处理，锁内不运行回测；测试两个任务同时登记只有一个 first。
- [ ] checkpoint 保存阶段、累计候选/指标、随机状态、已测邻域、冻结 ID、完成窗口及用途登记。恢复只执行未完成窗口；留出登记先写、回测后写结果，即使中断也不能恢复为首次未使用状态。稳健 checkpoint 与旧 search checkpoint 用 version 区分，旧模式保持原读取路径。
- [ ] 冻结前三名分别运行完整开发区间连续回测及两年、半年步进的开发滚动窗口；指标从连续曲线计算，诊断不反馈 R。参考窗口共用缓存。
- [ ] 留出复用相同固定配置与空仓起点，风险或相对默认失败→failed，交易不足→insufficient，所有门槛满足→passed；保存通过原因及数据声明。前三名序列完全不变。
- [ ] 重跑定向及旧恢复测试，核对断电原子写、候选失败、stage 事件与任务生命周期之间的区别。

## Task 6：API 集成与页面

**Files:** 修改 custom/strategy_optimizer.py、前端 api.ts、StrategyOptimizerPage.tsx 及其测试；新增 RobustnessConfig.tsx、RobustnessResults.tsx、`RobustnessResults.test.tsx`。

**Interfaces:**

```typescript
type EvaluationMode = 'legacy' | 'robust'
type HoldoutStatus = 'not_applicable' | 'pending' | 'passed' | 'failed' | 'insufficient'
type WindowPlan = { id: string; start: string; end: string; role: 'development' | 'holdout' | 'diagnostic' }
type RobustSegment = { window_id: string; annualized_return: number | null; max_drawdown: number | null;
  trade_count: number | null; baseline_delta: number | null; percentile: number | null; failures: string[] }
type RobustRecommendation = { candidate_id: string; base_score: number; robust_score: number | null;
  stability: number | null; segments: RobustSegment[]; holdout_status: HoldoutStatus }
// RobustnessResults props 接受已类型化结果，组件不自行计算分数。
```

- [ ] 先写 API 预览/运行/恢复/保存测试：授权范围、robust 非 position 拒绝、无合格推荐不能保存、已有 legacy 请求和响应不变。
- [ ] 写组件用例：三个分段行、百分点转换、留出失败仍保留原推荐顺序、未验证邻域、零推荐、旧卡片、取消和缺数据。以下测试 fixture 的 mock 结果严格匹配新 API 类型。

```tsx
it('keeps failed holdout visible without relabeling it as success', () => {
  render(<RobustnessResults result={failedHoldoutFixture} />)
  expect(screen.getByText('留出验证未通过')).toBeInTheDocument()
  expect(screen.getByText('推荐 1')).toBeInTheDocument()
})
```

- [ ] 配置组件发送预览请求并展示实际交易日切点、预算和 coverage；修改配置使旧预览失效，启动必须携带相同配置，后端重新确认数据 generation，不能依赖客户端预览摘要放行。
- [ ] 后端结果在 API 映射到上述扁平 segment 字段；内部 dataclass 不直接散落到前端。SSE 增加 stage/done/total，复用现有事件连接，不为每张推荐卡拉取单独任务。
- [ ] 比例统一在展示时乘 100，baseline_delta 使用“个百分点”；旧指标保留旧说明，新卡片显示独立段/连续开发/留出用途。
- [ ] 执行 backend API 测试；frontend 根据 package.json 真实脚本运行定向组件测试，再执行 `pnpm build`；手工查看深浅主题、窄屏、结果表滚动和失败状态。

## Task 7：全链路验证、性能与文档

**Files:** 新增 `backend/tests/test_strategy_optimizer_robust_integration.py`；更新优化插件原有用户文档所在文件（通过 `rg -n '策略优化|strategy.optimizer' docs README.md` 确定，不新增平行指南）；不改无关文件。

- [ ] 用固定合成价格和信号构造 integration fixture，覆盖 T+1、费用、价格限制、跨段持仓和预热；运行真实 StrategyBacktestService，无网络与用户本地数据依赖。

```python
def test_continuous_drawdown_is_not_max_of_segment_drawdowns():
    # 两个独立段各跌 10%，连续曲线从 1.0 跌至 0.81。
    nav = (1.0, 0.9, 0.81)
    peak = nav[0]
    drawdowns = []
    for value in nav:
        peak = max(peak, value)
        drawdowns.append(1 - value / peak)
    assert max(drawdowns) == pytest.approx(0.19)
    # integration fixture 还须断言 API 连续曲线结果为 0.19，分段结果各为 0.10。
```

- [ ] 运行所有 strategy_optimizer 测试及受影响 backtest 测试；Ruff 仅针对改动文件；前端定向测试与构建。失败先定位再修复，不根据计划预期宣称通过。
- [ ] 十年、同一股票池、同一机器记录主搜索及附加阶段耗时/峰值内存/回测调用数；验证上限公式 `3N + 3U + 3(1+W+H)` 加参考窗口，其中 N≤500，U≤200，W为滚动窗口数，H为有留出时1否则0；参考按唯一窗口及配置去重。预览展示上界，取消后核查资源释放。
- [ ] 文档说明门槛是可编辑工程起始值、排名仅针对本次候选、留出声明不能证明未被使用、重叠窗口非独立样本、无邻域或证据不足不会成为完整合格推荐。
- [ ] `git diff --check`、`git status --short` 和完整 diff 审查，确认原有工作区修改未被覆盖，运行数据/源码快照不提交。总结真实运行命令、结果和剩余风险。

## 执行顺序与评审节点

任务依赖为 1 → 2 → 3 → 4 → 5 → 6 → 7；不提前对用户开放只有部分规则的新模式。每项完成后按契约与对应测试评审，最后按 CONTRIBUTING.md 对全链路检查。目前未选择执行方式，计划评审后可选择本会话逐项实现或委派实现；未获选择前不启动产品代码开发。

## 计划自审

设计中的时间布局、同参跨段搜索、默认及固定参考、硬门槛、百分位、邻域、冻结留出、连续曲线、滚动诊断、资格检查、旧记录、取消恢复、缓存与性能均对应上方任务。真实交易日历入口与快照实例化不是已确认能力，已安排任务 1 查明并以测试证明可用；缺失时明确失败，不编造公共接口。现有工作区中已有测试与其他设计文档修改，实施时须先读取最新内容并保留。
