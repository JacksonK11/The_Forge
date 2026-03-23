import React, { useState } from 'react';

const PRIMARY_TABS = [
  {
    id: 'build',
    label: 'Build',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
      </svg>
    ),
  },
  {
    id: 'results',
    label: 'Results',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" />
      </svg>
    ),
  },
  {
    id: 'chat',
    label: 'Chat',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" />
      </svg>
    ),
  },
  {
    id: 'files',
    label: 'Files',
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
      </svg>
    ),
  },
];

const MORE_TABS = [
  { id: 'update', label: 'Update', emoji: '↻' },
  { id: 'memory', label: 'Memory', emoji: '💡' },
  { id: 'overview', label: 'Overview', emoji: '◻' },
  { id: 'pipeline', label: 'Pipeline', emoji: '⚡' },
  { id: 'architecture', label: 'Architecture', emoji: '⊞' },
];

export default function MobileNav({ activeTab, onTabChange }) {
  const [showMore, setShowMore] = useState(false);

  const moreIsActive = MORE_TABS.some((t) => t.id === activeTab);

  function handleTabChange(id) {
    onTabChange(id);
    setShowMore(false);
  }

  return (
    <>
      {/* More drawer overlay */}
      {showMore && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 40,
            backgroundColor: 'rgba(0,0,0,0.5)',
          }}
          onClick={() => setShowMore(false)}
        >
          <div
            style={{
              position: 'absolute',
              bottom: 'calc(72px + env(safe-area-inset-bottom, 0px))',
              left: 0,
              right: 0,
              backgroundColor: '#0f0b1a',
              borderTop: '1px solid rgba(107, 33, 168, 0.4)',
              borderRadius: '16px 16px 0 0',
              padding: '12px 0',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              style={{
                width: '36px',
                height: '4px',
                backgroundColor: '#4b3a6e',
                borderRadius: '2px',
                margin: '0 auto 12px',
              }}
            />
            {MORE_TABS.map((tab) => {
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => handleTabChange(tab.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '16px',
                    width: '100%',
                    padding: '14px 24px',
                    backgroundColor: isActive ? 'rgba(107, 33, 168, 0.2)' : 'transparent',
                    border: 'none',
                    color: isActive ? '#c084fc' : '#9ca3af',
                    fontSize: '16px',
                    fontWeight: isActive ? 600 : 400,
                    textAlign: 'left',
                    cursor: 'pointer',
                  }}
                >
                  <span style={{ fontSize: '18px', width: '24px', textAlign: 'center' }}>{tab.emoji}</span>
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Bottom nav bar */}
      <nav
        style={{
          position: 'fixed',
          bottom: 0,
          left: 0,
          right: 0,
          zIndex: 50,
          backgroundColor: 'rgba(15, 11, 26, 0.95)',
          backdropFilter: 'blur(16px)',
          WebkitBackdropFilter: 'blur(16px)',
          borderTop: '1px solid rgba(107, 33, 168, 0.3)',
          paddingBottom: 'env(safe-area-inset-bottom, 0px)',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-around',
            height: '64px',
            paddingLeft: '4px',
            paddingRight: '4px',
          }}
        >
          {PRIMARY_TABS.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => handleTabChange(tab.id)}
                style={{
                  position: 'relative',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  minWidth: '44px',
                  minHeight: '44px',
                  padding: '4px 8px',
                  borderRadius: '12px',
                  border: 'none',
                  backgroundColor: isActive ? 'rgba(107, 33, 168, 0.15)' : 'transparent',
                  color: isActive ? '#c084fc' : '#6b7280',
                  cursor: 'pointer',
                  flexShrink: 0,
                  flex: 1,
                }}
                aria-label={tab.label}
                aria-current={isActive ? 'page' : undefined}
              >
                {isActive && (
                  <span
                    style={{
                      position: 'absolute',
                      top: '-1px',
                      left: '50%',
                      transform: 'translateX(-50%)',
                      width: '32px',
                      height: '3px',
                      borderRadius: '2px',
                      backgroundColor: '#9333ea',
                      boxShadow: '0 0 8px rgba(147,51,234,0.6)',
                    }}
                  />
                )}
                <span
                  style={{
                    transform: isActive ? 'scale(1.1)' : 'scale(1)',
                    transition: 'transform 0.2s',
                    display: 'flex',
                  }}
                >
                  {tab.icon}
                </span>
                <span
                  style={{
                    fontSize: '10px',
                    marginTop: '2px',
                    fontWeight: isActive ? 600 : 400,
                    lineHeight: 1.2,
                  }}
                >
                  {tab.label}
                </span>
              </button>
            );
          })}

          {/* More button */}
          <button
            onClick={() => setShowMore(!showMore)}
            style={{
              position: 'relative',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              minWidth: '44px',
              minHeight: '44px',
              padding: '4px 8px',
              borderRadius: '12px',
              border: 'none',
              backgroundColor: (showMore || moreIsActive) ? 'rgba(107, 33, 168, 0.15)' : 'transparent',
              color: (showMore || moreIsActive) ? '#c084fc' : '#6b7280',
              cursor: 'pointer',
              flex: 1,
            }}
            aria-label="More"
          >
            {(showMore || moreIsActive) && (
              <span
                style={{
                  position: 'absolute',
                  top: '-1px',
                  left: '50%',
                  transform: 'translateX(-50%)',
                  width: '32px',
                  height: '3px',
                  borderRadius: '2px',
                  backgroundColor: '#9333ea',
                  boxShadow: '0 0 8px rgba(147,51,234,0.6)',
                }}
              />
            )}
            <svg
              xmlns="http://www.w3.org/2000/svg"
              style={{ width: '24px', height: '24px', transform: showMore ? 'rotate(180deg)' : 'rotate(0)', transition: 'transform 0.2s' }}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 12a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm6.75 0a.75.75 0 11-1.5 0 .75.75 0 011.5 0zm6.75 0a.75.75 0 11-1.5 0 .75.75 0 011.5 0z" />
            </svg>
            <span
              style={{
                fontSize: '10px',
                marginTop: '2px',
                fontWeight: (showMore || moreIsActive) ? 600 : 400,
                lineHeight: 1.2,
              }}
            >
              More
            </span>
          </button>
        </div>
      </nav>
    </>
  );
}
