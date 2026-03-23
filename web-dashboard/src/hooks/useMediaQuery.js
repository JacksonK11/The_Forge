import { useState, useEffect, useCallback } from 'react';

/**
 * Custom hook that tracks whether a CSS media query matches.
 * Uses window.matchMedia for efficient, reactive viewport detection.
 *
 * @param {string} query - A CSS media query string, e.g. "(max-width: 768px)"
 * @returns {boolean} Whether the media query currently matches
 */
export function useMediaQuery(query) {
  const getMatches = useCallback((q) => {
    if (typeof window === 'undefined') {
      return false;
    }
    return window.matchMedia(q).matches;
  }, []);

  const [matches, setMatches] = useState(() => getMatches(query));

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    const mediaQueryList = window.matchMedia(query);

    const handleChange = (event) => {
      setMatches(event.matches);
    };

    // Set initial value in case it changed between render and effect
    setMatches(mediaQueryList.matches);

    // Modern browsers support addEventListener on MediaQueryList
    if (mediaQueryList.addEventListener) {
      mediaQueryList.addEventListener('change', handleChange);
      return () => {
        mediaQueryList.removeEventListener('change', handleChange);
      };
    } else {
      // Fallback for older browsers (Safari < 14)
      mediaQueryList.addListener(handleChange);
      return () => {
        mediaQueryList.removeListener(handleChange);
      };
    }
  }, [query]);

  return matches;
}

/**
 * Convenience hook that returns true when the viewport width is less than 768px.
 * Uses the same breakpoint as Tailwind's `md:` prefix.
 *
 * @returns {boolean} Whether the current viewport is mobile-sized (< 768px)
 */
export function useIsMobile() {
  return useMediaQuery('(max-width: 767px)');
}

/**
 * Convenience hook that returns true when the viewport width is less than 1024px.
 * Useful for tablet-specific layouts.
 *
 * @returns {boolean} Whether the current viewport is tablet-sized or smaller (< 1024px)
 */
export function useIsTablet() {
  return useMediaQuery('(max-width: 1023px)');
}

export default useMediaQuery;