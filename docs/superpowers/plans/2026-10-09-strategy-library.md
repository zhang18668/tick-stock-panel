# 策略库与周期回测对比实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增可手动分档的内置策略库页面，展示策略说明并比较最近 3、6、12 个月的回测摘要。

**Architecture:** 前端以现有扩展路由注册策略库页；后端通过当前后端扩展契约提供用户分组、批量任务及结果 API。任务复用现有策略发现、回测 worker/engine、provider、HeavyJobLimiter 和 preferences 多用户隔离，按策略顺序串行执行 3 个滚动窗口，并保存紧凑摘要。

**Tech Stack:** Python、FastAPI、现有策略回测 worker/engine、preferences/settings context、React、TypeScript、TanStack Query、现有前后端扩展注册契约。

**Spec:** `docs/superpowers/specs/2026-10-09-strategy-library-design.md`

## Global Constraints

- 策略执行复用现有策略回测引擎和数据 provider，不复制执行逻辑。
- 最新可用交易日是 3、6、12 月请求窗口的共同结束日；实际窗口由后端统一计算。
- `backtest_range_guard` 开启且拒绝 1 年窗口时显示受限状态，不绕过保护。
- 缺失的数据、指标或策略能力标成不可用并给原因，不将缺失伪装为零。
- 分组名称和顺序由用户定义；策略分组只能手动操作，指标不触发自动分组。
- 持久化数据必须按用户隔离，保存使用现有 merge-write 语义，写失败保留上一份有效结果。
- 服务器下载的策略源文件属于用户数据，不提交到 Git。
- 保留当前工作区已有的 `StrategyOptimizerPage.tsx` 和对应测试修改，不覆盖或夹带到策略库改动中。
- 单次全量更新有界、串行，单项失败隔离；任务可取消、可重试，并可识别进程重启时遗留的运行中状态。

## Review Focus

- 末月日期不存在（例如 5 月 31 日向前滚 3 个月）时，窗口回退到目标月最后一天；在窗口计算测试中固定此规则。
- provider 声明分钟能力但窗口数据不完整时，策略/窗口标记不可用；在任务规划测试中验证不会用日线结果冒充分钟回测。
- 一个策略窗口失败后其余窗口和策略仍完成；在 manager 测试中断言状态与未执行项目。
- 用户偏好中已有未知字段或旧结构时，分组/结果写入保留旧数据；在 store/preferences 测试中验证 merge-write 和隔离。
- 任务运行期间重复启动、取消以及应用重启恢复状态均有确定结果；在 manager API 生命周期测试中覆盖。

---

## 文件结构

- `backend/app/custom/strategy_library.py`：按现有后端扩展入口注册策略库 router 和任务服务，不侵入主应用生命周期。
- `backend/app/strategy_library/contracts.py`：请求/响应模型、状态枚举、周期与统计摘要契约。
- `backend/app/strategy_library/manager.py`：单用户任务排队、串行执行、取消、重试、故障隔离及恢复标记。
- `backend/app/strategy_library/store.py`：策略库摘要与分组的用户偏好读写，沿用偏好层 merge-write。
- `backend/app/api/strategy.py`：只补充策略详情中真实存在的规则及执行元信息，保持既有 API 兼容。
- `backend/app/services/preferences.py`：将策略库个人偏好加入多用户隔离白名单。
- `backend/tests/test_strategy_library_manager.py`：周期任务调度和状态生命周期。
- `backend/tests/test_strategy_library_store.py`：偏好写入和用户隔离。
- `backend/tests/test_strategy_library_api.py`：路由契约、权限和错误响应。
- `backend/tests/test_strategy_library_windows.py`：日历月、交易日边界及共同截止日。
- `backend/tests/test_strategy_detail_metadata.py`：策略详情新字段和旧字段兼容。
- `frontend/src/custom/strategy-library/extension.tsx`：注册完整页面路由和导航。
- `frontend/src/custom/strategy-library/api.ts`：策略库 API 类型与请求。
- `frontend/src/custom/strategy-library/StrategyLibraryPage.tsx`：页面编排、查询和用户操作。
- `frontend/src/custom/strategy-library/StrategyLibraryPage.test.tsx`：页面主要交互状态。
- `frontend/src/custom/strategy-library/components/StrategyCard.tsx`：策略卡片和周期指标展示。
- `frontend/src/custom/strategy-library/components/StrategyDetail.tsx`：策略规则、参数及回测详情。
- `frontend/src/custom/strategy-library/components/StrategyGroups.tsx`：自定义分档、排序和手动移动。
- `frontend/src/custom/strategy-library/components/BacktestJobPanel.tsx`：全量/单策略更新、进度、取消、失败和重试。
- `frontend/src/lib/queryKeys.ts`：添加策略库策略、分组、结果和任务查询键。
- `frontend/src/custom/strategy-library/extension.test.tsx`：验证扩展注册页面及导航项。

## Task 1: 后端周期契约与窗口计算

**Files:**
- Create: `backend/app/strategy_library/__init__.py`
- Create: `backend/app/strategy_library/contracts.py`
- Create: `backend/app/strategy_library/windows.py`
- Test: `backend/tests/test_strategy_library_windows.py`
- Test: `backend/tests/test_strategy_library_contracts.py`

**Interfaces:**
- `BacktestPeriod`: 固定枚举 `3m`、`6m`、`12m`。
- `BacktestWindow`: `period: BacktestPeriod`, `requested_start: date`, `requested_end: date`, `actual_start: date | None`, `actual_end: date | None`, `availability: str`, `reason: str | None`。
- `build_rolling_windows(latest_trading_day: date) -> list[BacktestWindow]`: 生成统一截止日的 3 个请求窗口；按日历月回溯，目标月缺少对应日期时取目标月最后一天。实际数据范围由调用方回填。
- `StrategyLibraryTaskStatus`: `queued | running | completed | completed_with_errors | cancelled | failed | interrupted`。

- [ ] **Step 1: 写窗口边界测试**

```python
def test_windows_share_latest_trading_day_and_use_calendar_months():
    windows = build_rolling_windows(date(2026, 10, 8))
    assert [window.period for window in windows] == [
        BacktestPeriod.THREE_MONTHS,
        BacktestPeriod.SIX_MONTHS,
        BacktestPeriod.TWELVE_MONTHS,
    ]
    assert {window.requested_end for window in windows} == {date(2026, 10, 8)}
    assert windows[0].requested_start == date(2026, 7, 8)


def test_month_end_clamps_to_last_day_of_target_month():
    windows = build_rolling_windows(date(2026, 5, 31))
    assert windows[0].requested_start == date(2026, 2, 28)
```

- [ ] **Step 2: 运行定向测试确认窗口实现缺失时失败**

运行：`cd backend; uv run --frozen pytest tests/test_strategy_library_windows.py -q`
预期：测试因模块/函数尚未实现而失败。

- [ ] **Step 3: 实现周期契约和日历窗口函数**

```python
def build_rolling_windows(latest_trading_day: date) -> list[BacktestWindow]:
    """Return 3/6/12 calendar-month windows ending on one trading day."""
    ...
```

月末夹取使用标准库日历能力；函数只计算请求日期，不读取行情，也不伪造实际覆盖范围。

- [ ] **Step 4: 运行窗口与 schema 定向测试**

运行：`cd backend; uv run --frozen pytest tests/test_strategy_library_windows.py tests/test_strategy_library_contracts.py -q`
预期：窗口边界和序列化契约测试通过。

## Task 2: 策略详情规则和执行元信息

**Files:**
- Modify: `backend/app/api/strategy.py`
- Test: `backend/tests/test_strategy_detail_metadata.py`
- Review: `backend/app/strategy/builtin/*.py`

**Interfaces:**
- `/api/strategies` 现有响应字段保持不变；策略条目增加 `rules` 和 `execution` 元信息，仅返回策略模块实际声明并经过 JSON 安全规范化的字段。
- `execution` 仅允许展示可解释策略回测方式所需元数据；缺字段返回空值/明确 unavailable，不根据文件名推断。

- [ ] **Step 1: 为策略条目新增字段兼容测试**

```python
def test_strategy_detail_includes_declared_rules_and_execution_metadata(client):
    response = client.get('/api/strategies')
    assert response.status_code == 200
    item = find_strategy(response.json(), 'known_builtin')
    assert item['rules'] == ['真实策略模块声明的规则']
    assert item['execution']['mode'] == 'daily'


def test_missing_metadata_keeps_legacy_strategy_fields(client):
    item = find_strategy(client.get('/api/strategies').json(), 'legacy_builtin')
    assert item['name']
    assert item['description']
    assert item['rules'] == []
    assert item['execution']['mode'] is None
```

实现测试样本时使用仓库中确实存在并声明相应 META/RULES 的内置策略，不伪造策略模块。

- [ ] **Step 2: 运行详情定向测试并确认失败**

运行：`cd backend; uv run --frozen pytest tests/test_strategy_detail_metadata.py -q`
预期：新字段断言失败，现有详情接口仍可被旧测试读取。

- [ ] **Step 3: 以兼容方式映射真实 RULES 与执行 META**

保持当前 `_strategy_detail` 的字段和参数/风控构造不变，只添加安全归一化后的 `rules`、`execution`；未知策略类型和缺失元信息不能导致整个列表接口失败。

- [ ] **Step 4: 运行策略详情相关测试**

运行：`cd backend; uv run --frozen pytest tests/test_strategy_detail_metadata.py tests/test_strategy_registry.py tests/test_strategy_access.py -q`
预期：新旧详情契约、策略发现和权限相关测试通过。

## Task 3: 用户隔离的策略库存储

**Files:**
- Modify: `backend/app/services/preferences.py`
- Create: `backend/app/strategy_library/store.py`
- Test: `backend/tests/test_strategy_library_store.py`
- Review: `backend/tests/test_preferences_cache.py`
- Review: `backend/tests/test_preferences_concurrent_write.py`

**Interfaces:**
- 个人偏好键：`strategy_library_groups` 和 `strategy_library_results`，两者归入 `_USER_PREFERENCE_KEYS`。
- `StrategyLibraryStore.get_groups() -> list[StrategyGroup]`。
- `StrategyLibraryStore.save_groups(groups: list[StrategyGroup]) -> None`。
- `StrategyLibraryStore.get_results() -> dict[str, StrategyResultSummary]`。
- `StrategyLibraryStore.save_result(strategy_id: str, period: BacktestPeriod, summary: StrategyResultSummary) -> None`。
- 结果键由稳定策略 ID 与周期确定；摘要带窗口实际日期、配置/源码指纹和更新时间。失败写入不得覆盖之前有效摘要。

- [ ] **Step 1: 添加偏好保留和用户隔离测试**

```python
def test_strategy_library_preferences_are_user_scoped(settings_context):
    save_strategy_library_preferences({'strategy_library_groups': [{'id': 'g1'}]})
    assert read_user_preferences('user_a')['strategy_library_groups'] == [{'id': 'g1'}]
    assert read_user_preferences('user_b').get('strategy_library_groups', []) == []


def test_saving_result_preserves_unknown_preference_keys(store, preferences):
    preferences.update({'unrelated_user_key': {'keep': True}})
    store.save_result('builtin_x', BacktestPeriod.THREE_MONTHS, sample_summary())
    assert preferences['unrelated_user_key'] == {'keep': True}
```

- [ ] **Step 2: 运行 store 测试确认白名单/存储功能尚未实现时失败**

运行：`cd backend; uv run --frozen pytest tests/test_strategy_library_store.py -q`
预期：新存储契约测试失败。

- [ ] **Step 3: 实现 schema 校验、merge-write 和用户隔离**

```python
class StrategyLibraryStore:
    def get_groups(self) -> list[StrategyGroup]: ...
    def save_groups(self, groups: list[StrategyGroup]) -> None: ...
    def get_results(self) -> dict[str, StrategyResultSummary]: ...
    def save_result(self, strategy_id: str, period: BacktestPeriod,
                    summary: StrategyResultSummary) -> None: ...
```

对历史偏好缺字段、未知字段、损坏的单条结果采用有界校验；无效条目标示无法解析或跳过该条，保留其余用户偏好。

- [ ] **Step 4: 运行 store 与 preferences 定向测试**

运行：`cd backend; uv run --frozen pytest tests/test_strategy_library_store.py tests/test_preferences_cache.py tests/test_preferences_concurrent_write.py -q`
预期：用户隔离、合并写入、缓存一致性和并发写入测试通过。

## Task 4: 串行回测任务管理器

**Files:**
- Create: `backend/app/strategy_library/manager.py`
- Modify: `backend/app/backtest/strategy.py`
- Review: `backend/app/api/backtest.py`
- Review: `backend/app/backtest/worker.py`
- Review: `backend/app/strategy/engine.py`
- Test: `backend/tests/test_strategy_library_manager.py`

**Interfaces:**
- `StrategyLibraryManager.start(user_id: str, strategy_ids: list[str] | None) -> StrategyLibraryTask`：`None` 表示全部可用策略。
- `StrategyLibraryManager.get_task(user_id: str, task_id: str) -> StrategyLibraryTask | None`。
- `StrategyLibraryManager.cancel(user_id: str, task_id: str) -> bool`。
- `StrategyLibraryManager.retry_failed(user_id: str, task_id: str, items: list[tuple[str, BacktestPeriod]] | None) -> StrategyLibraryTask`。
- 任务按 strategy ID 和 3/6/12m 顺序串行；每次调用现有回测服务，映射现有统计字段形成摘要。不新建一套指标算法。

- [ ] **Step 1: 写任务状态、故障隔离和取消测试**

```python
def test_one_window_failure_does_not_stop_remaining_windows(manager, runner):
    runner.fail_on(('builtin_a', BacktestPeriod.THREE_MONTHS))
    task = manager.start('user-a', ['builtin_a', 'builtin_b'])
    manager.wait(task.id)
    assert task.item('builtin_a', BacktestPeriod.THREE_MONTHS).status == 'failed'
    assert task.item('builtin_a', BacktestPeriod.SIX_MONTHS).status == 'completed'
    assert task.item('builtin_b', BacktestPeriod.THREE_MONTHS).status == 'completed'


def test_cancel_stops_after_current_backtest(manager, runner):
    task = manager.start('user-a', ['builtin_a', 'builtin_b'])
    runner.block_current()
    manager.cancel('user-a', task.id)
    runner.release_current()
    manager.wait(task.id)
    assert task.status == StrategyLibraryTaskStatus.CANCELLED
    assert task.unstarted_items_are_cancelled()
```

- [ ] **Step 2: 运行 manager 测试确认失败**

运行：`cd backend; uv run --frozen pytest tests/test_strategy_library_manager.py -q`
预期：任务管理器缺失时测试失败。

- [ ] **Step 3: 编写最小串行 manager 并接入现有回测调用链**

任务持有取消事件、完成/失败/未执行明细和用户 ID；使用 HeavyJobLimiter 与现有后台执行方式。任务恢复时将上次进程遗留的 running 标记为 interrupted。重试只重放失败或明确选中的策略/周期项。全量项预计约 120 次，不能并发 fan-out。

- [ ] **Step 4: 测试重复启动、失败隔离、重试和恢复标记**

运行：`cd backend; uv run --frozen pytest tests/test_strategy_library_manager.py tests/test_backtest_stream_date_guard.py tests/backtest/test_worker_process.py -q`
预期：任务幂等/占用规则明确，失败项可重试，现有回测日期限制继续有效。

## Task 5: 策略库 API 与后端扩展接线

**Files:**
- Create: `backend/app/strategy_library/api.py`
- Create: `backend/app/custom/strategy_library.py`
- Modify only if existing registration requires it: `backend/app/extensions/loader.py`
- Test: `backend/tests/test_strategy_library_api.py`
- Review: `backend/tests/test_extensions.py`

**Interfaces:**
- `GET /api/strategy-library`: 返回可用策略详情、用户分组、最近结果和数据日期。
- `POST /api/strategy-library/jobs`: 启动全部或指定策略的更新。
- `GET /api/strategy-library/jobs/{task_id}`: 返回任务进度、当前项和逐项状态。
- `POST /api/strategy-library/jobs/{task_id}/cancel`：请求安全取消。
- `POST /api/strategy-library/jobs/{task_id}/retry`：重试失败项或请求选定项。
- `PUT /api/strategy-library/groups`：保存用户自定义分组及策略归属。
- 所有任务和分组 API 以认证用户身份隔离；读他人 task ID 返回 404，避免泄露任务存在性。

- [ ] **Step 1: 写 API 正常、隔离及重复请求测试**

```python
def test_job_cannot_be_read_or_cancelled_by_another_user(client_for_user_a, client_for_user_b):
    task_id = client_for_user_a.post('/api/strategy-library/jobs', json={}).json()['id']
    assert client_for_user_b.get(f'/api/strategy-library/jobs/{task_id}').status_code == 404
    assert client_for_user_b.post(f'/api/strategy-library/jobs/{task_id}/cancel').status_code == 404


def test_invalid_strategy_id_returns_structured_error(client):
    response = client.post('/api/strategy-library/jobs', json={'strategy_ids': ['../secret']})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'invalid_strategy_id'
```

- [ ] **Step 2: 运行 API 测试确认接口未注册时失败**

运行：`cd backend; uv run --frozen pytest tests/test_strategy_library_api.py -q`
预期：策略库路由返回 404，新增测试失败。

- [ ] **Step 3: 通过后端扩展 registrar 注册 API 与服务**

路由从依赖获取当前用户身份、preferences/store 和 manager；启动时恢复 interrupted 状态。扩展注册遵守当前 loader 契约，不手改 `main.py`；若 loader 确实未自动发现 backend custom 模块，最小改其真实注册点并追加加载失败隔离断言。

- [ ] **Step 4: 运行 API、扩展和策略权限测试**

运行：`cd backend; uv run --frozen pytest tests/test_strategy_library_api.py tests/test_extensions.py tests/test_strategy_access.py -q`
预期：用户隔离、认证、字段校验、错误码和扩展失败隔离通过。

## Task 6: 前端扩展、API 和策略分档

**Files:**
- Create: `frontend/src/custom/strategy-library/extension.tsx`
- Create: `frontend/src/custom/strategy-library/api.ts`
- Create: `frontend/src/custom/strategy-library/StrategyLibraryPage.tsx`
- Create: `frontend/src/custom/strategy-library/components/StrategyGroups.tsx`
- Modify: `frontend/src/lib/queryKeys.ts`
- Test: `frontend/src/custom/strategy-library/extension.test.tsx`
- Test: `frontend/src/custom/strategy-library/StrategyLibraryPage.test.tsx`
- Review: `frontend/src/extensions/types.ts`
- Review: `frontend/src/extensions/registry.ts`

**Interfaces:**
- 页面通过现有 `FrontendExtension` 注册绝对路由 `/strategy-library` 和导航项，不直接修改核心路由。
- API 客户端仅在 `strategy-library/api.ts` 封装 endpoint；缓存键放 `queryKeys.ts`。
- 分组更新发送完整且稳定排序后的 `{groups:[{id,name,order,strategy_ids}]}`，未分组策略由后端/前端统一按无 group membership 推导。

- [ ] **Step 1: 写扩展发现、空页和手动分组测试**

```tsx
it('registers strategy library route and navigation item', () => {
  const extension = strategyLibraryExtension
  expect(extension.routes?.[0].path).toBe('/strategy-library')
  expect(extension.navigation?.[0].routeId).toBe(extension.routes?.[0].id)
})

it('moves a strategy only after the user selects a group', async () => {
  render(<StrategyLibraryPage initialData={sampleLibrary()} />)
  await user.click(screen.getByRole('button', { name: '放入 强势' }))
  expect(saveGroups).toHaveBeenCalledWith(expect.objectContaining({
    groups: expect.arrayContaining([expect.objectContaining({ strategy_ids: ['builtin_x'] })]),
  }))
})
```

- [ ] **Step 2: 运行前端定向测试确认未实现状态**

运行：`cd frontend; pnpm vitest run src/custom/strategy-library/extension.test.tsx src/custom/strategy-library/StrategyLibraryPage.test.tsx`
预期：测试文件/扩展尚未实现而失败。

- [ ] **Step 3: 实现 API、查询键、路由注册和分组交互**

沿用 TanStack Query、统一 API 客户端、既有按钮/卡片/拖放设计模式；支持创建、重命名、排序、删除分组，删除后策略归未分组。名称和顺序只由显式用户操作改变。

- [ ] **Step 4: 运行前端定向测试与构建**

运行：`cd frontend; pnpm vitest run src/custom/strategy-library/extension.test.tsx src/custom/strategy-library/StrategyLibraryPage.test.tsx; pnpm build`
预期：路由和分组行为测试通过，前端构建通过。

## Task 7: 策略卡片、详情和回测任务操作

**Files:**
- Create: `frontend/src/custom/strategy-library/components/StrategyCard.tsx`
- Create: `frontend/src/custom/strategy-library/components/StrategyDetail.tsx`
- Create: `frontend/src/custom/strategy-library/components/BacktestJobPanel.tsx`
- Modify: `frontend/src/custom/strategy-library/StrategyLibraryPage.tsx`
- Modify: `frontend/src/custom/strategy-library/StrategyLibraryPage.test.tsx`

**Interfaces:**
- 策略卡片接收策略说明、分组名、3/6/12m 指标摘要和可用状态；不在组件计算回测统计。
- 详情展示 RULES、参数、风险和 execution 元数据、请求/实际窗口、配置/源码指纹与结果状态。
- 任务面板调用 Task 5 API，实现全部更新、单策略更新、进度刷新、取消、失败项重试。

- [ ] **Step 1: 增加卡片和详情的状态测试**

```tsx
it('renders missing period metrics as unavailable with a reason', () => {
  render(<StrategyCard strategy={strategyWithoutYearData} />)
  expect(screen.getByText('1 年')).toBeVisible()
  expect(screen.getByText('不可用')).toBeVisible()
  expect(screen.getByText('回测区间超过当前限制')).toBeVisible()
})

it('shows partial task progress and lets user retry failed periods', async () => {
  render(<BacktestJobPanel task={partiallyFailedTask} />)
  expect(screen.getByText('已完成 5 / 6')).toBeVisible()
  await user.click(screen.getByRole('button', { name: '重试失败项' }))
  expect(retryTask).toHaveBeenCalledWith(partiallyFailedTask.id)
})
```

- [ ] **Step 2: 运行前端状态测试确认失败**

运行：`cd frontend; pnpm vitest run src/custom/strategy-library/StrategyLibraryPage.test.tsx`
预期：组件状态断言失败或组件未导出。

- [ ] **Step 3: 完成 UI 状态和任务操作**

覆盖初次加载、无策略、源码不可用、provider 能力不足、数据不足、部分成功、整体错误、运行中、取消中和 1 年 guard 拒绝状态。对任务状态轮询设置有限间隔，仅运行/排队任务轮询；完成或失败即停止。

- [ ] **Step 4: 运行页面测试和前端构建**

运行：`cd frontend; pnpm vitest run src/custom/strategy-library/StrategyLibraryPage.test.tsx; pnpm build`
预期：卡片、详情、分组和任务状态断言通过，构建通过。

## Task 8: 整体回归和差异复核

**Files:**
- Review all files listed in Tasks 1–7.
- Preserve unrelated pre-existing files: `frontend/src/custom/strategy-optimizer/StrategyOptimizerPage.tsx`, `frontend/src/custom/strategy-optimizer/StrategyOptimizerPage.test.tsx`.

- [ ] **Step 1: 运行后端策略库及相邻回归测试**

运行：`cd backend; uv run --frozen pytest tests/test_strategy_library_windows.py tests/test_strategy_library_contracts.py tests/test_strategy_library_store.py tests/test_strategy_library_manager.py tests/test_strategy_library_api.py tests/test_strategy_detail_metadata.py tests/test_extensions.py tests/test_preferences_cache.py tests/test_preferences_concurrent_write.py tests/test_strategy_access.py tests/backtest/test_worker_process.py tests/test_backtest_stream_date_guard.py -q`
预期：所有定向回归通过，未运行的测试不得报告为通过。

- [ ] **Step 2: 运行前端策略库测试及生产构建**

运行：`cd frontend; pnpm vitest run src/custom/strategy-library; pnpm build`
预期：策略库前端测试和构建通过。

- [ ] **Step 3: 检查 diff、敏感文件和格式**

运行：`git diff --check; git status --short --branch; git diff --stat; git diff -- frontend/src/custom/strategy-optimizer/StrategyOptimizerPage.tsx frontend/src/custom/strategy-optimizer/StrategyOptimizerPage.test.tsx`
预期：diff check 无输出；变更仅包含策略库设计/实现所需文件；策略源码、密钥、用户数据没有被纳入 Git；两个既有优化器修改与任务前一致。

- [ ] **Step 4: 交付可审阅结果**

列出具体改动、真实执行的验证命令与结果、1 年窗口 guard 和 provider 数据能力限制、未覆盖范围。未经用户另行确认，不提交、不推送、不部署。
