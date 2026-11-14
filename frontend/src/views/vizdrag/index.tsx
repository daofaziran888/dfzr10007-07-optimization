import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/vizdrag'
const columns = [
  "方案编号",
  "方案名称",
  "数据源绑定",
  "图表类型",
  "横轴字段",
  "纵轴字段",
  "分组字段",
  "方案状态"
]
const actions = [
  "发布方案",
  "嵌入看板",
  "归档方案"
]
const statuses = [
  "草稿",
  "已发布",
  "已嵌入",
  "已归档"
]
const queueColumns: Array<{ key: string; label: string }> = [
  { key: '方案编号', label: '方案编号' },
  { key: '方案名称', label: '方案名称' },
  { key: 'status', label: '队列状态' },
  { key: 'error', label: 'error' },
  { key: '失败原因', label: '失败原因' },
  { key: '文件版本', label: '文件版本' },
  { key: '导出文件', label: '导出文件' },
  { key: '进入导出', label: '进入导出' },
  { key: '尝试次数', label: '尝试次数' },
]

type Row = Record<string, string | number | null>
type QueueRow = Record<string, string | number | boolean | null>
type Receipt = {
  方案编号: string
  ok: boolean
  status: string
  error: string | null
  失败原因: string | null
  文件版本: string | null
  导出文件: string | null
  进入导出: boolean
  复用首次结果: boolean
  message: string
}
type BatchResult = {
  ok: boolean
  message: string
  receipts: Receipt[]
}

export default function VizdragView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [queueRows, setQueueRows] = useState<QueueRow[]>([])
  const [queueTotal, setQueueTotal] = useState(0)
  const [receipts, setReceipts] = useState<Receipt[]>([])
  const [queueMessage, setQueueMessage] = useState('')
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const stats = useMemo(() => [
    { label: '可视化方案总数', value: total },
    { label: '已发布方案', value: rows.filter((row) => row.status === '已发布').length },
    { label: '已嵌入方案', value: rows.filter((row) => row.status === '已嵌入').length },
  ], [rows, total])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('可视化方案列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '拖拽可视化列表读取失败')
    }
  }, [filters])

  const reloadQueue = useCallback(async () => {
    try {
      const response = await request(`${ENDPOINT}/publish-queue`)
      if (!response.ok) {
        throw new Error('发布队列读取失败')
      }
      const payload = await response.json()
      setQueueRows(payload.items ?? [])
      setQueueTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '发布队列读取失败')
    }
  }, [])

  useEffect(() => {
    void reload()
    void reloadQueue()
  }, [reload, reloadQueue])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action } }),
      })
      if (!response.ok) {
        throw new Error('拖拽可视化动作未生效，请稍后重试')
      }
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '拖拽可视化操作失败')
    }
  }

  async function runBatch(url: string, body?: Record<string, unknown>) {
    setErrorMessage('')
    setQueueMessage('')
    try {
      const response = await request(url, {
        method: 'POST',
        body: JSON.stringify({ values: body ?? {} }),
      })
      if (!response.ok) {
        throw new Error('连续发布请求未生效，请稍后重试')
      }
      const payload: BatchResult = await response.json()
      setReceipts(payload.receipts ?? [])
      setQueueMessage(payload.message ?? '')
      await Promise.all([reload(), reloadQueue()])
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '连续发布失败')
    }
  }

  function renderQueueCell(row: QueueRow, key: string) {
    const value = row[key]
    if (typeof value === 'boolean') {
      return value ? '是' : '否'
    }
    if (value === null || value === undefined || value === '') {
      return '—'
    }
    return String(value)
  }

  return (
    <section className="page" data-module="vizdrag">
      <header className="page-head">
        <div>
          <h2>拖拽可视化管理</h2>
          <p className="page-desc">维护拖拽可视化的图表类型、数据绑定与分组配置，为拖拽可视化分析提供可验证的数据工程流程。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('可视化方案登记入口尚未接入审批流')}>
            登记可视化方案
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出拖拽可视化清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        {stats.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterFields.map((field) => (
          <label key={field} className="filter-item">
            <span>{field}</span>
            <input
              value={filters[field] ?? ''}
              placeholder={`按${field}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
            />
          </label>
        ))}
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>暂无拖拽可视化数据，可先登记可视化方案</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条拖拽可视化记录</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>

      <section className="queue-section">
        <header className="page-head">
          <div>
            <h2>发布队列</h2>
            <p className="page-desc">连续发布可恢复：每项记录失败原因，断线后只重试未完成项，异常项留在队列而不进入导出文件。</p>
          </div>
          <div className="page-actions">
            <button className="btn primary" type="button" onClick={() => void runBatch(`${ENDPOINT}/publish`)}>
              连续发布
            </button>
            <button className="btn" type="button" onClick={() => void runBatch(`${ENDPOINT}/publish-queue/retry`)}>
              重试未完成项
            </button>
            <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/publish-queue/export`, '_blank')}>
              导出发布文件
            </button>
          </div>
        </header>

        {receipts.length > 0 && (
          <div className="receipt-panel">
            <h3>发布回执{queueMessage ? `：${queueMessage}` : ''}</h3>
            <ul>
              {receipts.map((receipt) => (
                <li key={receipt.方案编号} className={receipt.ok ? 'receipt-ok' : 'receipt-fail'}>
                  <strong>{receipt.方案编号}</strong>
                  <span>{receipt.status}</span>
                  {receipt.error && <code>error={receipt.error}</code>}
                  {receipt.失败原因 && <span>{receipt.失败原因}</span>}
                  {receipt.文件版本 && <span>文件版本 {receipt.文件版本}</span>}
                  {receipt.复用首次结果 && <span>沿用首次发布结果</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
        {receipts.length === 0 && queueMessage && <p className="page-desc">{queueMessage}</p>}

        <table className="data-table">
          <thead>
            <tr>
              {queueColumns.map((column) => <th key={column.key}>{column.label}</th>)}
              <th>可执行动作</th>
            </tr>
          </thead>
          <tbody>
            {queueRows.map((row) => (
              <tr key={String(row.id)}>
                {queueColumns.map((column) => <td key={column.key}>{renderQueueCell(row, column.key)}</td>)}
                <td className="row-actions">
                  {row.status !== '已完成' && (
                    <button
                      className="link"
                      type="button"
                      onClick={() => void runBatch(`${ENDPOINT}/publish`, { 方案编号: [row.方案编号] })}
                    >
                      重试
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {queueRows.length === 0 && (
              <tr>
                <td className="empty-state" colSpan={queueColumns.length + 1}>暂无数据</td>
              </tr>
            )}
          </tbody>
        </table>

        <footer className="page-foot">
          <span>共 {queueTotal} 条发布队列记录</span>
        </footer>
      </section>
    </section>
  )
}
