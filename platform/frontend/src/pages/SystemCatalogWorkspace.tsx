import { Tabs } from 'antd'

import { SystemEvidenceScreen } from './SystemEvidenceScreen'
import { SystemScreen } from './SystemScreen'

export function SystemCatalogWorkspace() {
  return (
    <Tabs
      className="systemCatalogTabs"
      items={[
        { key: 'datasets', label: 'Dataset Versions', children: <SystemScreen section="catalog" /> },
        { key: 'financial-evidence', label: 'Financial Evidence', children: <SystemEvidenceScreen /> },
      ]}
    />
  )
}
