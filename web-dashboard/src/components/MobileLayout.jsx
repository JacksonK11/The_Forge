import React from 'react';
import MobileNav from './MobileNav';

const HEADER_HEIGHT = 52;
const NAV_HEIGHT = 72;

// Tabs whose content manages its own scroll (fixed input bar, etc.)
const FULL_HEIGHT_TABS = new Set(['chat', 'results']);

export default function MobileLayout({
  activeTab,
  setActiveTab,
  tabs,
  children,
  tabContent,
}) {
  const activeTabObj = tabs.find((t) => (t.key || t.id || t) === activeTab);
  const activeLabel = activeTabObj
    ? activeTabObj.label || activeTabObj.name || activeTab
    : activeTab;

  const isFullHeight = FULL_HEIGHT_TABS.has(activeTab);

  const renderContent = () => {
    if (tabContent && typeof tabContent === 'function') {
      return tabContent(activeTab);
    }
    if (tabContent && typeof tabContent === 'object') {
      return tabContent[activeTab] || null;
    }
    return children || null;
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        backgroundColor: '#08061A',
        color: '#e2e8f0',
      }}
    >
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <header
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 100,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingLeft: '16px',
          paddingRight: '16px',
          paddingTop: 'env(safe-area-inset-top, 0px)',
          height: `calc(${HEADER_HEIGHT}px + env(safe-area-inset-top, 0px))`,
          backgroundColor: 'rgba(8, 6, 26, 0.9)',
          backdropFilter: 'blur(10px)',
          WebkitBackdropFilter: 'blur(10px)',
          borderBottom: '1px solid rgba(107, 33, 168, 0.3)',
        }}
      >
        <span
          style={{
            fontSize: '18px',
            fontWeight: 700,
            background: 'linear-gradient(135deg, #a855f7, #7c3aed)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            backgroundClip: 'text',
          }}
        >
          ⚒ The Forge
        </span>
        <span
          style={{
            fontSize: '13px',
            color: '#a78bfa',
            fontWeight: 500,
            textTransform: 'capitalize',
          }}
        >
          {activeLabel}
        </span>
      </header>

      {/* ── Content ────────────────────────────────────────────────────── */}
      <main
        style={{
          position: 'fixed',
          top: `calc(${HEADER_HEIGHT}px + env(safe-area-inset-top, 0px))`,
          bottom: `calc(${NAV_HEIGHT}px + env(safe-area-inset-bottom, 0px))`,
          left: 0,
          right: 0,
          overflowY: isFullHeight ? 'hidden' : 'auto',
          overflowX: 'hidden',
          WebkitOverflowScrolling: 'touch',
          backgroundColor: '#08061A',
        }}
      >
        <div
          style={{
            padding: isFullHeight ? 0 : '16px 12px 16px',
            height: isFullHeight ? '100%' : 'auto',
            boxSizing: 'border-box',
          }}
        >
          {renderContent()}
        </div>
      </main>

      {/* ── Bottom nav ─────────────────────────────────────────────────── */}
      <MobileNav
        activeTab={activeTab}
        onTabChange={setActiveTab}
      />
    </div>
  );
}
