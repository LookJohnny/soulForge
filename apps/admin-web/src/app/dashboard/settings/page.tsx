"use client";

import { useState, useEffect } from "react";
import { Key, Copy, Trash2, Plus, Shield, BarChart3 } from "lucide-react";

interface ApiKeyInfo { id: string; name: string; prefix: string; lastUsedAt: string | null; expiresAt: string | null; revoked: boolean; createdAt: string; }

export default function SettingsPage() {
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyValue, setNewKeyValue] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function fetchKeys() { const res = await fetch("/api/api-keys"); if (res.ok) setKeys(await res.json()); }
  useEffect(() => { fetchKeys(); }, []);
  async function createKey() { setLoading(true); const res = await fetch("/api/api-keys", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: newKeyName || "New Key" }) }); if (res.ok) { const d = await res.json(); setNewKeyValue(d.key); setNewKeyName(""); fetchKeys(); } setLoading(false); }
  async function revokeKey(id: string) { await fetch("/api/api-keys", { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }) }); fetchKeys(); }

  return (
    <div className="space-y-8 max-w-3xl">
      <div>
        <h1 className="text-[26px] font-bold tracking-tight text-gold flex items-center gap-3">
          <Shield className="w-6 h-6 text-amber-400" />
          设置
        </h1>
        <p className="text-[13px] text-white/30 mt-1">API 密钥、许可证和用量</p>
      </div>

      {/* API Keys */}
      <section className="glass rounded-2xl p-6 animate-fade-in">
        <h2 className="text-[15px] font-semibold text-white/70 flex items-center gap-2 mb-5">
          <Key className="w-4 h-4 text-amber-400" /> API 密钥
        </h2>

        <div className="flex gap-2.5 mb-5">
          <input type="text" value={newKeyName} onChange={(e) => setNewKeyName(e.target.value)} placeholder="密钥名称..." className="input-dark flex-1 text-[13px]" />
          <button onClick={createKey} disabled={loading} className="btn-primary flex items-center gap-1.5 text-[13px]">
            <Plus className="w-3.5 h-3.5" /> 创建
          </button>
        </div>

        {newKeyValue && (
          <div className="mb-5 p-4 rounded-xl bg-emerald-500/5 border border-emerald-500/10 animate-scale-in">
            <p className="text-[12px] text-emerald-400/80 mb-2">密钥已创建，请立即复制：</p>
            <div className="flex items-center gap-2">
              <code className="text-[11px] text-emerald-300/80 bg-black/30 px-3 py-2 rounded-lg flex-1 font-mono break-all">{newKeyValue}</code>
              <button onClick={() => navigator.clipboard.writeText(newKeyValue)} className="p-2 text-emerald-400/60 hover:text-emerald-300 transition-colors"><Copy className="w-4 h-4" /></button>
            </div>
            <button onClick={() => setNewKeyValue(null)} className="mt-2 text-[11px] text-white/25 hover:text-white/40">已复制，关闭</button>
          </div>
        )}

        <div className="space-y-2">
          {keys.map((key) => (
            <div key={key.id} className={`flex items-center justify-between p-3.5 rounded-xl transition-all duration-300 ${key.revoked ? "bg-red-500/3 opacity-40" : "bg-white/[0.02] border border-white/[0.04]"}`}>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-[13px] text-white/70">{key.name}</span>
                  {key.revoked && <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-400/60">已撤销</span>}
                </div>
                <div className="text-[11px] text-white/20 mt-0.5 font-mono">{key.prefix}...</div>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-[11px] text-white/15">{new Date(key.createdAt).toLocaleDateString("zh-CN")}</span>
                {!key.revoked && <button onClick={() => revokeKey(key.id)} className="p-1 text-white/15 hover:text-red-400 transition-colors"><Trash2 className="w-3.5 h-3.5" /></button>}
              </div>
            </div>
          ))}
          {keys.length === 0 && <p className="text-[13px] text-white/20 text-center py-4">暂无密钥</p>}
        </div>
      </section>

      {/* License */}
      <section className="glass rounded-2xl p-6 animate-fade-in stagger-2">
        <h2 className="text-[15px] font-semibold text-white/70 flex items-center gap-2 mb-5">
          <BarChart3 className="w-4 h-4 text-amber-400" /> 许可证 & 用量
        </h2>
        <p className="text-[13px] text-white/30 mb-4">当前为免费版。升级以解锁更多配额。</p>
        <div className="grid grid-cols-3 gap-3">
          {[{ n: "3", l: "角色上限" }, { n: "10", l: "设备上限" }, { n: "100", l: "日对话上限" }].map((item) => (
            <div key={item.l} className="p-4 rounded-xl bg-white/[0.02] border border-white/[0.04] text-center">
              <div className="text-[22px] font-bold text-amber-400/80 tabular-nums">{item.n}</div>
              <div className="text-[11px] text-white/25 mt-0.5">{item.l}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
