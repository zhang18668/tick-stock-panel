# 缠论分析工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从左侧快捷栏进入，输入股票代码，在既有 K 线图上自动显示可解释的缠论结构。

**Architecture:** 扩展模块注册路由与快捷入口，复用共享股票搜索和行情查询。纯 TypeScript 计算模块输出结构数据，通过既有 EChartsCandlestick 的可选通用叠加契约绘图。首版不新增后端接口或持久化缓存。

**Tech Stack:** React 18、TypeScript、TanStack Query、ECharts、Tailwind、Vitest；不新增产品依赖。

**Spec:** `docs/superpowers/specs/2026-10-30-chan-analysis-design.md`（用户已确认）。

## 用户授权变更与执行状态

实施过程中用户明确改用 chan.py，取代下文 Task 1/2 的手写算法路线以及「不新增后端接口」限制；保留原计划作为范围和验证依据。最终引擎为固定版本的上游公开计算核心，原 TypeScript 算法与对应算法测试已移除，没有并行保留第二套缠论规则。

- [x] 计算层：固定引入 44 个上游计算文件，隔离命名空间，保留 MIT 和 SHA256 来源清单；新增标准 OHLC 的无状态计算适配器、输入校验、日/周线聚合和逐根确认日期记录。
- [x] 图表层：复用 EChartsCandlestick，增加可选结构线、价格矩形、结构定位，兼容旧标记及时间区间；修复缩放中间区域时稀疏结构线被过滤的问题。
- [x] 页面层：左侧快捷入口、股票搜索、日/周切换、五类结构图层、VOL/MACD、历史截止、结构详情、加载/空/错误/重试、切股隔离；保持现有主题与K线风格。
- [x] 复审修正：周确认日期与截断可见时刻对齐；刷新相同 OHLC 也重算收盘定版范围；桌面包携带上游许可与来源文件。
- [x] 最终验证：Vitest 55 个文件 372 项通过，2 个原有 node:test 文件单独运行 5 项通过，后端相关 25 项通过，构建、Ruff 和 diff 检查通过。浏览器连接超时，真实行情页面与安装包人工验收保留待办。按 weekly-work-report 执行本周记录，写入结果以本次回复为准。

## Global Constraints

- 复用项目现有 K 线图组件，避免独立构建另一套图表、行情请求或缓存。
- 切股后立即清除上一标的结构与选中记录，不能把占位数据当成当前标的。
- 未实现或不满足条件的信号明确显示「未实现」或「暂无信号」，不以局部极值代替，也不输出交易指令。
- 不新增缠论 HTTP API。
- 风格要与其他 K 线图一致。
- 使用真实 OHLC，不制造示例行情作为正式结果；不提交或推送，除非用户另行要求。
- 未经用户选择不得启用子代理；推荐当前会话内直接执行。

## Review Focus

1. 查询切股竞态：上一只股票响应不能生成新股票的线与信号；Task 4 测试。
2. 历史极值与确认时刻不同：截断历史不能提前确认；Task 1、2 测试。
3. 周末、跨年与未结束周：周聚合按交易周，指标重新计算，当前周保守视作未完成；Task 1 测试。
4. 缺失、非法或重复时间 OHLC：显式错误或空结果，不能输出伪结构；Task 1 测试。
5. 关闭图层与切换股票：旧 series、markArea 和选择状态必须消失；Task 3、4 测试。

---

### Task 1: 基础计算、周期与分型笔

**Files:** Create `frontend/src/custom/chan/types.ts`, `bars.ts`, `analysis.ts`, `analysis.test.ts`, `bars.test.ts`.

**Interfaces:**

```ts
import type { OHLC } from '@/components/EChartsCandlestick'
export interface ChanPoint { date: string; price: number; index: number }
export interface ChanStructure {
  id: string
  kind: 'fractal' | 'stroke' | 'segment' | 'center' | 'signal'
  start: ChanPoint
  end: ChanPoint
  confirmedAt: string | null
  basis: string
  label: string
  low?: number
  high?: number
}
export interface ChanAnalysis {
  structures: ChanStructure[]
  warnings: string[]
  ruleVersion: string
}
export function aggregateWeekly(rows: OHLC[]): OHLC[]
export function withMacd(rows: OHLC[]): OHLC[]
export function analyzeChan(rows: OHLC[]): ChanAnalysis
```

- [ ] Step 1: Write the following failing tests and numeric inclusion/fractal fixtures. Test dates are UTC date-only labels, not runtime trading-time assumptions.

```ts
const row = (date: string, low: number, high: number): OHLC => ({ date, low, high, open: low, close: high, volume: 10 })
expect(analyzeChan([]).structures).toEqual([])
expect(aggregateWeekly([
  row('2026-10-26', 10, 12), row('2026-10-27', 11, 15),
  row('2026-11-02', 13, 16),
])).toMatchObject([
  { date: '2026-10-27', open: 10, high: 15, low: 10, close: 15, volume: 20 },
  { date: '2026-11-02', volume: 10 },
])
expect(() => analyzeChan([row('2026-10-26', 12, 10)])).toThrow()
expect(() => analyzeChan([row('2026-10-26', 10, 12), row('2026-10-26', 11, 13)])).toThrow()
```

- [ ] Step 2: Run `pnpm exec vitest run src/custom/chan/analysis.test.ts src/custom/chan/bars.test.ts` from frontend; confirm missing-module failure.
- [ ] Step 3: Implement validation: finite positive OHLC, low <= open/close <= high, strictly increasing unique dates. Return empty analysis on empty input; reject malformed input with a user-readable error.
- [ ] Step 4: Implement directional containment merging. Keep original high/low occurrence indexes separately from merged-bar end index. Upward inclusion uses max high/max low, downward uses min high/min low; initial ambiguous direction remains unresolved until a non-containing directional pair exists. Plateau extrema do not produce strict fractals. Use three merged bars for strict high/high and low/low comparisons.
- [ ] Step 5: Implement stroke endpoint selection: alternating strict fractals, at least four merged-bar index intervals apart, endpoint price order consistent with direction. Same-kind more extreme endpoints replace the active endpoint. Final stroke remains provisional until the opposite valid stroke endpoint exists; confirmation date includes that opposite endpoint's right-hand evidence. Keep separate dates for extrema and confirmation.
- [ ] Step 6: Add positive, negative and prefix tests for every above rule. In tests, compare point prices and occurrence dates, not just counts. Assert every non-null confirmedAt is <= input's last date, and no unfinished last stroke is labeled confirmed.
- [ ] Step 7: Implement weekly aggregation using Monday week keys derived from date-only calendar arithmetic, retaining last trading date as chart label; compute EMA12/26 and DEA9 from weekly closes. Preserve volume units. Test cross-year week, a single-bar week, and constant-close MACD = 0. Avoid using daily indicator columns on weekly bars.
- [ ] Step 8: Rerun both suites; record pass/fail. Do not commit.

### Task 2: 线段、中枢与信号的可解释计算

**Files:** Create `frontend/src/custom/chan/segments.ts`, `centers.ts`, `signals.ts` and adjacent `.test.ts`; update `analysis.ts`.

**Interfaces:**

```ts
export function buildSegments(strokes: ChanStructure[]): ChanStructure[]
export function buildCenters(segments: ChanStructure[]): ChanStructure[]
export function buildSignals(rows: OHLC[], segments: ChanStructure[], centers: ChanStructure[]): ChanStructure[]
```

- [ ] Step 1: Before implementation, add fixtures asserting a feature-sequence top/bottom reversal, directional containment within feature sequences, feature-sequence gap requiring subsequent reversal evidence, and final unconfirmed segment. Fixtures must specify expected endpoint dates/prices and confirmedAt. Run these tests to confirm missing exports.
- [ ] Step 2: Implement segments using opposite-direction strokes as feature elements and directional inclusion normalization. A gap-free three-element strict feature fractal supplies reversal evidence. A gapped first feature reversal cannot confirm the segment until an opposite feature-sequence fractal supplies the second evidence; otherwise retain the candidate. At least three strokes form a candidate segment; counting three strokes alone never confirms it. ConfirmedAt is the latest confirmation date of all required evidence. Document rule version and excluded ambiguous cases in source.
- [ ] Step 3: Implement segment-level centers only from confirmed segments: three consecutive segment price ranges must have strict positive intersection (`max(lows) < min(highs)`). Freeze the original ZD/ZG bounds while subsequent confirmed segments overlap; terminate when a segment range lies wholly outside. New center formation consumes a new eligible three-segment sequence; do not emit a duplicate center for each sliding window. Test disjoint, boundary-touching, extending and separated centers with explicit numeric ZD/ZG assertions.
- [ ] Step 4: Use a conservative staged signal contract. Calculate MACD histogram absolute area per comparable same-direction segment; insufficient inputs produce no divergence verdict. B1/S1 additionally require two successively lower/higher disjoint centers and a new low/high with reduced area. B2/S2 require an already confirmed B1/S1 and a confirmed subsequent opposite-direction retracement which does not break that extreme. B3/S3 require a confirmed departure segment and a confirmed first pullback which stays strictly outside the center's upper/lower bound. Confirmation date includes all signal evidence. Do not label unimplemented strict conditions as supported: leave that signal class absent and list it explicitly as unimplemented in warnings if the evidence model cannot support it.
- [ ] Step 5: For every emitted signal class, write separate valid and invalid fixtures: missing predecessor, price touching forbidden boundary, missing MACD and unconfirmed segment. Add prefix invariance tests: structures confirmed by date T match the same structures from a run ending at T; if mutable endpoint selection violates invariance, fix confirmation bookkeeping before exposing that class as confirmed.
- [ ] Step 6: Run all custom/chan algorithm tests. List actual supported signal classes and ambiguous segment cases in a short rule-version help text; no untested accuracy claims or synthetic buy/sell markers.

### Task 3: 为现有 K 线增加通用叠加能力

**Files:** Modify `frontend/src/components/EChartsCandlestick.tsx`, `EChartsCandlestick.test.tsx`.

**Interfaces:** Add optional props, without changing existing defaults:

```ts
export interface ChartStructureLine {
  id: string
  points: { date: string; price: number }[]
  color?: string
  width?: number
  dashed?: boolean
  label?: string
}
// ChartRange adds optional low?: number; high?: number.
// Props adds structureLines?: ChartStructureLine[].
```

- [ ] Step 1: Extend the existing mocked ECharts test to render a price-bounded range and a structure line. Assert `markArea.data[0][0].yAxis === 10`, second yAxis === 12, and the line's date-price coordinates. Verify old time-only ranges omit yAxis. Run the test and confirm failure.
- [ ] Step 2: Add range price coordinates only when both finite bounds exist and low < high; preserve all legacy range behavior. Add each structure line as a uniquely identified unsmoothed line on the existing main x/y axes, with no symbols, inherited theme-compatible text and normal tooltip behavior. Do not draw over a second canvas or recreate zoom/pointer handlers.
- [ ] Step 3: Pass the optional prop through buildOption and effect dependencies. Use the existing full option replacement to remove hidden series. Exclude invalid dates/prices and never interpolate a line through an unrepresented date. Keep candles and labels readable, preserving native chart colors, fonts, grids and MA styling.
- [ ] Step 4: Test replacing the prop with [] removes lines, changing symbol removes old overlays, dashed state uses the intended style, and existing compact-marker tests still pass.
- [ ] Step 5: Run `pnpm exec vitest run src/components/EChartsCandlestick.test.tsx`; record actual result.

### Task 4: 接入左侧快捷入口与完整页面

**Files:** Create `frontend/src/custom/chan/extension.tsx`, `ChanAnalysisPage.tsx`, `ChanAnalysisPage.test.tsx`; optionally split a focused `ChanDetails.tsx` when needed for readability.

**Interfaces:** Register static `/chan-analysis`; export default FrontendExtension with id `chan.analysis`, apiVersion 1, route id `chan-analysis` and a `layout.header.quick` component. Use React Router navigation and `useLocation` for active state. Use `StockFinancialSearch` onSelect(symbol, name), `klineDailyQueryOptions`, `toOHLC`, and Task 1-3 contracts.

- [ ] Step 1: Create jsdom tests with mocked search, queries and chart. Cover initial guidance, selection submission, loading, empty data, error and retry, switching symbols during delayed responses, and switching day/week. Confirm missing page failure.
- [ ] Step 2: Add the shortcut using the same classes as AssistantHeaderEntry (h-7, existing tokens and Lucide icon). Do not also add a duplicate navigation entry. Lazy-load the page through the extension route component so chart code does not enter the initial bundle unnecessarily. Test route registration through the existing extension registry suite patterns.
- [ ] Step 3: Compute the three-year query range once per page using Beijing today; only enable query after symbol selection. Reject response.symbol mismatches, and key symbol-dependent content/selection to prevent stale overlays. Disable structural analysis while the query is using placeholderData. Surface data errors rather than hiding them behind old structures.
- [ ] Step 4: Render header and a wrapping toolbar using existing bg-base/bg-surface/bg-elevated, border-border, text-foreground/text-secondary/text-muted, rounded-card and chart pill conventions. EChartsCandlestick owns candle styling, its info bar, crosshair, zoom, VOL and MACD. Provide main chart with five optional structure layer toggles, VOL/MACD toggles and a day/week picker; no unsupported minute option.
- [ ] Step 5: Show latest close/change calculated from two actual adjacent closes with clear data timestamp. Render structure details, latest center bounds, explicit divergence condition status and signal records in a desktop right column that stacks under the chart on narrow screens. Clearly identify rule version and signal classes unavailable in this first version.
- [ ] Step 6: Add history cutoff selection based on actual row dates. Analyze only the prefix ending at cutoff and hide subsequent candles/structures. Weekly analysis excludes the cutoff week from confirmed input unless it is known complete; conservatively keep newest weekly evidence provisional. Selecting a record sets the selected details and a chart visible date range via a minimal optional controlled focus contract if existing chart props cannot do so; add its graph test if introduced. Do not promise positioning while only changing sidebar text.
- [ ] Step 7: Test layer removal, record selection and chart focus, cutoff recomputation, symbol selection reset and retry. Verify all five visible layers are backed by actual outputs and unsupported algorithms are explicitly labeled.
- [ ] Step 8: Run `pnpm exec vitest run src/custom/chan src/components/EChartsCandlestick.test.tsx src/extensions/registry.test.ts src/extensions/runtime.test.ts`; first check actual available registry test filename and omit only nonexistent paths, not failing suites.

### Task 5: 集成验证、兼容性与交付记录

**Files:** Update this plan's checkboxes and a concise implementation/result section in the spec. Use weekly-work-report's external destination only after code and verification are finished.

- [ ] Step 1: Run `pnpm build` from frontend and fix errors caused by the change. Run `git diff --check` from repository root. Review `git diff --stat`, `git diff` and untracked product files, preserving user changes.
- [ ] Step 2: Run the dev preview if practical and inspect desktop/narrow, light/dark, empty/search/error/switching states and actual K-line overlays. Use real local available symbols, not fabricated financial values. Record any unavailable backend or browser prerequisite and avoid claiming manual verification when absent.
- [ ] Step 3: Read requesting-code-review and verification-before-completion skills, perform the permitted review workflow, and rerun only tests affected by resulting changes. Do not spawn subagents unless a selected execution method or applicable skill explicitly requires them.
- [ ] Step 4: Update supported rules, test/build results and remaining strict-algorithm limitations. Execute the `weekly-work-report` skill; merge this chat's evidenced results under its exclusive-lock rules. No scanning other chats; report failures honestly.
- [ ] Step 5: Deliver entry path, completed functionality, L2/L3 impact, verification results and remaining risks. No automatic commit, push, deployment or claim that unfinished signals are supported.

## Plan self-review

Page, calculations, graph reuse, cutoff behavior, signal honesty, week aggregation, states and verification each have an owning task. Inputs and outputs use the same shared ChanStructure contract. Existing graph APIs require optional additions only. Source rules are deliberately testable, and unimplemented signal classes remain visible as unavailable rather than fabricated. User's latest style constraint is included in both spec and tasks. Written plan awaits review before product implementation; recommended execution method is direct work in this chat, given the shared types and sequential graph/page dependencies.
