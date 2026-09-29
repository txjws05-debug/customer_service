"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { AuthCard } from "@/components/auth/AuthCard";
import { FormField, inputBase, fieldState } from "@/components/auth/FormField";
import { PasswordInput } from "@/components/auth/PasswordInput";
import { authAPI } from "@/lib/api";
import { setToken, setUser } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [usernameError, setUsernameError] = useState("");
  const [passwordError, setPasswordError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    let ok = true;
    if (!username.trim()) {
      setUsernameError("请输入用户名");
      ok = false;
    } else {
      setUsernameError("");
    }
    if (!password) {
      setPasswordError("请输入密码");
      ok = false;
    } else {
      setPasswordError("");
    }
    if (!ok) return;

    setLoading(true);
    try {
      const data = await authAPI.login(username.trim(), password);
      setToken(data.access_token);
      setUser({ username: data.username });
      toast.success("登录成功");
      router.push("/chat");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthCard
      title="登录电商客服"
      subtitle="AI 智能客服系统"
      footer={
        <>
          还没有账号？
          <Link
            href="/register"
            className="text-indigo-300 underline hover:text-indigo-200"
          >
            立即注册
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        <FormField id="username" label="用户名" error={usernameError}>
          <input
            id="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className={`${inputBase} ${fieldState(!!usernameError)}`}
            placeholder="请输入用户名"
            autoComplete="username"
          />
        </FormField>

        <FormField id="password" label="密码" error={passwordError}>
          <PasswordInput
            id="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={fieldState(!!passwordError)}
            placeholder="请输入密码"
            autoComplete="current-password"
          />
        </FormField>

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-lg bg-indigo-600 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? "登录中..." : "登录"}
        </button>
      </form>
    </AuthCard>
  );
}
