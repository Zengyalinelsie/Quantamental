import { Empty, Tag } from 'antd'

import type {
  CatalystProjection,
  InvestmentEvidenceProjection,
  InvalidatorProjection,
} from './investmentViewProjection'

interface InvestmentEvidencePanelProps {
  catalysts: CatalystProjection[]
  evidence: InvestmentEvidenceProjection[]
  invalidators: InvalidatorProjection[]
}

function EvidenceReferences({ ids }: { ids: string[] }) {
  if (ids.length === 0) return <span className="evidenceReferences--empty">未绑定证据</span>
  return (
    <span className="evidenceReferences">
      {ids.map((id) => <code key={id}>{id}</code>)}
    </span>
  )
}

export function InvestmentEvidencePanel({
  catalysts,
  evidence,
  invalidators,
}: InvestmentEvidencePanelProps) {
  return (
    <section aria-labelledby="evidence-heading" className="investmentViewSection">
      <header className="investmentViewSection__heading">
        <div>
          <p className="investmentViewSection__eyebrow">EVIDENCE BINDINGS</p>
          <h3 id="evidence-heading">催化、失效条件与证据</h3>
        </div>
      </header>
      <div className="investmentThesisGrid">
        <section aria-labelledby="catalyst-heading" className="investmentThesisColumn">
          <h4 id="catalyst-heading">Catalysts</h4>
          {catalysts.length === 0 ? <Empty description="未绑定催化剂" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
            <ul>
              {catalysts.map((catalyst) => (
                <li key={catalyst.catalyst_id}>
                  <strong>{catalyst.summary}</strong>
                  <span>{catalyst.horizon}</span>
                  <EvidenceReferences ids={catalyst.evidence_ids} />
                </li>
              ))}
            </ul>
          )}
        </section>
        <section aria-labelledby="invalidator-heading" className="investmentThesisColumn investmentThesisColumn--invalidators">
          <h4 id="invalidator-heading">Invalidators</h4>
          {invalidators.length === 0 ? <Empty description="未绑定失效条件" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
            <ul>
              {invalidators.map((invalidator) => (
                <li key={invalidator.invalidator_id}>
                  <strong>{invalidator.summary}</strong>
                  <EvidenceReferences ids={invalidator.evidence_ids} />
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <div className="evidenceLedger">
        <h4>Evidence ledger</h4>
        {evidence.length === 0 ? <Empty description="未绑定证据" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : (
          <ul>
            {evidence.map((item) => (
              <li key={item.evidence_id}>
                <div>
                  {item.source_url ? (
                    <a href={item.source_url} rel="noreferrer" target="_blank">{item.title}</a>
                  ) : <strong>{item.title}</strong>}
                  <code>{item.evidence_id}</code>
                </div>
                <div>
                  <Tag>{item.source_kind}</Tag>
                  <span>{item.available_at}</span>
                  <code>{item.version}</code>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
