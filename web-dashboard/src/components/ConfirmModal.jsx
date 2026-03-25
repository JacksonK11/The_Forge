import { useEffect } from "react";

export default function ConfirmModal({
  isOpen,
  title,
  message,
  confirmText = "Confirm",
  cancelText = "Cancel",
  onConfirm,
  onCancel,
  danger = false,
}) {
  // Close on Escape key
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e) => {
      if (e.key === "Escape") onCancel?.();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isOpen, onCancel]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel?.();
      }}
    >
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 max-w-sm w-full mx-4 shadow-2xl">
        {title && (
          <h3 className="text-white font-['Bebas_Neue'] text-xl tracking-widest mb-3">
            {title}
          </h3>
        )}
        {message && (
          <p className="text-gray-400 text-sm leading-relaxed mb-6">{message}</p>
        )}
        <div className="flex items-center gap-3 justify-end">
          <button
            onClick={onCancel}
            className="rounded-lg font-medium px-4 py-2.5 transition-all duration-200 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm"
          >
            {cancelText}
          </button>
          <button
            onClick={onConfirm}
            className={`rounded-lg font-medium px-4 py-2.5 transition-all duration-200 text-white text-sm ${
              danger
                ? "bg-red-600 hover:bg-red-500"
                : "bg-purple-600 hover:bg-purple-500"
            }`}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
