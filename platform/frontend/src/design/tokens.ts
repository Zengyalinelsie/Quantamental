import type { ThemeConfig } from 'antd'

export const tokens = {
  primary: '#2F5EA8',
  primaryHover: '#244C8A',
  layout: '#F3F5F7',
  container: '#FFFFFF',
  elevated: '#F7F8FA',
  subtle: '#ECEFF3',
  border: '#C8CDD4',
  secondaryBorder: '#DEE2E7',
  text: '#18202A',
  secondaryText: '#4E5968',
  tertiaryText: '#727D8B',
  borderRadius: 3,
} as const

export const semanticColors = {
  dataQuality: {
    verified: '#287A55',
    current: '#9A6A16',
    raw: '#687383',
    blocked: '#687383',
  },
  approval: {
    approved: '#315F9B',
    pending: '#8A651A',
    rejected: '#8E4A57',
  },
  market: {
    rise: '#A64045',
    fall: '#2E7660',
    flat: '#687383',
  },
  severity: {
    low: '#687383',
    information: '#315F9B',
    warning: '#8A651A',
    critical: '#A14B3D',
  },
} as const

export const theme: ThemeConfig = {
  token: {
    colorPrimary: tokens.primary,
    colorPrimaryHover: tokens.primaryHover,
    colorBgLayout: tokens.layout,
    colorBgContainer: tokens.container,
    colorBorder: tokens.border,
    colorBorderSecondary: tokens.secondaryBorder,
    colorText: tokens.text,
    colorTextSecondary: tokens.secondaryText,
    borderRadius: tokens.borderRadius,
    boxShadow: 'none',
    boxShadowSecondary: 'none',
    fontFamily: 'PingFang SC, ui-sans-serif, system-ui, sans-serif',
  },
  components: {
    Card: { boxShadow: 'none' },
    Table: {
      cellPaddingBlock: 8,
      cellPaddingInline: 10,
      headerBg: tokens.elevated,
      headerColor: tokens.secondaryText,
      rowHoverBg: '#F5F8FC',
    },
    Menu: {
      itemBorderRadius: 2,
      itemHeight: 40,
      itemMarginInline: 8,
    },
  },
}
