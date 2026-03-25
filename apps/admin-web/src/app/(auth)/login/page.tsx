"use client";

import { useState } from "react";
import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import { Flame } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    const result = await signIn("credentials", {
      email,
      password,
      redirect: false,
    });

    setLoading(false);

    if (result?.error) {
      setError("邮箱或密码错误");
    } else {
      router.push("/dashboard/characters");
      router.refresh();
    }
  }

  return (
    <div className="min-h-screen bg-[#f5f5f7] flex items-center justify-center px-4">
      <div className="w-full max-w-[380px]">
        {/* Logo */}
        <div className="flex flex-col items-center mb-10 animate-fade-in">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center mb-5 shadow-lg">
            <Flame className="w-6 h-6 text-white" />
          </div>
          <h1 className="text-[28px] font-bold tracking-tight text-gray-900">
            SoulForge
          </h1>
          <p className="text-[14px] text-gray-400 mt-1">
            为角色注入灵魂的设计平台
          </p>
        </div>

        {/* Card */}
        <div className="rounded-2xl bg-white border border-gray-200/60 p-7 shadow-sm animate-scale-in">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-[13px] text-gray-500 mb-1.5 ml-0.5 font-medium">
                邮箱
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input-dark w-full"
                placeholder="you@example.com"
                required
              />
            </div>

            <div>
              <label className="block text-[13px] text-gray-500 mb-1.5 ml-0.5 font-medium">
                密码
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input-dark w-full"
                placeholder="••••••••"
                required
              />
            </div>

            {error && (
              <p className="text-[13px] text-red-500 text-center py-1">{error}</p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full mt-2"
            >
              {loading ? "登录中..." : "登录"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
