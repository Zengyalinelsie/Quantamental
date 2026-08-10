import { ProTable, type ProColumns } from '@ant-design/pro-components'
import { useQuery } from '@tanstack/react-query'
import { Alert, Segmented, Select, Statistic, Tag } from 'antd'
import type { FilterValue, SorterResult, TablePaginationConfig } from 'antd/es/table/interface'
import { useEffect, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

import {
  getUniverseCoverage,
  getUniverseSnapshot,
  getUniverseVersions,
  type UniverseRow,
} from '../api/client'
import { WorkspaceState } from '../components/WorkspaceState'
import { parseUniverseView, updateUniverseView } from '../state/universeView'
import { useWorkspaceStore } from '../state/workspace'

function currentLocalDate() {
  const now = new Date()
  const year = now.getFullYear()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const listingStateLabels: Record<string, string> = {
  active: '正常挂牌',
  suspended_listing: '暂停上市',
  terminated: '终止上市',
}

export function UniverseScreen() {
  const [searchParams, setSearchParams] = useSearchParams()
  const setSystemAsOf = useWorkspaceStore((state) => state.setSystemAsOf)
  const view = parseUniverseView(searchParams)
  const asOf = view.pointMode === 'current' ? currentLocalDate() : view.asOf
  const versions = useQuery({
    queryKey: ['universe-versions'],
    queryFn: ({ signal }) => getUniverseVersions(signal),
  })
  const snapshot = useQuery({
    queryKey: ['universe-snapshot', view.universeId, asOf],
    queryFn: ({ signal }) => getUniverseSnapshot(view.universeId!, asOf!, signal),
    enabled: Boolean(view.universeId && asOf),
  })
  const coverage = useQuery({
    queryKey: ['universe-coverage', view.universeId, asOf],
    queryFn: ({ signal }) => getUniverseCoverage(view.universeId!, asOf!, signal),
    enabled: Boolean(view.universeId && asOf),
  })
  useEffect(() => {
    if (snapshot.data?.context.system_as_of) {
      setSystemAsOf(snapshot.data.context.system_as_of)
    }
  }, [setSystemAsOf, snapshot.data])

  const updateView = (patch: Parameters<typeof updateUniverseView>[1]) => {
    setSearchParams(updateUniverseView(searchParams, patch), { replace: true })
  }
  const rows = useMemo(() => snapshot.data?.data.rows ?? [], [snapshot.data])
  const industryFilters = useMemo(
    () => [...new Set(rows.map((row) => row.industry_name).filter(Boolean))]
      .sort((left, right) => left!.localeCompare(right!, 'zh-CN'))
      .map((value) => ({ text: value!, value: value! })),
    [rows],
  )
  const hiddenColumnsKey = view.hiddenColumns.join(',')
  const columns: ProColumns<UniverseRow>[] = [
    {
      title: '证券',
      dataIndex: 'code',
      key: 'security',
      width: 190,
      fixed: 'left',
      sorter: (left, right) => (left.code ?? '').localeCompare(right.code ?? ''),
      sortOrder: view.sort === 'code' ? view.order : null,
      render: (_, row) => (
        <span className="securityIdentity">
          <strong>
            <span>{row.code ?? '—'}</span> · <span>{row.name ?? '身份未解析'}</span>
          </strong>
          <small>{row.listing_id}</small>
          {row.delisted_on ? <Tag color="error">退市日 {row.delisted_on}</Tag> : null}
        </span>
      ),
    },
    {
      title: '交易所 / 板块',
      dataIndex: 'exchange',
      key: 'board',
      width: 130,
      render: (_, row) => `${row.exchange ?? '—'} / ${row.board ?? '—'}`,
    },
    {
      title: '行业',
      dataIndex: 'industry_name',
      key: 'industry',
      width: 130,
      filters: industryFilters,
      filteredValue: view.industry ? [view.industry] : null,
      onFilter: (value, row) => row.industry_name === value,
      render: (_, row) => row.industry_name ?? '未覆盖',
    },
    {
      title: '挂牌 / ST',
      dataIndex: 'listing_state',
      key: 'listing_state',
      width: 145,
      filters: Object.entries(listingStateLabels).map(([value, text]) => ({ value, text })),
      filteredValue: view.listingState ? [view.listingState] : null,
      onFilter: (value, row) => row.listing_state === value,
      render: (_, row) => (
        <span className="statusTags">
          <Tag>{row.listing_state ? listingStateLabels[row.listing_state] : '状态缺失'}</Tag>
          {row.special_treatment === 'star_st' ? <Tag color="error">*ST</Tag> : null}
          {row.special_treatment === 'st' ? <Tag color="warning">ST</Tag> : null}
        </span>
      ),
    },
    {
      title: '资格',
      dataIndex: 'tradable_eligible',
      key: 'eligibility',
      width: 150,
      filters: [
        { text: '研究池', value: 'research' },
        { text: '可交易池', value: 'tradable' },
      ],
      filteredValue: view.eligibility ? [view.eligibility] : null,
      onFilter: (value, row) => value === 'tradable'
        ? row.tradable_eligible
        : row.research_eligible,
      render: (_, row) => (
        <span className="statusTags">
          <Tag color={row.research_eligible ? 'blue' : 'default'}>
            {row.research_eligible ? '研究池' : '非研究池'}
          </Tag>
          <Tag color={row.tradable_eligible ? 'success' : 'error'}>
            {row.tradable_eligible ? '可交易' : '不可交易'}
          </Tag>
        </span>
      ),
    },
    {
      title: '纳入 / 排除原因',
      dataIndex: 'exclusion_reasons',
      key: 'reasons',
      width: 260,
      render: (_, row) => (
        <span className="reasonTags">
          {row.inclusion_reasons.map((reason) => <Tag key={`in:${reason}`}>{reason}</Tag>)}
          {row.exclusion_reasons.map((reason) => (
            <Tag color="error" key={`out:${reason}`}>{reason}</Tag>
          ))}
        </span>
      ),
    },
    {
      title: '基准',
      dataIndex: 'benchmark_member',
      key: 'benchmark_member',
      width: 90,
      filters: [{ text: '基准成员', value: true }],
      filteredValue: null,
      onFilter: (_, row) => row.benchmark_member,
      render: (_, row) => row.benchmark_member ? <Tag color="purple">基准</Tag> : '—',
    },
  ]
  const columnState = useMemo(
    () => Object.fromEntries(
      hiddenColumnsKey.split(',').filter(Boolean).map((key) => [key, { show: false }]),
    ),
    [hiddenColumnsKey],
  )

  return (
    <div className="universeScreen">
      <section aria-label="股票池查询条件" className="universeControls">
        <label>
          <span>UNIVERSE VERSION</span>
          <Select
            aria-label="Universe Version"
            loading={versions.isLoading}
            onChange={(universeId) => updateView({ universeId })}
            options={(versions.data?.data ?? []).map((version) => ({
              label: version.universe_version_id,
              value: version.universe_version_id,
            }))}
            placeholder="选择 UniverseVersion（不默认选择）"
            value={view.universeId}
          />
        </label>
        <label>
          <span>查询时点</span>
          <Segmented
            onChange={(value) => updateView({
              pointMode: value as 'current' | 'historical',
              asOf: value === 'current' ? null : view.asOf,
            })}
            options={[
              { label: '当前时点', value: 'current' },
              { label: '历史日期', value: 'historical' },
            ]}
            value={view.pointMode}
          />
        </label>
        {view.pointMode === 'historical' ? (
          <label>
            <span>AS OF（Asia/Shanghai）</span>
            <input
              aria-label="历史查询日期"
              onChange={(event) => updateView({ asOf: event.target.value || null })}
              type="date"
              value={view.asOf ?? ''}
            />
          </label>
        ) : (
          <span className="currentAsOf">
            <small>AS OF（本地日期）</small>
            <strong>{asOf}</strong>
          </span>
        )}
      </section>

      {view.pointMode === 'historical' ? (
        <Alert
          title="历史日期重建使用 current_research 数据合同，不是 strict_historical，也不代表 PIT verified；当前身份记录可能包含查询日后才获知的信息。"
          showIcon
          type="warning"
        />
      ) : null}

      {versions.isLoading ? (
        <WorkspaceState reason="正在读取 UniverseVersion" state="loading" />
      ) : versions.isError ? (
        <WorkspaceState reason={String(versions.error)} state="error" />
      ) : versions.data?.data.length === 0 ? (
        <WorkspaceState
          reason="只读 API 返回 0 个版本；平台不会注入演示股票填充页面。"
          state="empty"
          title="尚无可用的 UniverseVersion"
        />
      ) : !view.universeId ? (
        <WorkspaceState
          reason="请选择一个真实 API 返回的版本；平台不做默认股票池选择。"
          state="empty"
          title="尚未选择 UniverseVersion"
        />
      ) : !asOf ? (
        <WorkspaceState reason="历史模式需要显式 AS OF 日期。" state="empty" />
      ) : snapshot.isLoading || coverage.isLoading ? (
        <WorkspaceState reason="正在重建查询日成员和覆盖率" state="loading" />
      ) : snapshot.isError || coverage.isError ? (
        <WorkspaceState
          reason={String(snapshot.error ?? coverage.error)}
          state="error"
        />
      ) : rows.length === 0 ? (
        <WorkspaceState
          reason={`${view.universeId} 在 ${asOf} 没有返回成员。`}
          state="empty"
        />
      ) : (
        <>
          <section aria-label="数据覆盖" className="coverageGrid">
            <Statistic title="成员" value={coverage.data?.data.total_members ?? 0} />
            <Statistic title="身份已解析" value={coverage.data?.data.identity_resolved ?? 0} />
            <Statistic title="研究池" value={coverage.data?.data.research_eligible ?? 0} />
            <Statistic title="可交易池" value={coverage.data?.data.tradable_eligible ?? 0} />
            <Statistic
              precision={1}
              suffix="%"
              title="身份覆盖率"
              value={(coverage.data?.data.identity_coverage ?? 0) * 100}
            />
          </section>
          <section aria-label="股票池成员" className="universeTable">
            <div className="datasetEvidence">
              <span>DATASET VERSION</span>
              <strong>{snapshot.data?.data.dataset_version_id}</strong>
              <span>DATA MODE</span>
              <strong>{snapshot.data?.context.data_mode}</strong>
              <span>SYSTEM AS OF</span>
              <strong>{snapshot.data?.context.system_as_of}</strong>
            </div>
            <ProTable<UniverseRow>
              cardBordered={false}
              columns={columns}
              columnsState={{
                value: columnState,
                onChange: (state) => {
                  const hiddenColumns = Object.entries(state)
                    .filter(([, value]) => value?.show === false)
                    .map(([key]) => key)
                    .sort()
                  if (hiddenColumns.join(',') !== view.hiddenColumns.join(',')) {
                    updateView({ hiddenColumns })
                  }
                },
              }}
              dataSource={rows}
              dateFormatter="string"
              onChange={(
                _: TablePaginationConfig,
                filters: Record<string, FilterValue | null>,
                sorter: SorterResult<UniverseRow> | SorterResult<UniverseRow>[],
              ) => {
                const selected = Array.isArray(sorter) ? sorter[0] : sorter
                updateView({
                  eligibility: filters.tradable_eligible?.[0] as 'research' | 'tradable' ?? null,
                  industry: filters.industry_name?.[0]?.toString() ?? null,
                  listingState: filters.listing_state?.[0]?.toString() ?? null,
                  sort: selected?.order && selected.columnKey === 'security' ? 'code' : null,
                  order: selected?.order ?? null,
                })
              }}
              options={{ density: true, fullScreen: true, reload: false, setting: true }}
              pagination={{ pageSize: 20, showSizeChanger: true }}
              rowKey="listing_id"
              scroll={{ x: 1150 }}
              search={false}
              toolBarRender={false}
            />
          </section>
        </>
      )}
    </div>
  )
}
