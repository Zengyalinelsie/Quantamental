import { Alert, Descriptions, Tag } from 'antd'

import { ExpectedReturnDistribution } from './ExpectedReturnDistribution'
import { InvestmentComponentWaterfall } from './InvestmentComponentWaterfall'
import { InvestmentEvidencePanel } from './InvestmentEvidencePanel'
import type {
  InvestmentDataMode,
  InvestmentTrustState,
  InvestmentViewProjection,
} from './investmentViewProjection'
import './investmentViewSummary.less'

interface InvestmentViewSummaryProps {
  projection: InvestmentViewProjection
}

const dataModeLabels: Record<InvestmentDataMode, string> = {
  current_research: '当前研究',
  strict_historical: '严格历史研究',
}

const trustLabels: Record<InvestmentTrustState, string> = {
  normalized_current: '规范化当前数据',
  pit_verified: 'PIT 已验证',
}

const trustColors: Record<InvestmentTrustState, string> = {
  normalized_current: 'gold',
  pit_verified: 'green',
}

export function InvestmentViewSummary({ projection }: InvestmentViewSummaryProps) {
  return (
    <article className="investmentViewSummary">
      <header className="investmentViewHeader">
        <div>
          <p className="investmentViewHeader__eyebrow">INVESTMENT VIEW · {projection.horizon}</p>
          <h2>{projection.security.display_name} · {projection.security.symbol}</h2>
          <p>
            {projection.security.exchange} · {projection.security.security_id}
            {' · '}Decision time {projection.decision_time}
          </p>
        </div>
        <div className="investmentViewHeader__trust" aria-label="数据用途与可信状态">
          <Tag color={projection.data_mode === 'strict_historical' ? 'blue' : 'gold'}>
            {dataModeLabels[projection.data_mode]}
          </Tag>
          <Tag color={trustColors[projection.trust_state]}>
            {trustLabels[projection.trust_state]}
          </Tag>
          <span>{projection.trust_reason}</span>
        </div>
      </header>

      {projection.warnings.map((warning) => (
        <Alert className="investmentViewWarning" key={warning} showIcon title={warning} type="warning" />
      ))}

      <ExpectedReturnDistribution
        confidence={projection.confidence.display}
        distribution={projection.distribution}
        horizon={projection.horizon}
      />
      <InvestmentComponentWaterfall
        closure={projection.closure}
        components={projection.components}
        residual={projection.residual}
      />
      <InvestmentEvidencePanel
        catalysts={projection.catalysts}
        evidence={projection.evidence}
        invalidators={projection.invalidators}
      />

      <section aria-labelledby="version-heading" className="investmentViewSection investmentViewVersions">
        <header className="investmentViewSection__heading">
          <div>
            <p className="investmentViewSection__eyebrow">IMMUTABLE LINEAGE</p>
            <h3 id="version-heading">版本绑定</h3>
          </div>
          <code>{projection.view_id}</code>
        </header>
        <Descriptions bordered column={{ xs: 1, sm: 1, md: 2 }} size="small">
          <Descriptions.Item label="DatasetVersion">
            <div className="versionStack">
              {projection.versions.dataset_version_ids.map((id) => <code key={id}>{id}</code>)}
            </div>
          </Descriptions.Item>
          <Descriptions.Item label="FeatureVersion">
            <div className="versionStack">
              {projection.versions.feature_version_ids.map((id) => <code key={id}>{id}</code>)}
            </div>
          </Descriptions.Item>
          <Descriptions.Item label="ModelVersion"><code>{projection.versions.model_version_id}</code></Descriptions.Item>
          <Descriptions.Item label="Run"><code>{projection.versions.run_id}</code></Descriptions.Item>
          <Descriptions.Item label="CodeVersion"><code>{projection.versions.code_version}</code></Descriptions.Item>
          <Descriptions.Item label="Environment"><code>{projection.versions.environment_id}</code></Descriptions.Item>
          <Descriptions.Item label="Content hash" span={{ xs: 1, sm: 1, md: 2 }}><code>{projection.versions.content_hash}</code></Descriptions.Item>
          <Descriptions.Item label="Frozen Artifact" span={{ xs: 1, sm: 1, md: 2 }}><code>{projection.versions.artifact_id}</code></Descriptions.Item>
        </Descriptions>
      </section>
    </article>
  )
}

export type { InvestmentViewProjection } from './investmentViewProjection'
