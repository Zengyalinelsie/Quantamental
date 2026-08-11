import { Alert, Descriptions, Empty, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'

import type {
  IndustryPeerProjection,
  ScreenNullableRankProjection,
  ScreenRankingProjection,
  ScreenRankingRowProjection,
  ScreenRankChangeProjection,
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

const columns: ColumnsType<ScreenRankingRowProjection> = [
  {
    title: 'Rank',
    key: 'rank',
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
          columns={columns}
          dataSource={projection.rows}
          onRow={(row) => ({
            'aria-label': `screen-ranking-row-${row.snapshot_id}`,
          })}
          pagination={false}
          rowClassName={(row) => row.selected ? 'screenRankingRow--selected' : ''}
          rowKey="snapshot_id"
          scroll={{ x: 1400 }}
          size="small"
        />
      </div>

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
