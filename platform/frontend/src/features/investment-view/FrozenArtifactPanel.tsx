import { useQuery } from '@tanstack/react-query'
import { Button, Descriptions, Tag } from 'antd'

import { getArtifactMetadata, getIdentity } from '../../api/client'
import './investmentViewSummary.less'

interface FrozenArtifactPanelProps {
  artifactId: string | null
}

function ArtifactState({
  detail,
  status,
  title,
}: {
  detail: string
  status: 'empty' | 'loading' | 'error' | 'restricted'
  title: string
}) {
  return (
    <section aria-label="Frozen Artifact" className={`frozenArtifactPanel frozenArtifactPanel--${status}`}>
      <header>
        <div>
          <p>IMMUTABLE EXPORT</p>
          <h3>{title}</h3>
        </div>
        <Tag>{status}</Tag>
      </header>
      <p className="frozenArtifactPanel__detail">{detail}</p>
      {status === 'restricted' ? <Button disabled>下载不可变产物</Button> : null}
    </section>
  )
}

export function FrozenArtifactPanel({ artifactId }: FrozenArtifactPanelProps) {
  const identityQuery = useQuery({
    enabled: artifactId !== null,
    queryKey: ['identity', 'artifact-access'],
    queryFn: ({ signal }) => getIdentity(signal),
  })
  const identityPermissions = identityQuery.data?.data.permissions
  const hasPermissionContract = Array.isArray(identityPermissions)
  const canReadArtifact = hasPermissionContract && identityPermissions.includes('read_artifact')
  const metadataQuery = useQuery({
    enabled: artifactId !== null && canReadArtifact,
    queryKey: ['artifact-metadata', artifactId],
    queryFn: ({ signal }) => getArtifactMetadata(artifactId!, signal),
  })

  if (artifactId === null) {
    return (
      <ArtifactState
        detail="服务端没有绑定 Artifact ID；页面不会复用 InvestmentView ID 或构造下载地址。"
        status="empty"
        title="Frozen Artifact 尚未生成"
      />
    )
  }
  if (identityQuery.isLoading) {
    return (
      <ArtifactState
        detail="正在从服务端读取当前主体及 read_artifact 权限。"
        status="loading"
        title="正在验证 Frozen Artifact 权限"
      />
    )
  }
  if (identityQuery.isError) {
    return (
      <ArtifactState
        detail={String(identityQuery.error)}
        status="error"
        title="Frozen Artifact 权限读取失败"
      />
    )
  }
  if (!canReadArtifact) {
    return (
      <ArtifactState
        detail={hasPermissionContract
          ? `主体 ${identityQuery.data?.data.subject_id ?? 'unknown'} 未授予 read_artifact；下载保持禁用。`
          : 'Identity 响应缺少 permissions 合同；下载失败关闭。'}
        status="restricted"
        title="Frozen Artifact 下载受限"
      />
    )
  }
  if (metadataQuery.isLoading) {
    return (
      <ArtifactState
        detail={`正在校验 ${artifactId} 的治理记录与 producer run。`}
        status="loading"
        title="正在读取 Frozen Artifact 元数据"
      />
    )
  }
  if (metadataQuery.isError || !metadataQuery.data) {
    return (
      <ArtifactState
        detail={String(metadataQuery.error ?? 'API 未返回 Artifact metadata Envelope')}
        status="error"
        title="Frozen Artifact 元数据读取失败"
      />
    )
  }

  const artifact = metadataQuery.data.data
  if (artifact.artifact_id !== artifactId) {
    return (
      <ArtifactState
        detail={`返回的 Artifact ID 与请求不一致：requested=${artifactId}; returned=${artifact.artifact_id}。下载保持禁用。`}
        status="error"
        title="Frozen Artifact 身份校验失败"
      />
    )
  }
  return (
    <section aria-label="Frozen Artifact" className="frozenArtifactPanel frozenArtifactPanel--ready">
      <header>
        <div>
          <p>IMMUTABLE EXPORT</p>
          <h3>Frozen Artifact 已验证</h3>
        </div>
        <div className="frozenArtifactPanel__actions">
          <Tag color="green">READ ARTIFACT</Tag>
          <Button
            href={`/api/artifacts/${encodeURIComponent(artifact.artifact_id)}/download`}
            type="primary"
          >
            下载不可变产物
          </Button>
        </div>
      </header>
      <Descriptions bordered column={{ xs: 1, sm: 1, md: 2 }} size="small">
        <Descriptions.Item label="Artifact"><code>{artifact.artifact_id}</code></Descriptions.Item>
        <Descriptions.Item label="Run"><code>{artifact.run_id}</code></Descriptions.Item>
        <Descriptions.Item label="Content hash" span={{ xs: 1, sm: 1, md: 2 }}>
          <code>{artifact.content_hash}</code>
        </Descriptions.Item>
        <Descriptions.Item label="Media type">{artifact.media_type}</Descriptions.Item>
        <Descriptions.Item label="Created at">{artifact.created_at}</Descriptions.Item>
        <Descriptions.Item label="Data mode">{artifact.producer_context.data_mode}</Descriptions.Item>
        <Descriptions.Item label="Deployment stage">
          {artifact.producer_context.deployment_stage}
        </Descriptions.Item>
      </Descriptions>
    </section>
  )
}
