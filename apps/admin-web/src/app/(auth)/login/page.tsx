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
    <div className="min-h-screen bg-cosmic flex items-center justify-center px-4 relative overflow-hidden">
      {/* Floating gradient orbs — Apple-style */}
      <div className="orb w-[500px] h-[500px] bg-amber-600/30 top-[-15%] left-[20%] animate-blob" />
      <div className="orb w-[400px] h-[400px] bg-amber-800/20 bottom-[-10%] right-[15%] animate-blob" style={{ animationDelay: "-4s" }} />
      <div className="orb w-[300px] h-[300px] bg-orange-900/15 top-[40%] right-[5%] animate-blob" style={{ animationDelay: "-8s" }} />

      <div className="w-full max-w-[380px] relative z-10">
        {/* Logo */}
        <div className="flex flex-col items-center mb-12 animate-fade-in">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-amber-400 to-amber-700 flex items-center justify-center mb-5 shadow-xl shadow-amber-900/25">
            <Flame className="w-6 h-6 text-white" />
          </div>
          <h1 className="text-[28px] font-bold tracking-tight text-shimmer">
            SoulForge
          </h1>
          <p className="text-[13px] text-white/25 mt-1">
            为角色注入灵魂的设计平台
          </p>
        </div>

        {/* Card */}
        <div className="rounded-2xl bg-white/[0.03] border border-white/[0.06] p-7 backdrop-blur-2xl animate-scale-in shadow-2xl shadow-black/20">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-[12px] text-white/40 mb-1.5 ml-0.5 font-medium">
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
              <label className="block text-[12px] text-white/40 mb-1.5 ml-0.5 font-medium">
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
              <p className="text-[13px] text-red-400/80 text-center py-1">{error}</p>
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
