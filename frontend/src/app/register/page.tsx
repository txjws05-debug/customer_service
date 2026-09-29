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

export default function RegisterPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [usernameError, setUsernameError] = useState("");
  const [passwordError, setPasswordError] = useState("");
  const [confirmError, setConfirmError] = useState("");

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
    if (confirm !== password) {
      setConfirmError("两次输入的密码不一致");
      ok = false;
    } else {
      setConfirmError("");
    }
    if (!ok) return;

    setLoading(true);
    try {
      // 注册成功后端直接返回 token，前端自动登录
      const data = await authAPI.register(username.trim(), password);
      setToken(data.access_token);
      setUser({ username: data.username });
      toast.success("注册成功，已自动登录");
      router.push("/chat");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "注册失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthCard
      title="注册账号"
      subtitle="创建你的电商客服账号"
      footer={
        <>
          已有账号？
          <Link
            href="/login"
            className="text-indigo-300 underline hover:text-indigo-200"
          >
            返回登录
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
            autoComplete="new-password"
          />
        </FormField>

        <FormField id="confirm" label="确认密码" error={confirmError}>
          <PasswordInput
            id="confirm"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className={fieldState(!!confirmError)}
            placeholder="请再次输入密码"
            autoComplete="new-password"
          />
        </FormField>

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-lg bg-indigo-600 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? "注册中..." : "注册"}
        </button>
      </form>
    </AuthCard>
  );
}
