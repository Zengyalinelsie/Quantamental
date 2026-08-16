import { Alert, Button, Descriptions, Drawer, Empty, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useEffect, useState } from 'react'

import type {
  IndustryPeerProjection,
  ScreenComponentName,
  ScreenNullableRankProjection,
  ScreenRankingProjection,
  ScreenRankingRowProjection,
  ScreenRankChangeProjection,
  ScreenReturnIntervalProjection,
  ScreenRowComponentProjection,
} from './screenProjection'
import './screen.less'

interface ScreenRankingPanelProps {
  projection: ScreenRankingProjection
}

const dataModeLabels = {
  current_research: '当前研究',
  strict_historical: '严格历史研究',
} as const

const trustLabels = {
  normalized_current: '规范化当前数据',
  pit_verified: 'PIT 已验证',
} as const

function NullableRank({ value }: { value: ScreenNullableRankProjection }) {
  if (value.display === null) {
    return (
      <span
        aria-label={value.unavailable_reason ?? '排名字段不可用'}
        className="screenUnavailableValue"
      >
        —
      </span>
    )
  }
  return <span className="screenTabularValue">{value.display}</span>
}

function RankChange({ value }: { value: ScreenRankChangeProjection }) {
  if (value.display === null) return <NullableRank value={value} />
  return (
    <span className={`screenRankChange screenRankChange--${value.direction}`}>
      {value.display}
    </span>
  )
}

/**
 * One factor dimension cell.
 *
 * The server owns `display`, including the em dash for every non-quantified
 * status.  The status reason goes into `title` so that constrained ("bounded but
 * unquantified") stays distinguishable from unavailable ("missing") even though
 * both render the same dash — that difference matters in an audit.
 */
function ComponentCell({
  value,
  name,
}: {
  value: ScreenRowComponentProjection | undefined
  name: ScreenComponentName
}) {
  if (value === undefined) {
    return (
      <span
        className="screenUnavailableValue"
        title={`该行没有绑定的冻结 InvestmentView，${name} 分项不可用。`}
      >
        —
      </span>
    )
  }
  const quantified = value.status === 'quantified'
  return (
    <span
      className={quantified ? 'screenTabularValue' : 'screenUnavailableValue'}
      title={value.reason ?? `${value.label} · ${value.status}`}
    >
      {value.display}
    </span>
  )
}

function ReturnIntervalCell({
  value,
}: {
  value: ScreenReturnIntervalProjection | null | undefined
}) {
  if (!value || value.display === null) {
    return (
      <span
        className="screenUnavailableValue"
        title={value?.unavailable_reason ?? '该行没有绑定的冻结 InvestmentView，无法给出区间。'}
      >
        —
      </span>
    )
  }
  return <span className="screenTabularValue">{value.display}</span>
}

function componentOf(
  row: ScreenRankingRowProjection,
  name: ScreenComponentName,
): ScreenRowComponentProjection | undefined {
  return row.components?.find((item) => item.component === name)
}

const columns: ColumnsType<ScreenRankingRowProjection> = [
  {
    title: 'Rank',
    key: 'rank',
    fixed: 'left',
    width: 72,
    render: (_, row) => <strong className="screenTabularValue">{row.rank.display}</strong>,
  },
  {
    title: 'Security',
    key: 'security',
    width: 190,
    render: (_, row) => (
      <div className="screenSecurityCell">
        <strong>{row.security.display_name}</strong>
        <span>{row.security.symbol} · {row.security.exchange}</span>
      </div>
    ),
  },
  {
    title: 'Industry',
    key: 'industry',
    width: 145,
    render: (_, row) => (
      <div className="screenSecurityCell">
        <span>{row.industry.display_name}</span>
        <code>{row.industry.code}</code>
      </div>
    ),
  },
  {
    title: 'Previous',
    key: 'previous_rank',
    width: 92,
    render: (_, row) => <NullableRank value={row.previous_rank} />,
  },
  {
    title: 'Δ Rank',
    key: 'rank_change',
    width: 92,
    render: (_, row) => <RankChange value={row.rank_change} />,
  },
  {
    title: 'Score',
    key: 'score',
    width: 100,
    render: (_, row) => <span className="screenTabularValue">{row.score.display}</span>,
  },
  {
    title: 'Expected return',
    key: 'expected_return',
    width: 126,
    render: (_, row) => <span className="screenTabularValue">{row.expected_return.display}</span>,
  },
  {
    title: 'Confidence',
    key: 'confidence',
    width: 102,
    render: (_, row) => <span className="screenTabularValue">{row.confidence.display}</span>,
  },
  {
    title: '质量',
    key: 'component_quality',
    width: 90,
    render: (_, row) => <ComponentCell name="quality" value={componentOf(row, 'quality')} />,
  },
  {
    title: '估值预期差',
    key: 'component_valuation',
    width: 110,
    render: (_, row) => <ComponentCell name="valuation" value={componentOf(row, 'valuation')} />,
  },
  {
    title: '改善',
    key: 'component_revision',
    width: 90,
    render: (_, row) => <ComponentCell name="revision" value={componentOf(row, 'revision')} />,
  },
  {
    title: '60日预期收益区间',
    key: 'expected_return_interval',
    width: 158,
    render: (_, row) => <ReturnIntervalCell value={row.expected_return_interval} />,
  },
  {
    title: 'Trust',
    key: 'trust',
    width: 145,
    render: (_, row) => <Tag>{row.trust_state}</Tag>,
  },
  {
    title: 'Frozen binding',
    key: 'binding',
    width: 240,
    render: (_, row) => (
      <div className="screenBindingCell">
        <code>{row.snapshot_id}</code>
        <code>{row.investment_view_id}</code>
      </div>
    ),
  },
]

const compactColumnKeys = new Set([
  'rank',
  'security',
  'score',
  'expected_return',
  'confidence',
])

function useCompactScreenTable() {
  const query = '(max-width: 1100px) and (min-width: 821px)'
  const [compact, setCompact] = useState(() => (
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(query).matches
      : false
  ))

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined
    const media = window.matchMedia(query)
    const update = () => setCompact(media.matches)
    update()
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])

  return compact
}

function PeerList({ peers }: { peers: IndustryPeerProjection[] }) {
  if (peers.length === 0) {
    return <Empty description="服务端未返回合格行业 peers" image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }
  return (
    <ul className="screenPeerList" data-testid="industry-peer-list">
      {peers.map((peer) => (
        <li key={peer.snapshot_id}>
          <div>
            <strong>{peer.display_name}</strong>
            <span>{peer.symbol}</span>
          </div>
          <div>
            <span>Rank {peer.rank.display}</span>
            <strong>{peer.expected_return.display}</strong>
          </div>
        </li>
      ))}
    </ul>
  )
}

export function ScreenRankingPanel({ projection }: ScreenRankingPanelProps) {
  const compactTable = useCompactScreenTable()
  const [detailSnapshotId, setDetailSnapshotId] = useState<string | null>(null)
  const detailRow = projection.rows.find((row) => row.snapshot_id === detailSnapshotId) ?? null

  useEffect(() => {
    if (detailSnapshotId !== null && detailRow === null) {
      setDetailSnapshotId(null)
    }
  }, [detailRow, detailSnapshotId])

  const compactColumns: ColumnsType<ScreenRankingRowProjection> = [
    ...columns.filter((column) => compactColumnKeys.has(String(column.key))),
    {
      title: 'Details',
      key: 'details',
      width: 90,
      render: (_, row) => (
        <Button
          aria-label={`查看${row.security.display_name}详情`}
          onClick={() => setDetailSnapshotId(row.snapshot_id)}
          size="small"
          type="link"
        >
          详情
        </Button>
      ),
    },
  ]

  return (
    <section className="screenRankingPanel">
      <header className="screenPanelHeader">
        <div>
          <p>SERVER-RANKED SIGNAL SNAPSHOTS</p>
          <h2>{projection.universe.display_name} · {projection.universe.universe_size}</h2>
          <code>{projection.universe.universe_version_id}</code>
        </div>
        <div className="screenContextTags">
          <Tag color={projection.data_mode === 'strict_historical' ? 'blue' : 'gold'}>
            {dataModeLabels[projection.data_mode]}
          </Tag>
          <Tag color={projection.trust_state === 'pit_verified' ? 'green' : 'gold'}>
            {trustLabels[projection.trust_state]}
          </Tag>
          <Tag>{projection.approval_scope}</Tag>
        </div>
      </header>

      {projection.warnings.map((warning) => (
        <Alert key={warning} showIcon title={warning} type="warning" />
      ))}

      <div className="screenSelectionGrid">
        <section className="screenSelectedSecurity" data-testid="selected-screen-security">
          <p>SELECTED SECURITY</p>
          {projection.selected_security ? (
            <>
              <h3>{projection.selected_security.display_name} · {projection.selected_security.symbol}</h3>
              <span>{projection.selected_security.industry.display_name} · {projection.selected_security.industry.code}</span>
              <code>{projection.selected_security.snapshot_id}</code>
            </>
          ) : (
            <Empty description="服务端未选择 Security" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </section>
        <section className="screenIndustryPeers">
          <p>INDUSTRY PEERS</p>
          <PeerList peers={projection.industry_peers} />
        </section>
      </div>

      <div className="screenRankingTable">
        <Table
          columns={compactTable ? compactColumns : columns}
          dataSource={projection.rows}
          onRow={(row) => ({
            'aria-label': `screen-ranking-row-${row.snapshot_id}`,
          })}
          pagination={false}
          rowClassName={(row) => row.selected ? 'screenRankingRow--selected' : ''}
          rowKey="snapshot_id"
          scroll={{ x: compactTable ? 760 : 1400 }}
          size="small"
        />
      </div>

      <ul className="screenMobileRecordList" data-testid="screen-mobile-record-list">
        {projection.rows.map((row) => (
          <li
            className={row.selected ? 'screenMobileRecord--selected' : ''}
            key={row.snapshot_id}
          >
            <header>
              <strong>{row.security.display_name} · {row.security.symbol}</strong>
              <span>Rank {row.rank.display}</span>
            </header>
            <div className="screenMobileRecord__metrics">
              {row.previous_rank.display === null ? (
                <span>Previous <NullableRank value={row.previous_rank} /></span>
              ) : (
                <span>Previous {row.previous_rank.display}</span>
              )}
              <span>Δ Rank <RankChange value={row.rank_change} /></span>
              <span>Score {row.score.display}</span>
              <span>Expected return {row.expected_return.display}</span>
              <span>Confidence {row.confidence.display}</span>
              <span>Trust {row.trust_state}</span>
            </div>
            <p>{row.industry.display_name} · {row.industry.code} · {row.security.exchange}</p>
            <div className="screenMobileRecord__bindings">
              <code>{row.snapshot_id}</code>
              <code>{row.investment_view_id}</code>
              <code>{row.content_hash}</code>
            </div>
          </li>
        ))}
      </ul>

      <Drawer
        aria-label={detailRow
          ? `${detailRow.security.display_name} · ${detailRow.security.symbol}`
          : 'Screen row detail'}
        onClose={() => setDetailSnapshotId(null)}
        open={detailRow !== null}
        title={detailRow
          ? `${detailRow.security.display_name} · ${detailRow.security.symbol}`
          : 'Screen row detail'}
        size={380}
      >
        {detailRow ? (
          <Descriptions bordered column={1} size="small">
            <Descriptions.Item label="Industry">
              {detailRow.industry.display_name} · <code>{detailRow.industry.code}</code>
            </Descriptions.Item>
            <Descriptions.Item label="Previous rank">
              <NullableRank value={detailRow.previous_rank} />
            </Descriptions.Item>
            <Descriptions.Item label="Rank change">
              <RankChange value={detailRow.rank_change} />
            </Descriptions.Item>
            <Descriptions.Item label="Trust">{detailRow.trust_state}</Descriptions.Item>
            <Descriptions.Item label="Snapshot"><code>{detailRow.snapshot_id}</code></Descriptions.Item>
            <Descriptions.Item label="InvestmentView">
              <code>{detailRow.investment_view_id}</code>
            </Descriptions.Item>
            <Descriptions.Item label="Content hash">
              <code>{detailRow.content_hash}</code>
            </Descriptions.Item>
          </Descriptions>
        ) : null}
      </Drawer>

      <Descriptions bordered className="screenLineage" column={{ xs: 1, sm: 1, md: 2 }} size="small">
        <Descriptions.Item label="Decision time">{projection.decision_time}</Descriptions.Item>
        <Descriptions.Item label="Data cutoff">{projection.data_cutoff}</Descriptions.Item>
        <Descriptions.Item label="ModelVersion"><code>{projection.model_version_id}</code></Descriptions.Item>
        <Descriptions.Item label="Screen"><code>{projection.screen_id}</code></Descriptions.Item>
        <Descriptions.Item label="FactorVersion">
          <div className="screenVersionStack">{projection.factor_version_ids.map((id) => <code key={id}>{id}</code>)}</div>
        </Descriptions.Item>
        <Descriptions.Item label="FeatureVersion">
          <div className="screenVersionStack">{projection.feature_version_ids.map((id) => <code key={id}>{id}</code>)}</div>
        </Descriptions.Item>
        <Descriptions.Item label="DatasetVersion" span={{ xs: 1, sm: 1, md: 2 }}>
          <div className="screenVersionStack">{projection.dataset_version_ids.map((id) => <code key={id}>{id}</code>)}</div>
        </Descriptions.Item>
      </Descriptions>
    </section>
  )
}

export type { ScreenRankingProjection } from './screenProjection'
