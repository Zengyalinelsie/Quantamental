import {
  AlertOutlined,
  AppstoreOutlined,
  BarChartOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  FundOutlined,
} from '@ant-design/icons'
import type { ReactNode } from 'react'

export interface PrimaryNavigationItem {
  path: string
  label: string
  icon: ReactNode
}

export const primaryNavigation: readonly PrimaryNavigationItem[] = [
  { path: '/desk', label: '今日工作台', icon: <AppstoreOutlined /> },
  { path: '/research', label: '研究', icon: <ExperimentOutlined /> },
  { path: '/factors', label: '因子', icon: <BarChartOutlined /> },
  { path: '/portfolios', label: '组合', icon: <FundOutlined /> },
  { path: '/monitoring', label: '监控', icon: <AlertOutlined /> },
  { path: '/system', label: '数据与管理', icon: <DatabaseOutlined /> },
] as const

export const workspaceDefinitions = {
  research: {
    title: '研究',
    description: '从历史股票池、证券证据与事件上下文建立可审计研究案例。',
    tabs: ['Universe & Screen', 'Security', 'Events', 'Watchlists/Cases'],
  },
  factors: {
    title: '因子',
    description: '登记实验、验证统计不确定性，并管理因子与模型生命周期。',
    tabs: ['Catalog', 'Alpha Model', 'Timing Lab', 'Experiments', 'Correlation Monitor', 'Production'],
  },
  portfolios: {
    title: '组合',
    description: '从获批信号构建目标组合，检查风险、情景与闭合归因。',
    tabs: ['Construction', 'Backtests', 'Risk', 'Scenarios', 'Attribution'],
  },
  monitoring: {
    title: '监控',
    description: '跟踪信号、组合、Timing、漂移、再平衡、执行与事件。',
    tabs: ['Signals', 'Portfolios', 'Timing', 'Drift', 'Rebalance', 'Execution', 'Incidents'],
  },
  system: {
    title: '数据与管理',
    description: '检查数据目录、质量、血缘、任务、授权、用户、Agent 与审批。',
    tabs: ['Catalog', 'Quality', 'Lineage', 'Jobs', 'Entitlements', 'Users', 'Agents', 'Approvals'],
  },
} as const
