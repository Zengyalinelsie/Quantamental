import { useQuery } from '@tanstack/react-query'
import { Alert, Card, Descriptions, Pagination, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useMemo, useState } from 'react'

import {
  getSystemSection,
  type CoverageReportEntry,
  type DatasetCatalogEntry,
  type IngestionCheckpointEntry,
  type IngestionJobEntry,
  type LineageCatalogEntry,
  type QualityReportEntry,
  type SystemSection,
} from '../api/client'
import { WorkspaceState } from '../components/WorkspaceState'
import { useWorkspaceStore } from '../state/workspace'

const labels: Record<SystemSection, { empty: string; error: string; loading: string }> = {
  catalog: {
    empty: '尚无 DatasetVersion',
    error: '数据目录读取失败',
    loading: '正在读取 DatasetVersion',
  },
  quality: {
    empty: '尚无质量报告',
    error: '质量报告读取失败',
    loading: '正在读取质量报告',
  },
  lineage: {
    empty: '尚无血缘记录',
    error: '数据血缘读取失败',
    loading: '正在读取数据血缘',
  },
  jobs: {
    empty: '尚无摄取任务',
    error: '摄取任务读取失败',
    loading: '正在读取摄取任务',
  },
}

function statusColor(status: string) {
  if (status === 'passed' || status === 'succeeded') return 'success'
  if (status === 'failed' || status === 'blocked') return 'error'
  if (status === 'warned') return 'warning'
  if (status === 'running') return 'processing'
  return 'default'
}

const TABLE_PAGE_SIZE = 20

function useClientPage<T>(rows: T[]) {
  const [requestedPage, setRequestedPage] = useState(1)
  const lastPage = Math.max(1, Math.ceil(rows.length / TABLE_PAGE_SIZE))
  const currentPage = Math.min(requestedPage, lastPage)
  const pageRows = useMemo(() => {
    const start = (currentPage - 1) * TABLE_PAGE_SIZE
    return rows.slice(start, start + TABLE_PAGE_SIZE)
  }, [currentPage, rows])

  useEffect(() => {
    setRequestedPage(1)
  }, [rows])

  return {
    pageRows,
    pagination: {
      current: currentPage,
      pageSize: TABLE_PAGE_SIZE,
      showSizeChanger: false,
      total: rows.length,
      onChange: (page: number) => setRequestedPage(Math.max(1, Math.min(page, lastPage))),
    },
  }
}

function CatalogTable({ rows }: { rows: DatasetCatalogEntry[] }) {
  const page = useClientPage(rows)
  const columns: ColumnsType<DatasetCatalogEntry> = [
    { title: 'DatasetVersion', dataIndex: 'dataset_version_id', width: 300 },
    { title: 'Schema', dataIndex: 'schema_version', width: 180 },
    { title: '创建时间', dataIndex: 'created_at', width: 210 },
    {
      title: 'Content hash',
      dataIndex: 'content_hash',
      ellipsis: true,
      render: (value: string) => <code>{value}</code>,
    },
  ]
  return (
    <Table
      columns={columns}
      dataSource={page.pageRows}
      pagination={page.pagination}
      rowKey="dataset_version_id"
    />
  )
}

function QualityTable({ rows }: { rows: QualityReportEntry[] }) {
  const page = useClientPage(rows)
  const columns: ColumnsType<QualityReportEntry> = [
    { title: '报告', dataIndex: 'quality_report_id', width: 280 },
    { title: 'DatasetVersion', dataIndex: 'dataset_version_id', width: 280 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (value: string) => <Tag color={statusColor(value)}>{value}</Tag>,
    },
    { title: '通过', dataIndex: 'checks_passed', width: 90 },
    { title: '失败', dataIndex: 'checks_failed', width: 90 },
    {
      title: 'Warning',
      dataIndex: 'warnings',
      render: (warnings: string[]) => warnings.length ? warnings.join('；') : '—',
    },
  ]
  return (
    <Table
      columns={columns}
      dataSource={page.pageRows}
      pagination={page.pagination}
      rowKey="quality_report_id"
    />
  )
}

function LineageTable({ rows }: { rows: LineageCatalogEntry[] }) {
  const page = useClientPage(rows)
  const columns: ColumnsType<LineageCatalogEntry> = [
    { title: '上游', dataIndex: 'upstream_id' },
    { title: '关系', dataIndex: 'relation', width: 180 },
    { title: '下游', dataIndex: 'downstream_id' },
  ]
  return (
    <Table
      columns={columns}
      dataSource={page.pageRows}
      pagination={page.pagination}
      rowKey={(row) => `${row.upstream_id}:${row.relation}:${row.downstream_id}`}
    />
  )
}

function CoverageEvidence({
  jobId,
  rows,
}: {
  jobId: string
  rows: CoverageReportEntry[]
}) {
  const page = useClientPage(rows)
  return (
    <section
      aria-label={`${jobId} coverage reports`}
      className="systemJobEvidenceGroup"
    >
      <div className="systemJobEvidenceHeading">
        <span>COVERAGE REPORTS</span>
        <strong>{rows.length} TOTAL</strong>
      </div>
      <div className="systemJobEvidence">
        {page.pageRows.map((report) => (
          <section key={report.coverage_report_id}>
            <small>COVERAGE · {report.data_domain}</small>
            <strong>
              {report.observed_rows} / {report.expected_rows ?? '未知'}
            </strong>
            {report.warnings.map((warning) => <span key={warning}>{warning}</span>)}
          </section>
        ))}
      </div>
      <Pagination {...page.pagination} hideOnSinglePage size="small" />
    </section>
  )
}

function CheckpointEvidence({
  jobId,
  rows,
}: {
  jobId: string
  rows: IngestionCheckpointEntry[]
}) {
  const page = useClientPage(rows)
  return (
    <section
      aria-label={`${jobId} checkpoints`}
      className="systemJobEvidenceGroup"
    >
      <div className="systemJobEvidenceHeading">
        <span>CHECKPOINTS</span>
        <strong>{rows.length} TOTAL</strong>
      </div>
      <div className="systemJobEvidence">
        {page.pageRows.map((checkpoint) => (
          <section key={checkpoint.checkpoint_key}>
            <small>CHECKPOINT · {checkpoint.market ?? 'ALL'}</small>
            <strong>
              {checkpoint.processed_rows} processed · {checkpoint.rejected_rows} rejected
            </strong>
            {checkpoint.error ? <span>{checkpoint.error}</span> : null}
          </section>
        ))}
      </div>
      <Pagination {...page.pagination} hideOnSinglePage size="small" />
    </section>
  )
}

function JobCards({ rows }: { rows: IngestionJobEntry[] }) {
  const page = useClientPage(rows)
  return (
    <>
      <div className="systemJobs">
        {page.pageRows.map((job) => (
          <Card
            key={job.job_id}
            title={job.plan_id}
            extra={<Tag color={statusColor(job.status)}>{job.status}</Tag>}
          >
            <Descriptions column={{ xs: 1, sm: 2, lg: 4 }} size="small">
              <Descriptions.Item label="Provider">{job.provider_id}</Descriptions.Item>
              <Descriptions.Item label="Trust">
                <Tag>{job.output_trust_state}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="区间">{job.start_date} — {job.end_date}</Descriptions.Item>
              <Descriptions.Item label="DatasetVersion">{job.dataset_version_id ?? '未生成'}</Descriptions.Item>
            </Descriptions>
            {job.failure_reasons.length ? (
              <Alert
                className="systemJobAlert"
                title="阻断 / 失败原因"
                description={job.failure_reasons.join('；')}
                showIcon
                type="error"
              />
            ) : null}
            <CoverageEvidence jobId={job.job_id} rows={job.coverage_reports} />
            <CheckpointEvidence jobId={job.job_id} rows={job.checkpoints} />
          </Card>
        ))}
      </div>
      <Pagination {...page.pagination} hideOnSinglePage />
    </>
  )
}

export function SystemScreen({ section }: { section: SystemSection }) {
  const setSystemAsOf = useWorkspaceStore((state) => state.setSystemAsOf)
  const query = useQuery({
    queryKey: ['system', section],
    queryFn: ({ signal }) => getSystemSection(section, signal),
  })
  useEffect(() => {
    if (query.data?.context.system_as_of) {
      setSystemAsOf(query.data.context.system_as_of)
    }
  }, [query.data, setSystemAsOf])

  if (query.isLoading) {
    return <WorkspaceState reason={labels[section].loading} state="loading" />
  }
  if (query.isError) {
    return (
      <WorkspaceState
        reason={String(query.error)}
        state="error"
        title={labels[section].error}
      />
    )
  }
  const data = query.data?.data ?? []
  if (data.length === 0) {
    return (
      <WorkspaceState
        reason="只读 API 返回 0 条记录；平台不会注入运行时演示数据。"
        state="empty"
        title={labels[section].empty}
      />
    )
  }
  return (
    <div className="systemScreen">
      <div className="datasetEvidence">
        <span>DATA MODE</span>
        <strong>{query.data?.context.data_mode}</strong>
        <span>DEPLOYMENT</span>
        <strong>{query.data?.context.deployment_stage}</strong>
        <span>SYSTEM AS OF</span>
        <strong>{query.data?.context.system_as_of}</strong>
      </div>
      {section === 'catalog' ? <CatalogTable rows={data as DatasetCatalogEntry[]} /> : null}
      {section === 'quality' ? <QualityTable rows={data as QualityReportEntry[]} /> : null}
      {section === 'lineage' ? <LineageTable rows={data as LineageCatalogEntry[]} /> : null}
      {section === 'jobs' ? <JobCards rows={data as IngestionJobEntry[]} /> : null}
    </div>
  )
}
