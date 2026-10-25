"use client";

import { createContext, type ReactNode, useCallback, useContext, useMemo, useState } from "react";

interface Toast {
  id: number;
  message: string;
  tone: "neutral" | "error";
  action?: { label: string; onClick: () => void };
}

type ShowToast = (
  message: string,
  options?: { tone?: Toast["tone"]; action?: Toast["action"] },
) => void;

const ToastContext = createContext<ShowToast>(() => undefined);

export function useToast(): ShowToast {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const show = useCallback<ShowToast>((message, options) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current.slice(-2), { id, message, tone: "neutral", ...options }]);
    window.setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), 6000);
  }, []);
  const value = useMemo(() => show, [show]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed inset-x-0 bottom-4 z-50 flex flex-col items-center gap-2 px-4"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`rise-in pointer-events-auto flex items-center gap-3 rounded-xl px-4 py-2.5 text-sm shadow-[var(--shadow-card)] ${
              toast.tone === "error" ? "bg-danger text-white" : "bg-ink text-white"
            }`}
          >
            <span>{toast.message}</span>
            {toast.action ? (
              <button
                type="button"
                onClick={() => {
                  toast.action?.onClick();
                  setToasts((current) => current.filter((t) => t.id !== toast.id));
                }}
                className="font-semibold text-lavender-wash underline-offset-2 hover:underline"
              >
                {toast.action.label}
              </button>
            ) : null}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
