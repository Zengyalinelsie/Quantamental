import { MenuFoldOutlined, MenuUnfoldOutlined, SearchOutlined } from '@ant-design/icons'
import { Button, Drawer, Input, Layout, Menu, Tag, Tooltip } from 'antd'
import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import { primaryNavigation, workspaceDefinitions } from '../navigation/routes'
import { WorkspaceState } from '../components/WorkspaceState'
import { useWorkspaceStore } from '../state/workspace'

const { Header, Sider, Content } = Layout
const DeskPage = lazy(() => import('../pages/DeskPage').then((module) => ({ default: module.DeskPage })))
const WorkspacePage = lazy(() => import('../pages/WorkspacePage').then((module) => ({ default: module.WorkspacePage })))

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brand ${compact ? 'brand--compact' : ''}`}>
      <span className="brand__mark">FQ</span>
      {compact ? null : (
        <span className="brand__copy">
          <strong>Fundamental Quant</strong>
          <small>基本面量化研究平台</small>
        </span>
      )}
    </div>
  )
}

function NavigationMenu({ onNavigate }: { onNavigate?: () => void }) {
  const location = useLocation()
  const navigate = useNavigate()
  const selected = primaryNavigation.find(({ path }) => location.pathname.startsWith(path))?.path
    ?? '/desk'
  return (
    <Menu
      aria-label="一级导航"
      mode="inline"
      selectedKeys={[selected]}
      items={primaryNavigation.map(({ path, label, icon }) => ({ key: path, label, icon }))}
      onClick={({ key }) => {
        navigate(key)
        onNavigate?.()
      }}
    />
  )
}

function RouteWorkspace({ definition }: { definition: (typeof workspaceDefinitions)[keyof typeof workspaceDefinitions] }) {
  return <WorkspacePage {...definition} />
}

export function AppShell() {
  const desktopCollapsed = useWorkspaceStore((state) => state.desktopCollapsed)
  const mobileDrawerOpen = useWorkspaceStore((state) => state.mobileDrawerOpen)
  const securityQuery = useWorkspaceStore((state) => state.securityQuery)
  const setDesktopCollapsed = useWorkspaceStore((state) => state.setDesktopCollapsed)
  const setMobileDrawerOpen = useWorkspaceStore((state) => state.setMobileDrawerOpen)
  const setSecurityQuery = useWorkspaceStore((state) => state.setSecurityQuery)

  return (
    <Layout className="appShell">
      <Sider
        className="desktopSider"
        collapsed={desktopCollapsed}
        collapsedWidth={72}
        trigger={null}
        width={280}
      >
        <Brand compact={desktopCollapsed} />
        <NavigationMenu />
        <div className="siderFooter">
          <Tooltip title={desktopCollapsed ? '展开侧栏' : '收起侧栏'} placement="right">
            <Button
              aria-label={desktopCollapsed ? '展开侧栏' : '收起侧栏'}
              block
              icon={desktopCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setDesktopCollapsed(!desktopCollapsed)}
              type="text"
            >
              {desktopCollapsed ? null : '收起导航'}
            </Button>
          </Tooltip>
        </div>
      </Sider>

      <Drawer
        className="mobileNavigationDrawer"
        closable
        onClose={() => setMobileDrawerOpen(false)}
        open={mobileDrawerOpen}
        placement="left"
        size={280}
        title={<Brand />}
      >
        <NavigationMenu onNavigate={() => setMobileDrawerOpen(false)} />
      </Drawer>

      <Layout className="mainLayout">
        <Header className="globalHeader">
          <Button
            aria-label="打开移动导航"
            className="mobileMenuButton"
            icon={<MenuUnfoldOutlined />}
            onClick={() => setMobileDrawerOpen(true)}
            type="text"
          />
          <Input
            allowClear
            aria-label="全局证券搜索"
            className="securitySearch"
            onChange={(event) => setSecurityQuery(event.target.value)}
            placeholder="证券代码 / 公司名称（不默认选择）"
            prefix={<SearchOutlined aria-hidden />}
            role="searchbox"
            value={securityQuery}
          />
          <div aria-label="运行上下文" className="runContext">
            <span className="contextItem">
              <small>DATA MODE</small>
              <Tag>current_research</Tag>
            </span>
            <span className="contextItem">
              <small>DEPLOYMENT</small>
              <Tag color="blue">research</Tag>
            </span>
            <span className="contextItem contextItem--scope">
              <small>UNIVERSE</small>
              <strong>未选择</strong>
            </span>
            <span className="contextItem contextItem--scope">
              <small>PORTFOLIO</small>
              <strong>未选择</strong>
            </span>
            <span className="contextItem contextItem--time">
              <small>AS OF</small>
              <strong>未选择</strong>
            </span>
            <span className="contextItem contextItem--time">
              <small>SYSTEM AS OF</small>
              <strong>API 未连接</strong>
            </span>
            <Tag className="environmentTag">DEV · READ ONLY</Tag>
          </div>
        </Header>
        <Content className="appContent">
          <Suspense fallback={<WorkspaceState state="loading" reason="正在加载研究工作区" />}>
            <Routes>
              <Route path="/desk" element={<DeskPage />} />
              <Route path="/research" element={<RouteWorkspace definition={workspaceDefinitions.research} />} />
              <Route path="/factors" element={<RouteWorkspace definition={workspaceDefinitions.factors} />} />
              <Route path="/portfolios" element={<RouteWorkspace definition={workspaceDefinitions.portfolios} />} />
              <Route path="/monitoring" element={<RouteWorkspace definition={workspaceDefinitions.monitoring} />} />
              <Route path="/system" element={<RouteWorkspace definition={workspaceDefinitions.system} />} />
              <Route path="/dashboard" element={<Navigate replace to="/desk" />} />
              <Route path="/reports" element={<Navigate replace to="/desk" />} />
              <Route path="*" element={<Navigate replace to="/desk" />} />
            </Routes>
          </Suspense>
        </Content>
      </Layout>
    </Layout>
  )
}
