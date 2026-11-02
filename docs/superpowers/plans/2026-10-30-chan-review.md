# 缠论复盘页面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增独立的缠论复盘页面，生成并保存全市场或选定股票的一买、二买、三买历史记录，支持原图与后续走势人工复盘。

**Architecture:** 从现有 chan.py 适配器提取逐根计算接口，保持即时分析兼容。复用 MiningRunStore 的独立命名空间保存任务元数据、重任务准入和跨平台单写者锁；窄职责归档模块保存内容寻址输入、原图快照和 Parquet 信号索引。新增扩展路由和页面，直接复用 ChanChart/EChartsCandlestick。

**Tech Stack:** Python 3.11+、现有 chan.py、Polars、标准库 multiprocessing/gzip/hashlib、FastAPI、React 18、TypeScript、TanStack Query、既有 ECharts。

**Spec:** `docs/superpowers/specs/2026-10-30-chan-review-design.md`（用户已确认）。

## Global Constraints

- 首版不计算胜率、止盈止损或自动交易。
- 沿用既有 K 线风格和已固定版本的 chan.py，不引入第二套缠论算法。
- 复盘页必须有显式导航项，避免入口只存在于侧栏展开时的顶部小按钮。
- 来源分为 `observed`（本系统盘后实际扫描）和 `backfill`（使用现有历史数据逐日补算）。两类默认分开查询。
- 每次观测事实不可覆盖；信号消失后仍可查询原始记录。
- 单任务最多252个观测交易日；每只股票计算输入最多2000根，记录实际预热覆盖。
- 只读本地已同步行情，不在批量任务中为每只股票发起外部下载。
- 未认证多用户请求拒绝，不能回退 standalone。
- 不自动删除档案，不新增无人值守定时任务，不增加数据库迁移或新的 SSE 协议。
- 未经本次单独要求不自动提交、推送或部署。

## Review Focus

1. 历史窗口左侧已存在的信号不能冒充首次出现，且未来K线不得提前进入原图；Task 1/2 固定样本断言。
2. 复权或数据修订不能把旧结构价格直接贴入新口径后续图；Task 4 验证原图不变和后图独立。
3. 空结果与漏扫/失败不同，失败不能导致旧信号被判消失；Task 2/3 对覆盖记录和状态断言。
4. 刷新、重试、进程重启和跨用户访问不能重复登记或越权；Task 2/3 幂等、检查点、404测试。
5. 周末/停牌/未收盘/末周不能生成假的观测日期；Task 1/3 验证使用实际仓库日期和保守周规则。

---

### Task 1: 提取可增量推进的 chan.py 计算核心

**Files:** Modify `backend/app/services/chan_analysis.py`; create `backend/tests/test_chan_frames.py`.

**Interfaces:**

```python
def iter_chan_frames(
    rows: list[dict], period: Literal["day", "week"], *,
    observed_dates: set[str], cancel_event=None,
) -> Iterator[tuple[str, dict]]:
    """Yield (observation_date, analysis) using only that prefix of the input."""
```

`analysis` 保持当前 analyze 的 rows/structures/warnings/asOf/ruleVersion/engine 字段。既有 `analyze(rows, period, now=...)` 签名及返回行为不变。只提取原有算法流程，不改 vendored 上游。

- [ ] Step 1: 增加失败测试，用已有 `tests.test_chan_analysis.bars` 固定数据；对3个观测日比较逐帧结果与单独截断 analyze 的几何、指标、asOf。对比时仅忽略明确的执行时间字段，不能忽略价格或确认日期。

```python
data = bars(150)
frames = dict(iter_chan_frames(data, "day", observed_dates={"2025-03-11", "2025-04-10"}))
assert len(frames["2025-03-11"]["rows"]) == 70
assert all(s["end"]["date"] <= "2025-03-11" for s in frames["2025-03-11"]["structures"])
```

- [ ] Step 2: Run `.venv/Scripts/python.exe -m pytest tests/test_chan_frames.py -q`; expected failure: iter_chan_frames 不存在。
- [ ] Step 3: 提取标准化、引擎创建、喂单根和快照生成；仅向引擎前进一次。周线在下一周首个实际输入日才将上一周加入证据，最后未完成周保留在图上。取消事件在每根之间检查并结束生成。
- [ ] Step 4: 增加周线跨年、日内尚未定版、空输入、相等/重复日期拒绝、取消后无后续帧测试；确认无自造周末日期，并与现有周线确认日期回归一致。
- [ ] Step 5: Run `.venv/Scripts/python.exe -m pytest tests/test_chan_frames.py tests/test_chan_analysis.py -q`; expected all pass。当前150根样本已证实包含真实 B1/B2；另外固定一组能产生 B3a/B3b 的上游行情样本并保存确定的日期/类型期望，不能用伪造计算结果代替引擎正例。

### Task 2: 不可变档案、观测索引与分页查询

**Files:** Create `backend/app/chan_review/__init__.py`, `contracts.py`, `store.py`, `backend/tests/test_chan_review_store.py`.

**Interfaces:**

```python
class ChanReviewArchive:
    def __init__(self, data_dir: Path): ...
    def save_input(self, owner: str, rows: list[dict]) -> str: ...
    def save_observation(self, owner: str, run_id: str, symbol: str,
                         name: str, source: str, frame: dict,
                         input_hash: str, left_censored: bool) -> dict: ...
    def publish_run(self, owner: str, run_id: str, coverage: dict) -> None: ...
    def list_signals(self, owner: str, filters: dict, page: int, page_size: int) -> dict: ...
    def get_signal(self, owner: str, signal_id: str) -> dict: ...
    def get_snapshot(self, owner: str, snapshot_id: str) -> dict: ...
```

布局：`research/chan_review/archives/<sha256(owner)>/inputs/<hash>.json.gz`、`snapshots/<hash>.json.gz`、每任务 observations Parquet 和 coverage JSON。所有标识由服务端生成且校验；输入按内容寻址、快照以数据与规则摘要寻址，不把任意字符串作为路径。元数据 owner 身份不能接受客户端覆盖。

- [ ] Step 1: 写失败测试：同一输入保存两次只生成一个 blob；两用户同ID不可互读；`../x` 和非法hash拒绝；删除源行情文件后原快照仍可读；更换引擎版本不覆盖旧快照。
- [ ] Step 2: Run `.venv/Scripts/python.exe -m pytest tests/test_chan_review_store.py -q`; expected missing-module failure。
- [ ] Step 3: 实现路径约束及压缩JSON，复用 atomic_write_text/atomic_write_parquet；以锁内单写者和唯一目标保证现有原子写helper可用。先完整保存内容，再发布索引。失败不得写 committed 标记。
- [ ] Step 4: 保存正信号及无信号的成功覆盖事实；只收买点 B 前缀，保留 1p/2s/3a/3b 类型。索引只引用输入及快照，不重复保存三年行情。查询以 owner/source/period/rule partition 限定 Parquet scan，日期与类型过滤下推，默认每页30、最大100。
- [ ] Step 5: 列表归并连续出现区间，保留最初快照、最近观测和所有历史版本；没有成功扫描证据的日子不能推断消失。首个补算日期已存在的信号标记 left_censored。重复跑同一输入/规则/观测日不新增重复事实；不同来源和规则不能被合并。
- [ ] Step 6: 用测试输入对分类与归并作明确断言：B1/B1p 归一买但保留原类型、B2/B2s 归二买、B3a/B3b 归三买；一次失败覆盖不关闭事件，一次完整负观测关闭事件，后续重现创建新出现区间。跨页总数和分类计数一致。
- [ ] Step 7: Run store suite；expected all pass。不得对失败读取返回空列表来伪装正常零信号。

### Task 3: 盘后扫描任务、数据版本和受控扩展 API

**Files:** Create `backend/app/chan_review/scanner.py`, `jobs.py`, `backend/app/custom/chan_review.py`, `backend/tests/test_chan_review_jobs.py`, `test_chan_review_api.py`.

**Interfaces:**

```python
class ReviewRunRequest(BaseModel):
    source: Literal["observed", "backfill"]
    period: Literal["day", "week"] = "day"
    scope: Literal["market", "watchlist", "symbols"] = "market"
    symbols: list[str] = Field(default_factory=list, max_length=10000)
    start: date
    end: date
    resume_from: str | None = None

class ChanReviewJobs:
    def create(self, owner: str, request: ReviewRunRequest, repo) -> dict: ...
    def list(self, owner: str) -> list[dict]: ...
    def get(self, owner: str, run_id: str) -> dict: ...
    def cancel(self, owner: str, run_id: str) -> dict: ...
    def shutdown(self) -> None: ...
```

路由前缀 `/api/custom/chan-review`，POST/GET runs、GET runs/{id}、POST cancel、GET signals、GET signals/{id}、GET snapshots/{id}、GET signals/{id}/following（返回后续统一口径行情）。实际路由通过 `BackendExtensionRegistrar.include_router` 注册。新 API 都是本任务待实现接口。

- [ ] Step 1: 写失败测试：跨用户读/取消返回404，多用户无认证返回401，standalone归属独立；客户端伪造owner字段因 extra=forbid 被拒绝。日期逆序、未来日期、超过252实际交易日、非法股票/资产类型以及盘中 observed 扫描拒绝。
- [ ] Step 2: Run jobs/API suites；expected missing-module failure。
- [ ] Step 3: 创建 `MiningRunStore(data_dir, namespace="chan_review")` 保存任务清单、事件和摘要；归属从 request.state.current_user 与 app_mode 判定，沿用已有身份对象。任务状态兼容现有 transition_status；终态历史不改写。
- [ ] Step 4: API 只创建任务。后台协调器取得现有 `shared_heavy_job_limiter.slot('exclusive', cancel_event=...)` 准入；使用一个 spawn 计算进程，传文件引用和已验证owner，不pickle仓库或引擎。工作进程以 `MiningProcessLock(data_dir/'research'/'chan_review')` 持有独立单写者锁；不能占用现有 mining 根目录锁。
- [ ] Step 5: 读取 `get_instruments()` 的股票集合，按不超过100只一批调用 `get_daily_batch(..., columns=['symbol','date','open','high','low','close','volume'])`，按股票处理，warmup最多2000行。自选范围通过服务端已认证用户自选存储解析，不能读取其他人的自选；先定位现有 watchlist 仓储调用，再接线。结束前检查 `get_enriched_generation` 与输入物化前一致，否则不发布本次混杂结果。
- [ ] Step 6: 生成日期从实际输入交易日集合取；区分计划数、成功、失败、缺行情和进度。失败股票有具体记录并继续隔离；部分失败任务以 failed 终态及 explicit partial coverage 表达，有效结果可在版本一致后单独发布，界面明确「部分结果」，不能标成完整全市场扫描。
- [ ] Step 7: 检查点按已完成股票保存；取消/重启保留完整的已保存内容。重试创建新 run，resume_from 指向拥有的原run；验证输入/规则摘要一致后跳过完成股票，否则另起新计算。未完成股票从其输入重新推进，不反序列化任意 pickle。孤儿识别不能只看队列内存：遵循工作进程锁与PID是否仍活跃，不能把仍在运行的子进程标成已停止。
- [ ] Step 8: 测试 generation变化、重复日期拒绝、无信号与缺数据区分、取消排队与运行任务、同参重跑、重启、任务窗口上限、失败子进程，以及后续行情不会覆盖原输入。运行 jobs/API suite 和 Task1/2 suites，expected all pass。

### Task 4: 缠论复盘页面与原图/后图回放

**Files:** Modify `frontend/src/custom/chan/extension.tsx`, `extension.test.ts`, `ChanChart.tsx`, `frontend/src/lib/api.ts`, `queryKeys.ts`; create `ChanReviewPage.tsx`, `ChanReviewChart.tsx`, `ChanReviewRunForm.tsx`, `ChanReviewPage.test.tsx`, `ChanReviewChart.test.tsx`.

**Interfaces:** api.ts 增加任务、信号列表、详情、快照、后续行情的明确TS类型与上述请求；QK 提供 owner/session、filters、signal/snapshot/run ID 的集中查询键。现有 api.chanAnalyze 兼容不变。

- [ ] Step 1: jsdom先写测试：空档案引导、分类/日期/来源/周期查询、分页、选中信号、上一只/下一只、查询失败重试、切股慢响应不串图、任务创建/取消/刷新重连。仅 mock 网络与canvas边界，保留真实 QueryClient。
- [ ] Step 2: 新增 lazy `/chan-review` 路由和「缠论复盘」navigation 项；保留已有「缠论分析」入口。测试导航绑定和路由冲突隔离；借助现有 Layout 的导航图标实现折叠可见，不改 Layout。
- [ ] Step 3: 页头日期语义显式选择首次观测/发生日，默认最近已有档案；提供真实归档/历史补算分开筛选，一买/二买/三买标签与原始子类型。自适应列表+主图区；表格有发生日、首次观测、来源、状态和左截断提示。
- [ ] Step 4: 任务表单包含源、周期、范围和日期；创建后显示进度/覆盖数、失败与取消；仅活跃任务轮询，终态停止轮询并精确失效列表。跨用户登录变化必须清除之前用户的选中记录和详情缓存。
- [ ] Step 5: 原图直接渲染归档 OHLC 和 structures，不调用当前分析API重新生成；高亮原选中信号，时间轴截断于观测日。复用 ChanChart 增加最小可选参数以限制显示范围或增加历史锚点，不复制其绘图逻辑。
- [ ] Step 6: 后图使用独立的当前统一口径行情，保留原信号日期标记；默认定位到观测时点，逐根前/后、播放暂停、速度及回到起点只揭示已到达的行。首版后图不覆盖原结构价格；口径变化提示可回原图对照。
- [ ] Step 7: 每次切股/信号/模式重置播放计时器；卸载清理timer；末尾自动停止；无后续行情显示明确空态。控件支持键盘，窄屏布局堆叠，样式与现有 K 线一致。
- [ ] Step 8: Run `pnpm exec vitest run src/custom/chan src/components/EChartsCandlestick.test.tsx src/extensions/runtime.test.ts`; expected all pass。测试原图不包含未来行、后图每步正好多一行、后退隐藏未来、不把当前结构写回旧快照。

### Task 5: 完整验证、复审与周报

**Files:** Update本计划状态、规格交付记录；按 weekly-work-report 规则更新共享周报。

- [ ] Step 1: Run backend相关 chan/frames/review、extensions、mining_jobs、mining_process_lock 测试，确认原有任务存储与锁未回归；Ruff仅检查本次一方文件，不重写vendored源码。
- [ ] Step 2: Run frontend全量 Vitest（将原有2份node:test用Node独立运行）和 `pnpm build`；如原信号库120ms等待测试再次失败，记录具体失败，不隐瞒或为了全绿改无关代码。
- [ ] Step 3: Run `git diff --check`，审查全部新增文件，确认无私有行情、用户记录或本地绝对路径入库。真实行情验收仅使用当前窗口可用数据；没有本地数据时明确说明不能完成全市场实测。
- [ ] Step 4: 检查桌面/窄屏、明暗主题、导航展开/收起及真实图表。浏览器工具无法可靠识别URL或连接超时时保留实现，不虚构截图验收。
- [ ] Step 5: 使用 requesting-code-review 做一次独立最终复审；修复重要问题时补失败回归再修复，不再分发重复复审。
- [ ] Step 6: 用 verification-before-completion 以实际测试输出确认交付；执行 weekly-work-report，合并同一需求记录。交付说明写明入口、实际生成来源、验证结果和待验限制，不自动提交/推送/部署。

## 计划自审与执行方式

规格中的独立入口、全市场范围、原始档案、补算区分、归并、取消/恢复、用户隔离、原图/后图和回放均有对应任务。关键接口只列已确认复用能力与本任务待实现能力，没有假定不存在的插槽。计算核心和原图复用现有实现，存储与任务职责分开；原有 MiningRunStore 终态不变，重试采用新run关联检查点。

执行方式为当前聊天直接实施，依次完成计算、归档、任务API和页面，最后进行独立复审；用户已确认实施。

## 交付记录

- 已实现五项任务的产品功能。表单保留在复盘页内，避免为单次使用增加组件分层；原图复用既有 ChanChart/EChartsCandlestick。
- 后端相关回归51项通过，Ruff通过；独立复审的三项重要问题均有先失败后通过的回归测试。归档读取改为发布时生成的区间索引，详情限定相关股票与信号的分区。
- 已用合成行情完成真实 ECharts 浏览器检查：440px布局堆叠、1440px布局并排、暗色图表及画线；导航注册/冲突隔离和原缠论页面由自动化回归覆盖，未独立手动复验侧栏展开/折叠。
- 当前没有可用的生产全市场数据集，未声明全市场耗时、峰值内存或磁盘数值；真实多进程硬杀恢复也未完成端到端验收。计算使用固定上游算法，未重新论证其缠论定义。
- 最终前端56份测试文件/378项测试通过，另5项Node测试通过，`pnpm build`通过；构建仅报告既有大包和浏览器数据库更新提示。`git diff --check`通过。
- 本地实现完成时保留未提交内容；用户于2026-11-02另行授权提交、推送并向 `mobilecloud-deploy` 发布。发布结果以独立发布记录为准。已按实际完成日期合并当周周报。
