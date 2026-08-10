import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Descriptions, Drawer, Input, Select, Table, Tabs, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useMemo, useState } from 'react'

import {
  getDisclosures,
  getFactComparison,
  getFactRevisions,
  getFinancialMismatches,
  getRawEvidence,
  type DisclosureTimelineEntry,
  type FactRevisionEntry,
  type FactSelectionEntry,
  type FinancialMismatchEntry,
} from '../api/client'
import { WorkspaceState } from '../components/WorkspaceState'

type EvidenceTab = 'disclosures' | 'revisions' | 'comparison' | 'mismatches'

interface FactForm {
  companyId: string
  securityId: string
  metricCode: string
  reportPeriodEnd: string
  periodType: string
  statementType: string
  authorityRuleVersion: string
}

const emptyFactForm: FactForm = {
  companyId: '',
  securityId: '',
  metricCode: '',
  reportPeriodEnd: '',
  periodType: 'annual',
  statementType: 'income_statement',
  authorityRuleVersion: '',
}

function factParams(form: FactForm, includeComparison: boolean) {
  const params = new URLSearchParams()
  if (form.companyId) params.set('company_id', form.companyId)
  if (form.securityId) params.set('security_id', form.securityId)
  if (form.metricCode) params.set('metric_code', form.metricCode)
  if (form.reportPeriodEnd) params.set('report_period_end', form.reportPeriodEnd)
  params.set('period_type', form.periodType)
  params.set('statement_type', form.statementType)
  if (includeComparison) {
    const now = new Date().toISOString()
    params.set('decision_time', now)
    params.set('system_time', now)
    params.set('authority_rule_version', form.authorityRuleVersion)
  }
  return params
}

function EvidenceDrawer({ rawObjectId, onClose }: { rawObjectId: string | null; onClose: () => void }) {
  const evidence = useQuery({
    queryKey: ['raw-evidence', rawObjectId],
    queryFn: ({ signal }) => getRawEvidence(rawObjectId!, signal),
    enabled: Boolean(rawObjectId),
  })
  return (
    <Drawer onClose={onClose} open={Boolean(rawObjectId)} title="原始证据">
      {evidence.isLoading ? (
        <WorkspaceState reason="正在读取证据元数据" state="loading" />
      ) : evidence.isError ? (
        <WorkspaceState reason={String(evidence.error)} state="error" />
      ) : evidence.data ? (
        <div className="evidenceDrawerBody">
          {!evidence.data.data.redistribution_allowed ? (
            <Alert title="该证据不允许再分发；这里只展示治理元数据和原始来源链接。" type="warning" showIcon />
          ) : null}
          <Descriptions column={1} size="small">
            <Descriptions.Item label="RawObject">{evidence.data.data.raw_object_id}</Descriptions.Item>
            <Descriptions.Item label="Provider">{evidence.data.data.provider_id}</Descriptions.Item>
            <Descriptions.Item label="Content hash"><code>{evidence.data.data.content_hash}</code></Descriptions.Item>
            <Descriptions.Item label="Media type">{evidence.data.data.media_type}</Descriptions.Item>
            <Descriptions.Item label="Retrieved at">{evidence.data.data.retrieved_at}</Descriptions.Item>
            <Descriptions.Item label="Retention">{evidence.data.data.retention_policy}</Descriptions.Item>
            <Descriptions.Item label="License">{evidence.data.data.license_id}</Descriptions.Item>
            <Descriptions.Item label="Source">
              <a href={evidence.data.data.source_url} rel="noreferrer" target="_blank">打开原始来源</a>
            </Descriptions.Item>
          </Descriptions>
        </div>
      ) : null}
    </Drawer>
  )
}

function DisclosureView({ openEvidence }: { openEvidence: (id: string) => void }) {
  const [companyInput, setCompanyInput] = useState('')
  const [companyId, setCompanyId] = useState<string | null>(null)
  const query = useQuery({
    queryKey: ['disclosures', companyId],
    queryFn: ({ signal }) => getDisclosures(companyId!, signal),
    enabled: Boolean(companyId),
  })
  const columns: ColumnsType<DisclosureTimelineEntry> = [
    { title: '标题', dataIndex: 'title', width: 300 },
    { title: '报告期', dataIndex: 'report_period_end', width: 120 },
    {
      title: '发布时间',
      dataIndex: 'published_at',
      width: 260,
      render: (value: string, row) => (
        <span>{value} <Tag>{row.publication_time_precision === 'exact' ? '精确时间' : '仅日期'}</Tag></span>
      ),
    },
    { title: '市场可用', dataIndex: 'available_at', width: 210 },
    { title: '首次可交易', dataIndex: 'first_tradable_at', width: 210 },
    {
      title: '版本',
      key: 'version',
      width: 150,
      render: (_, row) => <Tag color={row.status === 'published' ? 'blue' : 'warning'}>v{row.version_sequence} · {row.status}</Tag>,
    },
    { title: '更正 / 撤回原因', dataIndex: 'status_reason', render: (value: string | null) => value ?? '—' },
    {
      title: '证据',
      key: 'evidence',
      width: 130,
      render: (_, row) => <Button onClick={() => openEvidence(row.raw_object_id)} type="link">查看原始证据</Button>,
    },
  ]
  return (
    <div className="evidenceView">
      <div className="evidenceQueryBar">
        <Input aria-label="公司 ID" onChange={(event) => setCompanyInput(event.target.value)} placeholder="显式输入 company_id" value={companyInput} />
        <Button disabled={!companyInput.trim()} onClick={() => setCompanyId(companyInput.trim())} type="primary">查询披露</Button>
      </div>
      {!companyId ? (
        <WorkspaceState reason="请输入真实 company_id；页面不默认选择公司或注入演示公告。" state="empty" title="尚未选择公司" />
      ) : query.isLoading ? (
        <WorkspaceState reason="正在读取官方披露版本链" state="loading" />
      ) : query.isError ? (
        <WorkspaceState reason={String(query.error)} state="error" title="披露时间线读取失败" />
      ) : query.data?.data.length === 0 ? (
        <WorkspaceState reason={`${companyId} 没有官方披露记录。`} state="empty" />
      ) : (
        <Table columns={columns} dataSource={query.data?.data} pagination={{ pageSize: 20 }} rowKey="disclosure_id" scroll={{ x: 1450 }} />
      )}
    </div>
  )
}

function FactFields({ form, onChange, comparison = false }: { form: FactForm; onChange: (value: FactForm) => void; comparison?: boolean }) {
  return (
    <div className="factQueryGrid">
      <Input aria-label={comparison ? '对比公司 ID' : '事实公司 ID'} onChange={(event) => onChange({ ...form, companyId: event.target.value })} placeholder="company_id" value={form.companyId} />
      <Input aria-label={comparison ? '对比证券 ID' : '事实证券 ID'} onChange={(event) => onChange({ ...form, securityId: event.target.value })} placeholder="security_id" value={form.securityId} />
      <Input aria-label={comparison ? '对比指标代码' : '事实指标代码'} onChange={(event) => onChange({ ...form, metricCode: event.target.value })} placeholder="metric_code" value={form.metricCode} />
      <Input aria-label="报告期" onChange={(event) => onChange({ ...form, reportPeriodEnd: event.target.value })} type="date" value={form.reportPeriodEnd} />
      <Select aria-label="期间类型" onChange={(periodType) => onChange({ ...form, periodType })} options={['q1', 'half_year', 'q3', 'annual', 'ttm'].map((value) => ({ label: value, value }))} value={form.periodType} />
      <Select aria-label="报表类型" onChange={(statementType) => onChange({ ...form, statementType })} options={['balance_sheet', 'income_statement', 'cash_flow_statement'].map((value) => ({ label: value, value }))} value={form.statementType} />
      {comparison ? <Input aria-label="Authority Rule" onChange={(event) => onChange({ ...form, authorityRuleVersion: event.target.value })} placeholder="authority rule version" value={form.authorityRuleVersion} /> : null}
    </div>
  )
}

function RevisionView({ openEvidence }: { openEvidence: (id: string) => void }) {
  const [form, setForm] = useState(emptyFactForm)
  const [params, setParams] = useState<URLSearchParams | null>(null)
  const query = useQuery({
    queryKey: ['fact-revisions', params?.toString()],
    queryFn: ({ signal }) => getFactRevisions(params!, signal),
    enabled: Boolean(params),
  })
  const columns: ColumnsType<FactRevisionEntry> = [
    { title: '指标', dataIndex: 'metric_code', width: 180 },
    { title: '值', dataIndex: 'value', width: 180, render: (value, row) => `${String(value)} ${row.currency ?? ''} ${row.unit}` },
    { title: 'Provider', dataIndex: 'provider_id', width: 150 },
    { title: 'Public revision', dataIndex: 'revision_sequence', width: 130 },
    { title: 'Available at', dataIndex: 'available_at', width: 210 },
    { title: 'System from', dataIndex: 'known_from', width: 210 },
    { title: 'System to', dataIndex: 'known_to', width: 210, render: (value: string | null) => value ?? 'open' },
    { title: 'Trust', dataIndex: 'trust_state', width: 150, render: (value: string) => <Tag>{value}</Tag> },
    { title: 'Quality', dataIndex: 'quality_state', width: 120 },
    { title: '证据', key: 'evidence', width: 130, render: (_, row) => <Button onClick={() => openEvidence(row.source_object_id)} type="link">查看原始证据</Button> },
  ]
  return (
    <div className="evidenceView">
      <FactFields form={form} onChange={setForm} />
      <Button disabled={!form.companyId.trim()} onClick={() => setParams(factParams(form, false))} type="primary">查询事实修订</Button>
      {!params ? <WorkspaceState reason="至少输入真实 company_id；可继续用证券、指标和报告期缩小范围。" state="empty" title="尚未查询事实" />
        : query.isLoading ? <WorkspaceState reason="正在读取双时间事实版本" state="loading" />
          : query.isError ? <WorkspaceState reason={String(query.error)} state="error" />
            : query.data?.data.length === 0 ? <WorkspaceState reason="没有匹配的事实版本。" state="empty" />
              : <Table columns={columns} dataSource={query.data?.data} pagination={{ pageSize: 20 }} rowKey="fact_id" scroll={{ x: 1550 }} />}
    </div>
  )
}

function SelectionCard({ mode, value }: { mode: 'current_research' | 'strict_historical'; value: FactSelectionEntry }) {
  return (
    <Card title={`${mode}：${value.status === 'selected' ? '已选择' : value.status === 'blocked' ? '阻断' : '不可用'}`}>
      {value.selected ? (
        <Descriptions column={1} size="small">
          <Descriptions.Item label="Value">{String(value.selected.value)}</Descriptions.Item>
          <Descriptions.Item label="Trust"><Tag>{value.selected.trust_state}</Tag></Descriptions.Item>
          <Descriptions.Item label="Fact">{value.selected.fact_id}</Descriptions.Item>
        </Descriptions>
      ) : <Alert title={value.reason ?? '没有可用观察'} type="warning" showIcon />}
      {value.blocks_downstream ? <Tag color="error">blocks downstream</Tag> : null}
      {value.conflicting_fact_ids.map((id) => <Tag color="error" key={id}>{id}</Tag>)}
    </Card>
  )
}

function ComparisonView() {
  const [form, setForm] = useState(emptyFactForm)
  const [params, setParams] = useState<URLSearchParams | null>(null)
  const complete = Boolean(form.companyId && form.securityId && form.metricCode && form.reportPeriodEnd && form.authorityRuleVersion)
  const query = useQuery({
    queryKey: ['fact-comparison', params?.toString()],
    queryFn: ({ signal }) => getFactComparison(params!, signal),
    enabled: Boolean(params),
  })
  return (
    <div className="evidenceView">
      <FactFields comparison form={form} onChange={setForm} />
      <Button disabled={!complete} onClick={() => setParams(factParams(form, true))} type="primary">执行对比</Button>
      {!params ? <WorkspaceState reason="对比不会把 normalized_current 提升为 PIT；请完整输入事实身份和 Authority Rule。" state="empty" title="尚未执行 Current / Strict 对比" />
        : query.isLoading ? <WorkspaceState reason="正在分别执行 current 与 strict 选择" state="loading" />
          : query.isError ? <WorkspaceState reason={String(query.error)} state="error" />
            : query.data ? <div className="comparisonGrid"><SelectionCard mode="current_research" value={query.data.data.current} /><SelectionCard mode="strict_historical" value={query.data.data.strict} /></div> : null}
    </div>
  )
}

function MismatchView() {
  const query = useQuery({ queryKey: ['financial-mismatches'], queryFn: ({ signal }) => getFinancialMismatches(signal) })
  const columns: ColumnsType<FinancialMismatchEntry> = useMemo(() => [
    { title: '类型', dataIndex: 'mismatch_type', width: 210 },
    { title: '状态', dataIndex: 'status', width: 110, render: (value: string) => <Tag color="error">{value}</Tag> },
    { title: '公司 / 指标', key: 'identity', render: (_, row) => `${row.company_id ?? '未映射'} / ${row.metric_code ?? '未映射'}` },
    { title: 'Provider', dataIndex: 'provider_ids', render: (values: string[]) => values.join(', ') },
    { title: '阻断原因', dataIndex: 'reason' },
  ], [])
  if (query.isLoading) return <WorkspaceState reason="正在读取 mismatch queue" state="loading" />
  if (query.isError) return <WorkspaceState reason={String(query.error)} state="error" />
  if (query.data?.data.length === 0) return <WorkspaceState reason="当前没有 pending mapping、质量阻断或多源值冲突。" state="empty" title="Mismatch queue 为空" />
  return <Table columns={columns} dataSource={query.data?.data} pagination={{ pageSize: 20 }} rowKey="mismatch_id" />
}

export function SystemEvidenceScreen() {
  const [active, setActive] = useState<EvidenceTab>('disclosures')
  const [rawObjectId, setRawObjectId] = useState<string | null>(null)
  const items = [
    { key: 'disclosures', label: '披露时间线', children: <DisclosureView openEvidence={setRawObjectId} /> },
    { key: 'revisions', label: '事实修订', children: <RevisionView openEvidence={setRawObjectId} /> },
    { key: 'comparison', label: 'Current / Strict', children: <ComparisonView /> },
    { key: 'mismatches', label: 'Mismatch Queue', children: <MismatchView /> },
  ]
  return (
    <div className="systemEvidenceScreen">
      <Alert title="诊断页面同时显示市场可用时间和系统已知时间；current 数据不会被当作 PIT。" type="info" showIcon />
      <Tabs activeKey={active} items={items} onChange={(value) => setActive(value as EvidenceTab)} />
      <EvidenceDrawer rawObjectId={rawObjectId} onClose={() => setRawObjectId(null)} />
    </div>
  )
}
