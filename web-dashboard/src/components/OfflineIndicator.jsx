import { useState, useEffect } from "react";
import { useToast } from "../context/ToastContext.jsx";

export default function OfflineIndicator() {
  const [isOffline, setIsOffline] = useState(!navigator.onLine);
  const { addToast } = useToast();
  const wasOfflineRef = { current: !navigator.onLine };

  useEffect(() => {
    const handleOffline = () => {
      setIsOffline(true);
      wasOfflineRef.current = true;
    };

    const handleOnline = () => {
      setIsOffline(false);
      if (wasOfflineRef.current) {
        addToast("Back online", "success", 4000);
        wasOfflineRef.current = false;
      }
    };

    window.addEventListener("offline", handleOffline);
    window.addEventListener("online", handleOnline);

    return () => {
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("online", handleOnline);
    };
  }, [addToast]);

  if (!isOffline) return null;

  return (
    <div className="fixed top-0 inset-x-0 z-50 bg-amber-900 text-amber-200 text-sm py-2 text-center flex items-center justify-center gap-2">
      <svg className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M18.364 5.636a9 9 0 010 12.728M15.536 8.464a5 5 0 010 7.072M3 3l18 18M10.828 10.828A3 3 0 0012 8.07M6.343 6.343A8 8 0 005.07 12" />
      </svg>
      <span>You are offline — changes will not be saved</span>
    </div>
  );
}
