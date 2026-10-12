import type { RobustPreview } from './api'

type Props = {
  layout: 'holdout' | 'diagnostic'
  holdoutUsage: 'used' | 'declared_unused' | 'unknown'
  neighborBudget: number
  preview: RobustPreview | null
  previewError: string
  onLayoutChange: (value: 'holdout' | 'diagnostic') => void
  onHoldoutUsageChange: (value: 'used' | 'declared_unused' | 'unknown') => void
  onNeighborBudgetChange: (value: number) => void
  onPreview: () => void
}

export function RobustnessConfig(props: Props) {
  return <fieldset className="grid gap-3 rounded border p-4">
    <legend className="px-1 text-sm font-medium">跨时期稳健配置</legend>
    <label className="text-sm">时间布局
      <select aria-label="稳健时间布局" value={props.layout} onChange={event => props.onLayoutChange(event.target.value as Props['layout'])} className="mt-1 block w-full rounded border bg-base p-2">
        <option value="holdout">三段开发 + 两年留出</option>
        <option value="diagnostic">三段历史诊断（全部用于开发）</option>
      </select>
    </label>
    {props.layout === 'holdout' && <label className="text-sm">留出使用声明
      <select aria-label="留出使用声明" value={props.holdoutUsage} onChange={event => props.onHoldoutUsageChange(event.target.value as Props['holdoutUsage'])} className="mt-1 block w-full rounded border bg-base p-2">
        <option value="unknown">不确定</option><option value="used">已用于选参或改策略</option><option value="declared_unused">声明未使用</option>
      </select>
    </label>}
    <label className="text-sm">邻域评估预算<input aria-label="邻域评估预算" type="number" min={0} max={200} value={props.neighborBudget} onChange={event => props.onNeighborBudgetChange(Math.max(0, Math.min(200, Number(event.target.value))))} className="mt-1 block w-full rounded border bg-base p-2" /></label>
    <button type="button" className="w-fit rounded border px-3 py-2" onClick={props.onPreview}>预览交易日切分与预算</button>
    {props.previewError && <p role="alert" className="text-sm text-red-500">{props.previewError}</p>}
    {props.preview && <div className="grid gap-2 text-sm">
      <p>交易日来源：{props.preview.calendar_source}；覆盖 {props.preview.calendar_coverage.covered_start} 至 {props.preview.calendar_coverage.covered_end}（{props.preview.calendar_coverage.trading_dates} 个交易日）</p>
      <ol className="grid gap-1">{props.preview.time_plan.development.map((window, index) => <li key={window.id}>开发段 {index + 1}：{window.start} 至 {window.end}</li>)}</ol>
      {props.preview.time_plan.holdout && <p>留出段：{props.preview.time_plan.holdout.start} 至 {props.preview.time_plan.holdout.end}</p>}
      <p>预计回测调用上限：{props.preview.budgets.estimated_backtests}</p>
      {!props.preview.run_available && <p role="status" className="text-amber-600">稳健任务暂不可启动：{props.preview.run_blocker}</p>}
    </div>}
  </fieldset>
}
