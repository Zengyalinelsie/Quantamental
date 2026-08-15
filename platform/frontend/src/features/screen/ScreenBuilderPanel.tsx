import { Tag } from 'antd'

import type { ScreenRankingProjection } from './screenProjection'

interface ScreenBuilderPanelProps {
  /** Null when no qualified frozen screen exists. */
  projection: ScreenRankingProjection | null
}

/**
 * The prototype's Screen builder, as a read-only projection of a frozen screen.
 *
 * Per ADR-0012 this panel reports which universe, factor versions, model version
 * and approval scope the frozen screen actually used.  It offers no weight
 * inputs and no run action: those would produce a ranking with no definition
 * version, no Run record and no approval scope, and with the P4 factor gate
 * unpassed there are no qualified factors to re-rank with.  The editable
 * scratch/governed split arrives after P4.
 *
 * When no screen is bound, the panel says so.  It never falls back to the
 * prototype's sample weights (40/30/30), coverage (96.3%) or liquidity
 * threshold (> 5000 万 CNY) — those are DESIGN FIXTURE values.
 */
export function ScreenBuilderPanel({ projection }: ScreenBuilderPanelProps) {
  return (
    <section aria-label="Screen 构建器" className="screenBuilderPanel">
      <header className="screenBuilderPanel__header">
        <h2>Screen 构建器 / Factor Builder</h2>
        <p>
          以下参数为该 Screen 运行时的
          <strong>已冻结</strong>
          绑定，供审计核对，不可在此编辑。
        </p>
      </header>
      {projection === null
        ? (
          <p className="screenBuilderPanel__unavailable" role="status">
            当前没有合格的冻结 Screen，因此没有可展示的股票池、因子版本或审批绑定。
          </p>
        )
        : (
          <dl className="screenBuilderPanel__fields">
            <div className="screenBuilderField">
              <dt>股票池范围</dt>
              <dd>
                <span className="screenBuilderField__value">
                  {projection.universe.display_name}
                </span>
                <code>{projection.universe.universe_version_id}</code>
              </dd>
            </div>
            <div className="screenBuilderField">
              <dt>股票池规模</dt>
              <dd>
                <span className="screenBuilderField__value">
                  {projection.universe.universe_size}
                </span>
              </dd>
            </div>
            <div className="screenBuilderField">
              <dt>参与打分的因子版本</dt>
              <dd className="screenBuilderField__list">
                {projection.factor_version_ids.map((item) => (
                  <code key={item}>{item}</code>
                ))}
              </dd>
            </div>
            <div className="screenBuilderField">
              <dt>模型版本</dt>
              <dd><code>{projection.model_version_id}</code></dd>
            </div>
            <div className="screenBuilderField">
              <dt>审批用途</dt>
              <dd><Tag>{projection.approval_scope}</Tag></dd>
            </div>
            <div className="screenBuilderField">
              <dt>输入可信状态</dt>
              <dd><Tag>{projection.trust_state}</Tag></dd>
            </div>
            <div className="screenBuilderField">
              <dt>决策时点 / 数据截止</dt>
              <dd className="screenBuilderField__list">
                <code>{projection.decision_time}</code>
                <code>{projection.data_cutoff}</code>
              </dd>
            </div>
            <div className="screenBuilderField">
              <dt>特征与数据版本</dt>
              <dd className="screenBuilderField__list">
                {[...projection.feature_version_ids, ...projection.dataset_version_ids]
                  .map((item) => <code key={item}>{item}</code>)}
              </dd>
            </div>
          </dl>
        )}
    </section>
  )
}
