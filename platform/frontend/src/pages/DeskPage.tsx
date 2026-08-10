import { ProTable, type ProColumns } from '@ant-design/pro-components'
import { Tag } from 'antd'
import type { SorterResult } from 'antd/es/table/interface'
import { useSearchParams } from 'react-router-dom'

import { PageHeading } from '../components/PageHeading'

interface CapabilityRow {
  key: string
  area: string
  capability: string
  state: 'ready' | 'blocked'
  reason: string
}

const capabilityRows: CapabilityRow[] = [
  { key: 'run-context', area: '核心合同', capability: '双轴 RunContext', state: 'ready', reason: '合法组合由领域合同 fail closed' },
  { key: 'pit', area: '核心合同', capability: 'PIT 时间与可信状态', state: 'ready', reason: '当前仅有领域合同，尚无生产数据' },
  { key: 'ledger', area: '治理', capability: '版本、运行与 Artifact 账本', state: 'ready', reason: '内存适配器供本地合同验证' },
  { key: 'universe', area: '数据', capability: '历史股票池', state: 'ready', reason: 'P2 身份、历史成员与只读 API 合同就绪；运行时仍需真实摄取' },
  { key: 'market-data', area: '数据', capability: '市场基础数据', state: 'ready', reason: '原始行情、复权因子、状态与 Parquet 查询就绪；免费源上限为 normalized_current' },
  { key: 'financials', area: '数据', capability: 'PIT 财务事实', state: 'blocked', reason: '等待 P3 正式接入' },
  { key: 'quality', area: '研究', capability: '公司质量', state: 'blocked', reason: '等待行业模板与特征版本' },
  { key: 'valuation', area: '研究', capability: '估值预期差', state: 'blocked', reason: '等待 P5 估值服务' },
  { key: 'revision', area: '研究', capability: '改善与恶化', state: 'blocked', reason: '等待 PIT 财务与特征快照' },
  { key: 'events', area: '事件', capability: '事件影响', state: 'blocked', reason: '等待 P8 事件证据链' },
  { key: 'factors', area: '验证', capability: 'Factor Lab', state: 'blocked', reason: '等待 P4 统计引擎' },
  { key: 'timing', area: '择时', capability: '主动 Timing', state: 'blocked', reason: '等待 P7 Shadow 验证' },
  { key: 'portfolio', area: '组合', capability: '目标组合', state: 'blocked', reason: '等待 P6 组合政策' },
  { key: 'risk', area: '风险', capability: 'Risk R0', state: 'blocked', reason: '等待 P6 风险模型' },
  { key: 'execution', area: '执行', capability: 'Paper OMS', state: 'blocked', reason: '等待 P10 且不连接真实账户' },
  { key: 'approval', area: '治理', capability: '审批与晋级', state: 'blocked', reason: '等待服务端身份与审批工作流' },
]

export function DeskPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedArea = searchParams.get('area')
  const selectedSort = searchParams.get('sort')
  const selectedOrder = searchParams.get('order') === 'descend' ? 'descend' : 'ascend'
  const areaFilters = [...new Set(capabilityRows.map(({ area }) => area))]
    .sort()
    .map((value) => ({ text: value, value }))
  const columns: ProColumns<CapabilityRow>[] = [
    {
      title: '领域',
      dataIndex: 'area',
      width: 90,
      filters: areaFilters,
      filteredValue: selectedArea ? [selectedArea] : null,
      onFilter: (value, row) => row.area === value,
      sorter: (left, right) => left.area.localeCompare(right.area, 'zh-CN'),
      sortOrder: selectedSort === 'area' ? selectedOrder : null,
    },
    {
      title: '能力',
      dataIndex: 'capability',
      width: 180,
      sorter: (left, right) => left.capability.localeCompare(right.capability, 'zh-CN'),
      sortOrder: selectedSort === 'capability' ? selectedOrder : null,
    },
    {
      title: '状态',
      dataIndex: 'state',
      width: 100,
      sorter: (left, right) => left.state.localeCompare(right.state),
      sortOrder: selectedSort === 'state' ? selectedOrder : null,
      render: (_, row) => row.state === 'ready'
        ? <Tag color="success">合同就绪</Tag>
        : <Tag>未启用</Tag>,
    },
    { title: '真实说明 / 启用条件', dataIndex: 'reason', ellipsis: true },
  ]
  return (
    <div className="workspacePage">
      <PageHeading
        title="今日工作台"
        description="先看数据和能力是否可信，再看研究输出。当前页面只显示真实建设状态，不展示模拟行情或组合数字。"
        eyebrow="FUNDAMENTAL QUANT"
        extra={<Tag color="processing">P2 · READ ONLY</Tag>}
      />
      <section aria-label="平台能力状态" className="deskSection">
        <div className="sectionHeading">
          <div>
            <h2>能力与数据就绪度</h2>
            <p>16 项核心能力逐项说明当前状态和启用条件。</p>
          </div>
        </div>
        <ProTable<CapabilityRow>
          columns={columns}
          dataSource={capabilityRows}
          rowKey="key"
          search={false}
          cardBordered={false}
          dateFormatter="string"
          pagination={{ pageSize: 20, hideOnSinglePage: true }}
          options={{ density: true, fullScreen: true, setting: true, reload: false }}
          onChange={(_, filters, sorter) => {
            const updated = new URLSearchParams(searchParams)
            const area = filters.area?.[0]
            if (area) updated.set('area', String(area))
            else updated.delete('area')
            const selected = (Array.isArray(sorter) ? sorter[0] : sorter) as SorterResult<CapabilityRow>
            if (selected?.order && typeof selected.field === 'string') {
              updated.set('sort', selected.field)
              updated.set('order', selected.order)
            } else {
              updated.delete('sort')
              updated.delete('order')
            }
            setSearchParams(updated, { replace: true })
          }}
          toolBarRender={false}
        />
      </section>
    </div>
  )
}
