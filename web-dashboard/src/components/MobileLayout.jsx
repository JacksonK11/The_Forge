import React, { useState, useRef, useCallback, useEffect } from 'react';
import MobileNav from './MobileNav';

const SWIPE_THRESHOLD = 50;
const SWIPE_VELOCITY_THRESHOLD = 0.3;
const BOTTOM_NAV_HEIGHT = 72;

export default function MobileLayout({
  activeTab,
  setActiveTab,
  tabs,
  children,
  tabContent,
}) {
  const [touchStart, setTouchStart] = useState(null);
  const [touchEnd, setTouchEnd] = useState(null);
  const [touchStartTime, setTouchStartTime] = useState(null);
  const [swiping, setSwiping] = useState(false);
  const [swipeOffset, setSwipeOffset] = useState(0);
  const contentRef = useRef(null);

  const tabKeys = tabs.map((t) => t.key || t.id || t);

  const currentIndex = tabKeys.indexOf(activeTab);

  const handleTouchStart = useCallback((e) => {
    const touch = e.targetTouches[0];
    setTouchStart(touch.clientX);
    setTouchEnd(null);
    setTouchStartTime(Date.now());
    setSwiping(true);
    setSwipeOffset(0);
  }, []);

  const handleTouchMove = useCallback(
    (e) => {
      if (!touchStart) return;
      const touch = e.targetTouches[0];
      setTouchEnd(touch.clientX);
      const diff = touch.clientX - touchStart;

      const atFirstTab = currentIndex === 0 && diff > 0;
      const atLastTab = currentIndex === tabKeys.length - 1 && diff < 0;

      if (atFirstTab || atLastTab) {
        setSwipeOffset(diff * 0.2);
      } else {
        setSwipeOffset(diff * 0.4);
      }
    },
    [touchStart, currentIndex, tabKeys.length]
  );

  const handleTouchEnd = useCallback(() => {
    if (!touchStart || !touchEnd) {
      setSwiping(false);
      setSwipeOffset(0);
      return;
    }

    const distance = touchStart - touchEnd;
    const elapsed = Date.now() - (touchStartTime || Date.now());
    const velocity = Math.abs(distance) / elapsed;

    const isSignificantSwipe =
      Math.abs(distance) > SWIPE_THRESHOLD || velocity > SWIPE_VELOCITY_THRESHOLD;

    if (isSignificantSwipe) {
      if (distance > 0 && currentIndex < tabKeys.length - 1) {
        setActiveTab(tabKeys[currentIndex + 1]);
      } else if (distance < 0 && currentIndex > 0) {
        setActiveTab(tabKeys[currentIndex - 1]);
      }
    }

    setTouchStart(null);
    setTouchEnd(null);
    setTouchStartTime(null);
    setSwiping(false);
    setSwipeOffset(0);
  }, [touchStart, touchEnd, touchStartTime, currentIndex, tabKeys, setActiveTab]);

  useEffect(() => {
    setSwipeOffset(0);
    setSwiping(false);
  }, [activeTab]);

  const activeTabObj = tabs.find((t) => (t.key || t.id || t) === activeTab);
  const activeLabel = activeTabObj
    ? activeTabObj.label || activeTabObj.name || activeTab
    : activeTab;

  const FULL_HEIGHT_TABS = new Set(['chat', 'results']);
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
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        width: '100vw',
        overflow: 'hidden',
        backgroundColor: '#08061A',
        color: '#e2e8f0',
        position: 'relative',
      }}
    >
      {/* Header */}
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 16px',
          paddingTop: 'max(12px, env(safe-area-inset-top))',
          backgroundColor: 'rgba(107, 33, 168, 0.15)',
          borderBottom: '1px solid rgba(107, 33, 168, 0.3)',
          flexShrink: 0,
          minHeight: '48px',
          backdropFilter: 'blur(10px)',
          WebkitBackdropFilter: 'blur(10px)',
          zIndex: 10,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span
            style={{
              fontSize: '20px',
              fontWeight: 700,
              background: 'linear-gradient(135deg, #a855f7, #7c3aed)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              backgroundClip: 'text',
            }}
          >
            ⚒ The Forge
          </span>
        </div>
        <span
          style={{
            fontSize: '14px',
            color: '#a78bfa',
            fontWeight: 500,
            textTransform: 'capitalize',
          }}
        >
          {activeLabel}
        </span>
      </header>

      {/* Content area */}
      <main
        ref={contentRef}
        onTouchStart={isFullHeight ? undefined : handleTouchStart}
        onTouchMove={isFullHeight ? undefined : handleTouchMove}
        onTouchEnd={isFullHeight ? undefined : handleTouchEnd}
        style={{
          flex: 1,
          overflowY: isFullHeight ? 'hidden' : 'auto',
          overflowX: 'hidden',
          paddingBottom: isFullHeight ? '0' : `${BOTTOM_NAV_HEIGHT + 16}px`,
          paddingLeft: isFullHeight ? '0' : '12px',
          paddingRight: isFullHeight ? '0' : '12px',
          paddingTop: isFullHeight ? '0' : '12px',
          WebkitOverflowScrolling: 'touch',
          transform: swiping ? `translateX(${swipeOffset}px)` : 'translateX(0)',
          transition: swiping ? 'none' : 'transform 0.25s ease-out',
          willChange: 'transform',
          minHeight: 0,
        }}
      >
        <div
          style={{
            maxWidth: '100%',
            margin: '0 auto',
            height: isFullHeight ? '100%' : 'auto',
          }}
        >
          {renderContent()}
        </div>
      </main>

      {/* Bottom navigation */}
      <MobileNav
        tabs={tabs}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        height={BOTTOM_NAV_HEIGHT}
      />
    </div>
  );
}