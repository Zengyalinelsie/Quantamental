import { Descriptions, Drawer, Tag } from 'antd'

interface EvidenceDrawerProps {
  open: boolean
  onClose: () => void
  title: string
  status: 'unavailable' | 'normalized_current' | 'pit_verified'
  reason: string
}

const statusLabels = {
  unavailable: '不可用',
  normalized_current: '当前研究数据',
  pit_verified: 'PIT 已验证',
} as const

export function EvidenceDrawer({ open, onClose, title, status, reason }: EvidenceDrawerProps) {
  return (
    <Drawer open={open} onClose={onClose} size={420} title={title}>
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="状态">
          <Tag>{statusLabels[status]}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label="说明">{reason}</Descriptions.Item>
        <Descriptions.Item label="证据版本">尚无已发布 Artifact</Descriptions.Item>
      </Descriptions>
    </Drawer>
  )
}
