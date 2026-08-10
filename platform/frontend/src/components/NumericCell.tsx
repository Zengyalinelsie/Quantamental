interface NumericCellProps {
  value: number | null | undefined
  precision?: number
  suffix?: string
  unavailableReason?: string
}

export function NumericCell({
  value,
  precision = 2,
  suffix = '',
  unavailableReason = '缺少权威数据',
}: NumericCellProps) {
  if (value == null || !Number.isFinite(value)) {
    return (
      <span
        aria-label={`不可用：${unavailableReason}`}
        className="numericCell numericCell--missing"
      >
        —
      </span>
    )
  }
  const formatted = new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  }).format(value)
  return <span className="numericCell">{formatted}{suffix}</span>
}
