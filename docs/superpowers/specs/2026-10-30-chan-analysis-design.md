# 缠论分析工作台首版设计

日期：2026-10-30。基线：`c48247e90f715a5349d66c199bc05d768f0ccbfd`。

## 已确认的引擎调整（取代下文早期自算方案）

用户在实施过程中明确要求「引用 chan.py 来实现」。最终使用 Vespa314/chan.py 公开计算核心，固定版本 `f8ca3b5e44d7166e2abd756a8e7fa816c79faebe`，保留 MIT 许可、来源与原始文件哈希。仅将导入路径隔离到 `app.vendor.chanpy`，计算代码不变；原有自写 TypeScript 算法已删除。

前端继续复用共享日线查询，将标准 OHLC 输入有 2000 根上限的无状态 `POST /api/custom/chan/analyze`。后端调用 CKLine_List / CKLine_Unit 计算并返回图表坐标与指标，不调用上游数据源，不绕过项目行情读取链路。此调整取代下文「纯前端计算、不新增 API」及 `analysis.ts` 文件规划。

日/周线均由同一引擎计算。笔、中枢、线段沿用上游 is_sure；买卖点保留 1、1p、2、2s、3a、3b 原始类型。公开 CBS_Point 没有独立 is_sure，全部显示为可变化的形态信号，不用其所在笔的确认状态推定信号确认。配置显示 strict / chan / normal、MACD peak、背驰阈值 0.9。

历史截止先截断输入再计算。逐根喂入引擎，记录精确几何版本首次进入已确认状态的日期；最后一周保守排除于确认依据之外，周线结构的确认日期按下一周首根实际输入交易日记录，避免确认日期早于截断回看可观察时间。北京时间当日 15:30 以前的日K同样仅展示、不作为确认依据。

新增后端扩展路由和前端快捷入口属于 L2；现有图表新增可选结构线、价格范围和定位参数属于 L3。旧调用不传新参数时行为不变。派生查询键包含股票、周期与完整 OHLC，刷新行情成功后同时失效本股票派生结果，以覆盖 OHLC 数值未变但收盘定版条件变化的情况。没有持久化、数据库、SSE 或数据源配置变更。

图表风格继续由 EChartsCandlestick 统一管理。笔为细紫线、线段为粗蓝线、中枢为半透明矩形，结构记录可定位，图层和子图可独立开关。结构线按交易K线位置采样同一条直线，保证缩放到两端之外的中间视窗仍能显示。桌面打包显式携带上游 LICENSE、UPSTREAM.json 和 README。

## 用户目标

左侧快捷栏增加「缠论分析」入口。用户输入股票代码后，使用真实行情自动生成 K 线上的缠论结构，获得参考图中的笔、线段、中枢、买卖点和结构状态。复用项目现有 K 线图组件，避免独立构建另一套图表、行情请求或缓存。

## 页面与交互

用户于 2026-10-30 确认本设计，并补充：风格要与其他 K 线图一致。必须直接复用 EChartsCandlestick 的主题、字体、红涨绿跌、信息栏、子图、缩放和十字光标，页面控件使用项目既有设计令牌；不能另做独立图表皮肤。

- 顶部：股票代码搜索、名称、最近收盘价、相邻收盘涨跌幅、数据截止时间、周期切换。
- 主图区：分型、细线笔、粗线线段、带价格边界的半透明中枢、买卖点；五个独立图层开关，成交量与 MACD 子图开关。
- 右侧：当前结构状态、最近中枢上下沿、背驰分析状态、最近信号。点击结构或信号记录显示起止时间、价格、确认时间与判定依据，并定位到相关 K 线。
- 已确认结构实线显示；末端候选结构虚线显示并带「未确认」标签。候选和已确认信号分别展示。
- 窄屏侧栏转为主图下方信息区；沿用系统明暗主题。
- 首次进入显示代码输入引导；查询有加载、空数据、失败及重试状态。切股后立即清除上一标的结构与选中记录，不能把占位数据当成当前标的。

## 周期与数据

首版接入日线及由相同日线聚合的周线。60 分钟等周期只在确认现有分钟接口覆盖的历史长度及能力契约后接入，不能用单日分时伪装历史分钟分析。

日线沿用 `klineDailyQueryOptions`、`QK.kline`、`api.klineDaily` 和 `toOHLC`；默认查询最近三年，以实际返回交易日为准。周线按北京时间交易周聚合开高低收与成交量，未完成的周保留候选状态；MACD 按周线重新计算，不能复用日线指标值。价格统一使用接口现有复权口径。

行情请求不绕过服务层或数据源能力。首版分析为当前页面内纯计算，不增加持久化、SSE、后端缓存或自动交易。刷新复用原查询配置，不建立第二套缓存。

## 计算与确认契约

计算器与 React 和图表解耦，输入按时间排序的 OHLC，输出分型、笔、线段、中枢、候选结构及信号记录。所有结构包含稳定 ID、级别、起止时间与价格、`confirmedAt` 和判定依据；缺少依据的结果不得显示为已确认。

实现前必须对包含关系处理、分型间距、笔延伸、线段特征序列及破坏条件、中枢延伸和新生、背驰力度比较、三类买卖点逐项写出规则并用固定样本断言。不同缠论流派存在规则差异，首版页面应显示采用的规则版本，不能把普通折线或每三笔连接包装成严格线段。

分型至少等待右侧 K 线；笔、线段和信号的确认时间必须晚于或等于满足确认条件的最后输入时间。图上的极值发生日与实际确认日分别保留。历史回看按截断输入重新计算，不将后续确认结果泄漏到更早时点。

中枢必须为价格区间与时间区间组成的矩形。背驰缺少可比较的同级结构或力度数据时显示「条件不足」。B1/B2/B3、S1/S2/S3 分别需要对应完整条件；首版未实现或不满足条件的信号明确显示「未实现」或「暂无信号」，不以局部极值代替，也不输出交易指令。实现结果中的具体规则及尚未覆盖项必须写入交付说明。

## 真实接入点与方案分级

- `frontend/src/extensions/bootstrap.ts` 已通过 glob 加载 `custom/*/extension.tsx`。
- `frontend/src/extensions/types.ts` 已提供 routes/navigation，以及 `layout.header.quick` 左侧快捷行插槽。工作台通过独立扩展注册路由和快捷入口，属 L2，不复制 Layout 或路由系统。
- `frontend/src/components/EChartsCandlestick.tsx` 已支持 markers、ranges、priceLines、子图、缩放、十字光标与日期点击。
- 现有 ranges 只有时间范围，不能表达中枢价格上下沿；现有 priceLines 只有水平线，不能绘制斜线笔或线段。需要最小 L3 增量：可选结构折线和带上下界的矩形契约，旧调用无参数时保持原行为。
- 不新增缠论 HTTP API；若未来回测或监控需要同一算法，再将计算迁到统一领域服务，避免两套判定语义。

## 文件职责

- `frontend/src/custom/chan/extension.tsx`：路由和左侧快捷入口注册。
- `frontend/src/custom/chan/ChanAnalysisPage.tsx`：代码选择、共享查询、图层控制、布局及状态展示。
- `frontend/src/custom/chan/analysis.ts`：可测试的结构算法与聚合计算；过大时按实际职责拆分。
- `frontend/src/components/EChartsCandlestick.tsx`：通用结构线和价格矩形渲染，不包含缠论判定算法。
- 相邻 `.test.ts/.test.tsx`：算法、页面和图表兼容性测试。

## 验证与完成标准

1. 固定样本断言包含处理、分型确认、笔延伸、线段破坏、中枢边界与延伸；覆盖单调行情、相等高低点、空数据、无效 OHLC、历史截断与未完成末端。
2. 每种声称支持的买卖点有正例与反例，缺少 MACD 或同级结构时不输出背驰结论。
3. 页面测试覆盖代码提交、加载失败与重试、空行情、切股隔离、周期切换、图层开关和记录定位。
4. 图表测试验证旧 ranges 兼容、价格矩形上下沿、结构线实虚样式、关层不残留、切股与缩放后无旧标记。
5. 运行受影响 Vitest 测试、`pnpm build`、`git diff --check`，检查最终 diff。
6. 人工检查桌面与窄屏、明暗主题；记录无法执行的检查，不虚构通过结果。
7. 完成代码与验证后执行 weekly-work-report 技能，按独占锁合并当周记录；未完成代码不记为完成。

## 审阅状态

用户已审阅并确认本文件，要求继续实施并保持与其他 K 线图风格一致，随后明确指定使用 chan.py。实现已落在当前工作区，未提交或推送。实际生效方案以文首「已确认的引擎调整」为准。

## 交付与验证记录

- 入口：左侧头部快捷行「缠论」，独立路径 `/chan-analysis`；股票搜索沿用现有组件，行情查询与其他K线共享。
- 新增首要文件：`backend/app/services/chan_analysis.py` 为上游适配器，`backend/app/custom/chan_analysis.py` 注册计算路由，`frontend/src/custom/chan/` 负责入口、页面、绘图映射与详情。
- 后端验证：`backend/.venv/Scripts/python.exe -m pytest tests/test_chan_analysis.py tests/test_extensions.py tests/test_packaging_spec.py tests/test_kline_daily_latest.py -q`，25 项通过，只有已有 pypinyin 的 2 条弃用提示。环境没有 uv，使用现有虚拟环境执行；Ruff 检查本次一方 Python 文件通过。
- 前端定向：`pnpm exec vitest run src/custom/chan src/components/EChartsCandlestick.test.tsx src/extensions/runtime.test.ts`，18 项通过。
- 前端全量混跑：372 项 Vitest 断言通过，2 个原有 node:test 文件在 Vitest 中报「No test suite found」。将 `DimensionMembersDialog.test.ts`、`neighborPrefetch.test.ts` 用 `node --experimental-strip-types --test` 单独执行，5 项通过；未修改这些原有文件。
- 按测试框架分开复验：`pnpm exec vitest run --maxWorkers=2 --exclude src/components/DimensionMembersDialog.test.ts --exclude src/lib/neighborPrefetch.test.ts`，55 个文件、372 项通过，退出码 0。上面的两份 Node 测试另行 5 项通过。
- `pnpm build` 已通过；打包保留已有 ECharts 大 chunk 提示。`git diff --check` 通过。
- 独立复审的四项问题已修正：缩放结构线、周线确认日期、相同OHLC刷新、安装包第三方声明。
- 限制：浏览器预览连接超时，未完成真实行情页面、明暗主题、窄屏截图人工验收；未构建安装包、未部署。买卖点始终作为可变形态信号展示，最后一周保守不参与确认。

### 发布前复验补充（2026-10-30）

用户明确要求通过 SSH 别名 `mobilecloud-deploy` 发布。重新执行构建、后端相关 25 项、Ruff 和 5 项 Node 测试均通过；全量 Vitest 本轮 371 项通过，原有 `Signals.numeric-right.test.tsx` 的「信号库页: 数字右值条件不再触发错误边界, 正常渲染」在固定等待 120ms 后未显示 0.6，未改动该文件或信号库功能。用户已明确接受此项已知测试例外并要求继续发布。线上发布与回滚结果以本次交付回复、服务器独立发布记录为准。
