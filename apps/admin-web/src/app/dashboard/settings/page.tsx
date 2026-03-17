"use client";

import { useState, useEffect } from "react";
import { Key, Copy, Trash2, Plus, Shield, BarChart3 } from "lucide-react";

interface ApiKeyInfo {
  id: string;
  name: string;
  prefix: string;
  lastUsedAt: string | null;
  expiresAt: string | null;
  revoked: boolean;
  createdAt: string;
}

export default function SettingsPage() {
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyValue, setNewKeyValue] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function fetchKeys() {
    const res = await fetch("/api/api-keys");
    if (res.ok) setKeys(await res.json());
  }

  useEffect(() => {
    fetchKeys();
  }, []);

  async function createKey() {
    setLoading(true);
    const res = await fetch("/api/api-keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newKeyName || "New Key" }),
    });
    if (res.ok) {
      const data = await res.json();
      setNewKeyValue(data.key);
      setNewKeyName("");
      fetchKeys();
    }
    setLoading(false);
  }

  async function revokeKey(id: string) {
    await fetch("/api/api-keys", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    fetchKeys();
  }

  function copyToClipboard(text: string) {
    navigator.clipboard.writeText(text);
  }

  return (
    <div className="space-y-8 max-w-4xl">
      <div>
        <h1 className="text-2xl font-bold rune-text flex items-center gap-3">
          <Shield className="w-6 h-6 text-amber-400" />
          圣殿设置
        </h1>
        <p className="text-sm text-amber-600/40 mt-1">神印密钥、神圣契约与用量铭牌</p>
      </div>

      {/* API Keys Section */}
      <section className="glass rounded-2xl p-6">
        <h2 className="text-lg font-semibold text-amber-200/80 flex items-center gap-2 mb-4">
          <Key className="w-5 h-5 text-amber-400" />
          神印密钥
        </h2>

        {/* Create Key */}
        <div className="flex gap-3 mb-6">
          <input
            type="text"
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
            placeholder="密钥铭文..."
            className="input-dark flex-1"
          />
          <button
            onClick={createKey}
            disabled={loading}
            className="btn-primary flex items-center gap-2 text-sm"
          >
            <Plus className="w-4 h-4" />
            铸造密钥
          </button>
        </div>

        {/* New key display */}
        {newKeyValue && (
          <div className="mb-6 p-4 rounded-xl bg-amber-600/10 border border-amber-600/20">
            <p className="text-sm text-amber-400 mb-2">
              密钥已锻铸。请立即抄录，此后将不再显现：
            </p>
            <div className="flex items-center gap-2">
              <code className="text-xs text-amber-300 bg-black/30 px-3 py-2 rounded-lg flex-1 font-mono break-all">
                {newKeyValue}
              </code>
              <button
                onClick={() => copyToClipboard(newKeyValue)}
                className="p-2 text-amber-400 hover:text-amber-300 transition-colors"
              >
                <Copy className="w-4 h-4" />
              </button>
            </div>
            <button
              onClick={() => setNewKeyValue(null)}
              className="mt-2 text-xs text-amber-600/40 hover:text-amber-500"
            >
              已抄录，关闭
            </button>
          </div>
        )}

        {/* Keys List */}
        <div className="space-y-3">
          {keys.map((key) => (
            <div
              key={key.id}
              className={`flex items-center justify-between p-4 rounded-xl border ${
                key.revoked
                  ? "bg-red-500/5 border-red-900/10 opacity-50"
                  : "bg-amber-900/5 border-amber-800/10"
              }`}
            >
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-amber-200/80">{key.name}</span>
                  {key.revoked && (
                    <span className="text-xs px-2 py-0.5 rounded bg-red-500/15 text-red-400/70">
                      已封印
                    </span>
                  )}
                </div>
                <div className="text-xs text-amber-700/30 mt-1 font-mono">
                  {key.prefix}...
                </div>
              </div>
              <div className="flex items-center gap-4">
                <span className="text-xs text-amber-700/30">
                  {new Date(key.createdAt).toLocaleDateString("zh-CN")}
                </span>
                {!key.revoked && (
                  <button
                    onClick={() => revokeKey(key.id)}
                    className="p-1.5 text-amber-700/20 hover:text-red-400 transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>
          ))}
          {keys.length === 0 && (
            <p className="text-sm text-amber-600/30 text-center py-4">
              尚未铸造任何密钥
            </p>
          )}
        </div>
      </section>

      {/* License Section */}
      <section className="glass rounded-2xl p-6">
        <h2 className="text-lg font-semibold text-amber-200/80 flex items-center gap-2 mb-4">
          <BarChart3 className="w-5 h-5 text-amber-400" />
          神圣契约 & 用量
        </h2>
        <p className="text-sm text-amber-600/40">
          当前为凡人契约。升阶以解锁更多灵魂、神器和对话配额。
        </p>
        <div className="grid grid-cols-3 gap-4 mt-4">
          <div className="p-4 rounded-xl bg-amber-900/5 border border-amber-800/10 text-center">
            <div className="text-2xl font-bold text-amber-400">3</div>
            <div className="text-xs text-amber-600/40 mt-1">灵魂上限</div>
          </div>
          <div className="p-4 rounded-xl bg-amber-900/5 border border-amber-800/10 text-center">
            <div className="text-2xl font-bold text-amber-400">10</div>
            <div className="text-xs text-amber-600/40 mt-1">神器上限</div>
          </div>
          <div className="p-4 rounded-xl bg-amber-900/5 border border-amber-800/10 text-center">
            <div className="text-2xl font-bold text-amber-400">100</div>
            <div className="text-xs text-amber-600/40 mt-1">日对话上限</div>
          </div>
        </div>
      </section>
    </div>
  );
}
