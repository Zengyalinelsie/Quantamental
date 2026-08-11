import { Alert, Descriptions, Tag } from 'antd'

import type {
  AlphaModelReadinessProjection,
  ApprovedAlphaFactorProjection,
} from './screenProjection'
import './screen.less'

interface AlphaModelReadinessPanelProps {
  projection: AlphaModelReadinessProjection
}

function ApprovedFactorCard({ factor }: { factor: ApprovedAlphaFactorProjection }) {
  return (
    <article className="approvedFactorCard">
      <header>
        <div>
          <span>FACTOR VERSION</span>
          <strong>{factor.factor_version_id}</strong>
        </div>
        <Tag color="green">{factor.lifecycle_status}</Tag>
      </header>
      <Descriptions bordered column={1} size="small">
        <Descriptions.Item label="Factor hash"><code>{factor.factor_version_hash}</code></Descriptions.Item>
        <Descriptions.Item label="Review ID"><code>{factor.review_id}</code></Descriptions.Item>
        <Descriptions.Item label="Review hash"><code>{factor.review_hash}</code></Descriptions.Item>
        <Descriptions.Item label="ValidationReport"><code>{factor.validation_report_id}</code></Descriptions.Item>
        <Descriptions.Item label="Validation hash"><code>{factor.validation_report_hash}</code></Descriptions.Item>
        <Descriptions.Item label="Scientific gate"><Tag color="green">passed</Tag></Descriptions.Item>
        <Descriptions.Item label="Approval ID"><code>{factor.approval.approval_id}</code></Descriptions.Item>
        <Descriptions.Item label="Approval hash"><code>{factor.approval.approval_hash}</code></Descriptions.Item>
        <Descriptions.Item label="Scope"><Tag color="blue">{factor.approval.scope}</Tag></Descriptions.Item>
        <Descriptions.Item label="Decision"><Tag color="green">{factor.approval.decision}</Tag></Descriptions.Item>
        <Descriptions.Item label="Reviewer">{factor.approval.reviewer_id} · {factor.approval.reviewer_role}</Descriptions.Item>
        <Descriptions.Item label="Decided at">{factor.approval.decided_at}</Descriptions.Item>
        <Descriptions.Item label="Reason">{factor.approval.reason}</Descriptions.Item>
      </Descriptions>
    </article>
  )
}

export function AlphaModelReadinessPanel({ projection }: AlphaModelReadinessPanelProps) {
  if (projection.status === 'unavailable') {
    return (
      <section className="alphaReadinessPanel alphaReadinessPanel--unavailable">
        <Alert
          description="系统没有为视觉完整度注入模型。以下阻断来自服务端 readiness 投影。"
          showIcon
          title="Alpha Model 当前不可用"
          type="warning"
        />
        <div className="alphaReadinessContext">
          <Tag>{projection.data_mode}</Tag>
          <Tag>{projection.deployment_stage}</Tag>
          <Tag>{projection.requested_scope}</Tag>
          <span>Checked at {projection.checked_at}</span>
        </div>
        <div className="alphaBlockerList">
          {projection.blocked_reasons.map((blocker) => (
            <article key={`${blocker.code}:${blocker.affected_binding}`}>
              <header>
                <Tag color="error">{blocker.code}</Tag>
                <code>{blocker.affected_binding}</code>
              </header>
              <p>{blocker.reason}</p>
              <div>
                {blocker.evidence_ids.map((id) => <code key={id}>{id}</code>)}
              </div>
            </article>
          ))}
        </div>
      </section>
    )
  }

  return (
    <section className="alphaReadinessPanel" data-testid="approved-alpha-model">
      <header className="alphaReadyHeader">
        <div>
          <p>EXACT APPROVAL BINDINGS</p>
          <h2>Alpha Model 已满足当前用途</h2>
          <span>Checked at {projection.checked_at}</span>
        </div>
        <div>
          <Tag color="green">ready</Tag>
          <Tag color="blue">{projection.requested_scope}</Tag>
        </div>
      </header>
      <Alert
        className="alphaAuthorityNotice"
        showIcon
        title="该审批只授权声明的研究用途，不授予账户访问或下单权限。"
        type="info"
      />
      <Descriptions bordered className="alphaModelBinding" column={{ xs: 1, sm: 1, md: 2 }} size="small">
        <Descriptions.Item label="ModelVersion"><code>{projection.model.model_version_id}</code></Descriptions.Item>
        <Descriptions.Item label="CodeVersion"><code>{projection.model.code_version}</code></Descriptions.Item>
        <Descriptions.Item label="Model content hash" span={{ xs: 1, sm: 1, md: 2 }}><code>{projection.model.content_hash}</code></Descriptions.Item>
        <Descriptions.Item label="Data mode">{projection.data_mode}</Descriptions.Item>
        <Descriptions.Item label="Deployment stage">{projection.deployment_stage}</Descriptions.Item>
      </Descriptions>
      <div className="approvedFactorList">
        {projection.factors.map((factor) => (
          <ApprovedFactorCard factor={factor} key={factor.factor_version_id} />
        ))}
      </div>
    </section>
  )
}

export type { AlphaModelReadinessProjection } from './screenProjection'
