import { useState } from 'react'
import type { StrategyGroup } from '../api'

type Props = { groups: StrategyGroup[]; onChange: (groups: StrategyGroup[]) => void }

export function StrategyGroups({ groups, onChange }: Props) {
  const [name, setName] = useState('')
  const ordered = [...groups].sort((a, b) => a.order - b.order)
  const create = () => {
    const trimmed = name.trim()
    if (!trimmed || groups.some(group => group.name.toLocaleLowerCase() === trimmed.toLocaleLowerCase())) return
    onChange([...groups, { id: crypto.randomUUID(), name: trimmed, order: groups.length, strategy_ids: [] }])
    setName('')
  }
  const update = (next: StrategyGroup[]) => onChange(next.map((group, order) => ({ ...group, order })))
  return <section className="rounded-xl border border-border bg-card p-4 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="font-semibold">我的分组</h2><p className="mt-1 text-xs text-muted">按表现整理策略；分组不会自动变化。</p></div>
      <div className="flex gap-2"><input aria-label="新分组名称" value={name} onChange={event => setName(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') create() }} placeholder="例如：拉、推、夯" className="min-w-36 rounded-lg border bg-base px-3 py-2 text-sm" />
        <button type="button" disabled={!name.trim()} onClick={create} className="rounded-lg bg-primary px-3 py-2 text-sm text-white disabled:opacity-40">新建分组</button></div>
    </div>
    {ordered.length > 0 && <div className="mt-4 flex flex-wrap gap-2">{ordered.map((group, index) => <div key={group.id} className="flex items-center gap-1 rounded-lg border bg-base px-2 py-1.5">
      <span className="px-2 text-sm font-medium">{group.name}<span className="ml-1 text-xs text-muted">{group.strategy_ids.length}</span></span>
      <button type="button" aria-label={`上移 ${group.name}`} disabled={index === 0} onClick={() => { const next = [...ordered]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; update(next) }} className="rounded px-2 py-1 text-xs hover:bg-muted disabled:opacity-30">↑</button>
      <button type="button" aria-label={`下移 ${group.name}`} disabled={index === ordered.length - 1} onClick={() => { const next = [...ordered]; [next[index], next[index + 1]] = [next[index + 1], next[index]]; update(next) }} className="rounded px-2 py-1 text-xs hover:bg-muted disabled:opacity-30">↓</button>
      <button type="button" aria-label={`重命名 ${group.name}`} onClick={() => { const nextName = window.prompt('分组名称', group.name)?.trim(); if (nextName && !groups.some(item => item.id !== group.id && item.name.toLocaleLowerCase() === nextName.toLocaleLowerCase())) update(groups.map(item => item.id === group.id ? { ...item, name: nextName } : item)) }} className="rounded px-2 py-1 text-xs hover:bg-muted">改名</button>
      <button type="button" aria-label={`删除 ${group.name}`} onClick={() => { if (window.confirm(`删除“${group.name}”？策略将移回未分组。`)) update(groups.filter(item => item.id !== group.id).map(item => ({ ...item, strategy_ids: [] }))) }} className="rounded px-2 py-1 text-xs text-red-500 hover:bg-muted">删除</button>
    </div>)}</div>}
    {ordered.length === 0 && <p className="mt-4 text-sm text-muted">还没有自定义分组。输入你自己的档位名称来整理策略。</p>}
  </section>
}
