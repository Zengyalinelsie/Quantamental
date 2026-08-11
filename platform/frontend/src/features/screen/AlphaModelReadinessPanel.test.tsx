import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { AlphaModelReadinessPanel } from './AlphaModelReadinessPanel'
import type { AlphaModelReadinessProjection } from './screenProjection'

const unavailable: AlphaModelReadinessProjection = {
  status: 'unavailable',
  requested_scope: 'research_backtest',
  data_mode: 'strict_historical',
  deployment_stage: 'research',
  checked_at: '2026-08-11T08:05:00Z',
  blocked_reasons: [
    {
      code: 'NO_APPROVED_FACTOR_VERSION',
      reason: '三个候选因子均未通过真实 PIT 截面资格门。',
      affected_binding: 'factor-version:*',
      evidence_ids: ['artifact:p4-factor-qualification:failed:v1'],
    },
    {
      code: 'NO_APPROVED_MODEL_VERSION',
      reason: '不存在与当前用途一致的获批 ModelVersion。',
      affected_binding: 'model-version:*',
      evidence_ids: ['validation-report:p4:failed:v1'],
    },
  ],
}

const ready: AlphaModelReadinessProjection = {
  status: 'ready',
  requested_scope: 'research_backtest',
  data_mode: 'strict_historical',
  deployment_stage: 'research',
  checked_at: '2026-08-11T08:05:00Z',
  model: {
    model_version_id: 'expected-return-compiler:v0',
    code_version: '1'.repeat(40),
    content_hash: 'a'.repeat(64),
  },
  factors: [
    {
      factor_version_id: 'factor-version:quality:v1',
      factor_version_hash: 'b'.repeat(64),
      lifecycle_status: 'production',
      review_id: 'approval:quality:research-backtest:v1',
      review_hash: 'c'.repeat(64),
      validation_report_id: 'validation-report:quality:v1',
      validation_report_hash: 'd'.repeat(64),
      scientific_gate_passed: true,
      approval: {
        approval_id: 'approval:quality:research-backtest:v1',
        approval_hash: 'e'.repeat(64),
        scope: 'research_backtest',
        decision: 'approved',
        reviewer_id: 'user:reviewer-01',
        reviewer_role: 'reviewer',
        decided_at: '2026-08-11T07:30:00Z',
        reason: '只批准冻结研究回测用途。',
      },
    },
  ],
}

describe('AlphaModelReadinessPanel', () => {
  afterEach(cleanup)

  it('shows a professional unavailable state with every server blocker and no demo model', () => {
    render(<AlphaModelReadinessPanel projection={unavailable} />)

    expect(screen.getByRole('alert')).toHaveTextContent('Alpha Model 当前不可用')
    expect(screen.getByText('NO_APPROVED_FACTOR_VERSION')).toBeInTheDocument()
    expect(screen.getByText(/候选因子均未通过真实 PIT/)).toBeInTheDocument()
    expect(screen.getByText('NO_APPROVED_MODEL_VERSION')).toBeInTheDocument()
    expect(screen.getByText('artifact:p4-factor-qualification:failed:v1')).toBeInTheDocument()
    expect(screen.queryByText(/示例|demo|Demo/)).not.toBeInTheDocument()
    expect(screen.queryByTestId('approved-alpha-model')).not.toBeInTheDocument()
  })

  it('renders exact model factor review and reviewer approval scope when ready', () => {
    render(<AlphaModelReadinessPanel projection={ready} />)

    const panel = screen.getByTestId('approved-alpha-model')
    expect(within(panel).getByText('expected-return-compiler:v0')).toBeInTheDocument()
    expect(within(panel).getByText('factor-version:quality:v1')).toBeInTheDocument()
    expect(within(panel).getByText('validation-report:quality:v1')).toBeInTheDocument()
    expect(within(panel).getAllByText('approval:quality:research-backtest:v1')).toHaveLength(2)
    expect(within(panel).getByText('user:reviewer-01 · reviewer')).toBeInTheDocument()
    expect(within(panel).getAllByText('research_backtest').length).toBeGreaterThan(0)
    expect(within(panel).getByText('只批准冻结研究回测用途。')).toBeInTheDocument()
  })

  it('states that approval scope grants neither account nor order authority', () => {
    render(<AlphaModelReadinessPanel projection={ready} />)

    expect(screen.getByText(/不授予账户访问或下单权限/)).toBeInTheDocument()
  })
})
