"use client";

import { useState } from "react";
import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import { Eye } from "lucide-react";

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
      setError("凭证不符，圣殿拒绝了你的请求");
    } else {
      router.push("/dashboard/characters");
      router.refresh();
    }
  }

  return (
    <div className="min-h-screen bg-cosmic flex items-center justify-center px-4 relative overflow-hidden">
      {/* Sacred geometry background circles */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div className="w-[600px] h-[600px] rounded-full border border-amber-800/8 animate-halo" />
        <div className="absolute w-[450px] h-[450px] rounded-full border border-amber-700/6" style={{ animationDirection: "reverse", animation: "halo-rotate 30s linear infinite reverse" }} />
        <div className="absolute w-[300px] h-[300px] rounded-full border border-amber-600/5 animate-halo" style={{ animationDuration: "25s" }} />
      </div>

      <div className="w-full max-w-sm relative z-10">
        {/* Sacred eye logo */}
        <div className="flex flex-col items-center mb-10">
          <div className="w-16 h-16 rounded-full bg-gradient-to-br from-amber-600/80 to-amber-900/80 flex items-center justify-center mb-4 animate-candle shadow-lg shadow-amber-900/30">
            <Eye className="w-7 h-7 text-amber-200" />
          </div>
          <span className="text-2xl font-bold rune-text tracking-wider">
            SoulForge
          </span>
          <p className="text-xs text-amber-700/50 mt-1 italic tracking-widest">
            ANIMAE OFFICINA
          </p>
        </div>

        {/* Card — ancient scroll */}
        <div className="glass rounded-2xl p-8 glow-purple">
          <h1 className="text-xl font-semibold text-amber-200/90 mb-1 text-center">
            步入圣殿
          </h1>
          <p className="text-sm text-amber-600/40 mb-8 text-center">
            以你的凭证开启灵魂锻造之门
          </p>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-xs text-amber-400/40 mb-2 ml-1 tracking-wider uppercase">
                铭文信箱
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input-dark w-full"
                placeholder="forger@soulforge.ai"
                required
              />
            </div>

            <div>
              <label className="block text-xs text-amber-400/40 mb-2 ml-1 tracking-wider uppercase">
                秘钥
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
              <p className="text-sm text-red-400/80 text-center">{error}</p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full text-sm"
            >
              {loading ? "验证神印中..." : "开启圣殿"}
            </button>
          </form>
        </div>

        <p className="text-xs text-amber-800/30 text-center mt-6 italic">
          以神圣之火锻铸灵魂
        </p>
      </div>
    </div>
  );
}
