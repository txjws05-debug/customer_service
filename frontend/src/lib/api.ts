// Token 统一由 lib/auth 管理（单一来源，键名为 cs_token）。
// 此前本文件自行读写 access_token，与登录页写入的 cs_token 不一致，
// 导致登录成功后所有请求都缺少 Authorization 头、直接 401。
import { getToken, removeToken, setToken } from "./auth";

// 生产环境：构建时置空 NEXT_PUBLIC_API_BASE，使用相对路径 + 反向代理；
// 本地开发未配置时回退到后端默认端口。
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:18082";

export { getToken, setToken };
export const clearToken = removeToken;

export interface ChatObject {
  type: string;
  id: string;
  title?: string | null;
  attributes?: Record<string, string>;
}

async function request(path: string, options: RequestInit = {}) {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = `请求失败（${res.status}）`;
    try {
      const data = await res.json();
      if (data?.detail) detail = data.detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export function register(username: string, password: string) {
  return request("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function login(username: string, password: string) {
  return request("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

// 登录 / 注册页使用
export const authAPI = { login, register };

export async function streamChat(
  payload: { text?: string; object?: ChatObject },
  signal?: AbortSignal,
): Promise<ReadableStream<Uint8Array>> {
  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
    },
    body: JSON.stringify(payload),
    signal,
  });
  if (!res.ok) {
    let detail = `请求失败（${res.status}）`;
    try {
      const data = await res.json();
      if (data?.detail) detail = data.detail;
    } catch {}
    throw new Error(detail);
  }
  return res.body!;
}

export function fetchHistory() {
  return request("/api/chat/history", { method: "POST" });
}
