"use client";

import useSWR, { SWRConfiguration, mutate as globalMutate } from "swr";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : (detail as { message?: string })?.message || `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
  }
}

export async function api<T = any>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(path, {
    method: init.method || (init.body ? "POST" : "GET"),
    headers: init.body ? { "content-type": "application/json" } : undefined,
    body: init.body ? JSON.stringify(init.body) : undefined,
    credentials: "include",
  });
  if (res.status === 401 && typeof window !== "undefined" && !path.includes("/auth/")) {
    window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
  }
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) throw new ApiError(res.status, (data as any)?.detail ?? data);
  return data as T;
}

function safeJson(t: string) {
  try {
    return JSON.parse(t);
  } catch {
    return t;
  }
}

export function useApi<T = any>(path: string | null, opts?: SWRConfiguration) {
  return useSWR<T>(path, (p: string) => api<T>(p), { revalidateOnFocus: false, keepPreviousData: true, ...opts });
}

export const refresh = (key: string | ((k: string) => boolean)) =>
  typeof key === "string" ? globalMutate(key) : globalMutate((k) => typeof k === "string" && key(k));
