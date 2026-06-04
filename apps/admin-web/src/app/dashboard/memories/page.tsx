"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Brain,
  CheckCircle2,
  GitBranch,
  Loader2,
  RefreshCw,
  Search,
  Shield,
  ThumbsDown,
  Trash2,
} from "lucide-react";

type CharacterOption = {
  id: string;
  name: string;
  status: string;
};

type UserCandidate = {
  id: string;
  label: string | null;
  memoryCount: number;
  lastSeen: string | null;
};

type MemoryRow = {
  id: string;
  userId: string;
  characterId: string | null;
  tableName: string;
  memoryType: string;
  content: string;
  sensitivityLevel: string;
  permissionLevel: string;
  conflictStatus: string;
  confidenceScore: number;
  retrievalWeight: number;
  canSurfaceDirectly: boolean;
  implicitOnly: boolean;
  requiresConfirmation: boolean;
  usageCount: number;
  lastUsedAt: string | null;
  createdAt: string;
  updatedAt: string | null;
  enabled: boolean;
  relationAxis: string | null;
};

type MemoryPack = {
  direct: unknown[];
  implicit: unknown[];
  compiled_rules: unknown[];
  robot_behavior_hints: Record<string, unknown>;
  blocked_count: number;
  source: string;
};

const memoryTypeLabels: Record<string, string> = {
  PROFILE: "画像",
  EPISODIC: "事件",
  SEMANTIC: "语义",
  RELATIONAL: "关系",
  COMPILED_BEHAVIOR_RULE: "编译",
};

const typeColors: Record<string, string> = {
  PROFILE: "bg-blue-50 text-blue-600",
  EPISODIC: "bg-gray-100 text-gray-600",
  SEMANTIC: "bg-emerald-50 text-emerald-600",
  RELATIONAL: "bg-violet-50 text-violet-600",
  COMPILED_BEHAVIOR_RULE: "bg-amber-50 text-amber-600",
};

const sensitivityColors: Record<string, string> = {
  LOW: "bg-emerald-50 text-emerald-600",
  MEDIUM: "bg-amber-50 text-amber-600",
  HIGH: "bg-rose-50 text-rose-600",
  CRITICAL: "bg-red-100 text-red-700",
};

function formatDate(value: string | null) {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function shortId(id: string) {
  return id.slice(0, 8);
}

export default function MemoriesPage() {
  const [characters, setCharacters] = useState<CharacterOption[]>([]);
  const [users, setUsers] = useState<UserCandidate[]>([]);
  const [memories, setMemories] = useState<MemoryRow[]>([]);
  const [selectedCharacterId, setSelectedCharacterId] = useState("");
  const [selectedUserId, setSelectedUserId] = useState("");
  const [manualUserId, setManualUserId] = useState("");
  const [query, setQuery] = useState("创业方向怎么判断");
  const [newType, setNewType] = useState("RELATIONAL");
  const [newContent, setNewContent] = useState("");
  const [memoryPack, setMemoryPack] = useState<MemoryPack | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const activeUserId = manualUserId.trim() || selectedUserId;

  const stats = useMemo(() => {
    const byType = memories.reduce<Record<string, number>>((acc, item) => {
      acc[item.memoryType] = (acc[item.memoryType] || 0) + 1;
      return acc;
    }, {});
    return {
      total: memories.length,
      implicit: memories.filter((m) => m.implicitOnly).length,
      direct: memories.filter((m) => m.canSurfaceDirectly).length,
      compiled: byType.COMPILED_BEHAVIOR_RULE || 0,
    };
  }, [memories]);

  const loadMemories = useCallback(
    async (opts?: { characterId?: string; userId?: string }) => {
      setError(null);
      const characterId = opts?.characterId ?? selectedCharacterId;
      const userId = opts?.userId ?? activeUserId;
      const params = new URLSearchParams();
      if (characterId) params.set("characterId", characterId);
      if (userId) params.set("userId", userId);

      const res = await fetch(`/api/memories?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "加载失败");
      }

      setCharacters(data.characters || []);
      setUsers(data.users || []);
      setMemories(data.memories || []);

      const firstCharacter = data.characters?.[0]?.id || "";
      const firstUser = data.users?.[0]?.id || "";
      if (!selectedCharacterId && firstCharacter) {
        setSelectedCharacterId(firstCharacter);
      }
      if (!selectedUserId && firstUser && !manualUserId) {
        setSelectedUserId(firstUser);
      }
    },
    [activeUserId, manualUserId, selectedCharacterId, selectedUserId]
  );

  useEffect(() => {
    loadMemories()
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [loadMemories]);

  const refresh = async () => {
    setBusy("refresh");
    try {
      await loadMemories();
    } catch (err) {
      setError(err instanceof Error ? err.message : "刷新失败");
    } finally {
      setBusy(null);
    }
  };

  const retrievePack = async () => {
    if (!activeUserId || !selectedCharacterId) {
      setError("需要用户 ID 和角色");
      return;
    }
    setBusy("retrieve");
    setError(null);
    try {
      const res = await fetch("/api/memories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operation: "retrieve",
          user_id: activeUserId,
          character_id: selectedCharacterId,
          query,
          context: { user_mood: "neutral" },
          limit: 12,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || data.detail || "检索失败");
      setMemoryPack(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "检索失败");
    } finally {
      setBusy(null);
    }
  };

  const compile = async () => {
    if (!activeUserId || !selectedCharacterId) {
      setError("需要用户 ID 和角色");
      return;
    }
    setBusy("compile");
    setError(null);
    try {
      const res = await fetch("/api/memories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operation: "compile",
          user_id: activeUserId,
          character_id: selectedCharacterId,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || data.detail || "编译失败");
      await loadMemories();
      setMemoryPack((prev) => prev || null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "编译失败");
    } finally {
      setBusy(null);
    }
  };

  const createMemory = async () => {
    if (!activeUserId || !selectedCharacterId || !newContent.trim()) {
      setError("需要用户、角色和内容");
      return;
    }
    setBusy("create");
    setError(null);
    try {
      const res = await fetch("/api/memories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: activeUserId,
          character_id: selectedCharacterId,
          memory_type: newType,
          content: newContent.trim(),
          raw_source: { source: "admin_dashboard" },
          sensitivity_level: "LOW",
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || data.detail || "创建失败");
      setNewContent("");
      await loadMemories();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setBusy(null);
    }
  };

  const feedback = async (memoryId: string, value: "wrong" | "use_less" | "good") => {
    setBusy(memoryId);
    setError(null);
    try {
      const res = await fetch("/api/memories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          operation: "feedback",
          memory_id: memoryId,
          feedback: value,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || data.detail || "反馈失败");
      await loadMemories();
    } catch (err) {
      setError(err instanceof Error ? err.message : "反馈失败");
    } finally {
      setBusy(null);
    }
  };

  const deleteMemory = async (memoryId: string) => {
    setBusy(memoryId);
    setError(null);
    try {
      const res = await fetch(`/api/memories?memoryId=${memoryId}`, { method: "DELETE" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || data.detail || "删除失败");
      await loadMemories();
      if (memoryPack) {
        await retrievePack();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <div className="flex items-start justify-between mb-7">
        <div>
          <div className="flex items-center gap-3">
            <Brain className="w-6 h-6 text-blue-500" />
            <h1 className="text-[28px] font-bold tracking-tight text-gray-900">记忆</h1>
          </div>
          <p className="text-[14px] text-gray-400 mt-1">
            Profile / Episodic / Semantic / Relational / Policy
          </p>
        </div>
        <button
          onClick={refresh}
          className="inline-flex h-9 items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 text-gray-600 hover:bg-gray-50 disabled:opacity-50"
          disabled={busy === "refresh"}
        >
          {busy === "refresh" ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <RefreshCw className="w-4 h-4" />
          )}
          刷新
        </button>
      </div>

      {error && (
        <div className="mb-5 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-[13px] text-rose-600">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[320px_1fr] gap-5">
        <aside className="space-y-4">
          <section className="rounded-xl border border-gray-100 bg-white p-4">
            <div className="text-[12px] font-semibold text-gray-500 mb-3">上下文</div>
            <label className="block text-[11px] text-gray-400 mb-1">角色</label>
            <select
              value={selectedCharacterId}
              onChange={(e) => {
                setSelectedCharacterId(e.target.value);
                setMemoryPack(null);
                loadMemories({ characterId: e.target.value }).catch((err) =>
                  setError(err instanceof Error ? err.message : "加载失败")
                );
              }}
              className="w-full h-9 rounded-lg border border-gray-200 bg-white px-3 text-[13px] text-gray-700 outline-none focus:border-blue-300"
            >
              <option value="">选择角色</option>
              {characters.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} · {c.status}
                </option>
              ))}
            </select>

            <label className="block text-[11px] text-gray-400 mb-1 mt-3">用户</label>
            <select
              value={selectedUserId}
              onChange={(e) => {
                setSelectedUserId(e.target.value);
                setManualUserId("");
                setMemoryPack(null);
                loadMemories({ userId: e.target.value }).catch((err) =>
                  setError(err instanceof Error ? err.message : "加载失败")
                );
              }}
              className="w-full h-9 rounded-lg border border-gray-200 bg-white px-3 text-[13px] text-gray-700 outline-none focus:border-blue-300"
            >
              <option value="">选择用户</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.label || shortId(u.id)} · {u.memoryCount}
                </option>
              ))}
            </select>
            <input
              value={manualUserId}
              onChange={(e) => setManualUserId(e.target.value)}
              placeholder="手动输入用户 UUID"
              className="mt-2 w-full h-9 rounded-lg border border-gray-200 bg-white px-3 text-[12px] text-gray-700 outline-none focus:border-blue-300"
            />
          </section>

          <section className="rounded-xl border border-gray-100 bg-white p-4">
            <div className="text-[12px] font-semibold text-gray-500 mb-3">统计</div>
            <div className="grid grid-cols-2 gap-2">
              {[
                ["总数", stats.total],
                ["隐性", stats.implicit],
                ["可提", stats.direct],
                ["编译", stats.compiled],
              ].map(([label, value]) => (
                <div key={label} className="rounded-lg bg-gray-50 px-3 py-2">
                  <div className="text-[10px] text-gray-400">{label}</div>
                  <div className="text-[20px] font-semibold text-gray-900 tabular-nums">
                    {value}
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section className="rounded-xl border border-gray-100 bg-white p-4">
            <div className="text-[12px] font-semibold text-gray-500 mb-3">新增</div>
            <select
              value={newType}
              onChange={(e) => setNewType(e.target.value)}
              className="w-full h-9 rounded-lg border border-gray-200 bg-white px-3 text-[13px] text-gray-700 outline-none focus:border-blue-300"
            >
              <option value="PROFILE">画像</option>
              <option value="EPISODIC">事件</option>
              <option value="SEMANTIC">语义</option>
              <option value="RELATIONAL">关系</option>
            </select>
            <textarea
              value={newContent}
              onChange={(e) => setNewContent(e.target.value)}
              rows={4}
              placeholder="用户喜欢先结论后论证，不要空泛鼓励"
              className="mt-2 w-full resize-none rounded-lg border border-gray-200 bg-white px-3 py-2 text-[13px] text-gray-700 outline-none focus:border-blue-300"
            />
            <button
              onClick={createMemory}
              disabled={busy === "create"}
              className="mt-2 w-full btn-primary flex items-center justify-center gap-2 text-[13px]"
            >
              {busy === "create" ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <CheckCircle2 className="w-4 h-4" />
              )}
              保存
            </button>
          </section>

          <section className="rounded-xl border border-gray-100 bg-white p-4">
            <div className="text-[12px] font-semibold text-gray-500 mb-3">策略包</div>
            <div className="flex gap-2">
              <button
                onClick={retrievePack}
                disabled={busy === "retrieve"}
                className="flex-1 inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-gray-200 bg-white text-[12px] text-gray-600 hover:bg-gray-50 disabled:opacity-50"
              >
                {busy === "retrieve" ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Search className="w-4 h-4" />
                )}
                检索
              </button>
              <button
                onClick={compile}
                disabled={busy === "compile"}
                className="flex-1 inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-gray-200 bg-white text-[12px] text-gray-600 hover:bg-gray-50 disabled:opacity-50"
              >
                {busy === "compile" ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <GitBranch className="w-4 h-4" />
                )}
                编译
              </button>
            </div>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="mt-2 w-full h-9 rounded-lg border border-gray-200 bg-white px-3 text-[12px] text-gray-700 outline-none focus:border-blue-300"
            />
            {memoryPack && (
              <div className="mt-3 rounded-lg bg-gray-50 p-3 text-[11px] text-gray-500">
                <div className="grid grid-cols-4 gap-2 text-center">
                  <span>direct {memoryPack.direct.length}</span>
                  <span>implicit {memoryPack.implicit.length}</span>
                  <span>rules {memoryPack.compiled_rules.length}</span>
                  <span>blocked {memoryPack.blocked_count}</span>
                </div>
                <pre className="mt-2 max-h-28 overflow-auto whitespace-pre-wrap text-[10px] leading-relaxed">
                  {JSON.stringify(memoryPack.robot_behavior_hints, null, 2)}
                </pre>
              </div>
            )}
          </section>
        </aside>

        <main className="rounded-xl border border-gray-100 bg-white overflow-hidden">
          <div className="grid grid-cols-[120px_1fr_150px_120px_118px] items-center border-b border-gray-100 bg-gray-50 px-4 py-2 text-[11px] font-medium text-gray-400">
            <span>层级</span>
            <span>内容</span>
            <span>策略</span>
            <span>使用</span>
            <span className="text-right">操作</span>
          </div>

          {loading ? (
            <div className="flex h-64 items-center justify-center text-gray-400">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          ) : memories.length === 0 ? (
            <div className="flex h-64 flex-col items-center justify-center text-gray-400">
              <Shield className="w-9 h-9 mb-3 opacity-30" />
              <p className="text-[13px]">没有可显示的记忆</p>
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {memories.map((memory) => (
                <div
                  key={memory.id}
                  className="grid grid-cols-[120px_1fr_150px_120px_118px] gap-3 px-4 py-3 text-[13px]"
                >
                  <div>
                    <span
                      className={`inline-flex rounded-full px-2 py-1 text-[10px] font-medium ${
                        typeColors[memory.memoryType] || "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {memoryTypeLabels[memory.memoryType] || memory.memoryType}
                    </span>
                    {memory.relationAxis && (
                      <div className="mt-1 text-[10px] text-gray-400">
                        {memory.relationAxis}
                      </div>
                    )}
                  </div>

                  <div className="min-w-0">
                    <p className="text-gray-800 leading-relaxed">{memory.content}</p>
                    <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-gray-400">
                      <span>{shortId(memory.id)}</span>
                      <span>{memory.tableName}</span>
                      <span>{formatDate(memory.updatedAt || memory.createdAt)}</span>
                    </div>
                  </div>

                  <div className="space-y-1">
                    <span
                      className={`inline-flex rounded-full px-2 py-1 text-[10px] font-medium ${
                        sensitivityColors[memory.sensitivityLevel] || "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {memory.sensitivityLevel}
                    </span>
                    <div className="text-[10px] text-gray-400">
                      {memory.implicitOnly ? "implicit" : "surface"} ·{" "}
                      {memory.permissionLevel}
                    </div>
                  </div>

                  <div className="text-[11px] text-gray-500">
                    <div>conf {memory.confidenceScore.toFixed(2)}</div>
                    <div>used {memory.usageCount}</div>
                    <div>{formatDate(memory.lastUsedAt)}</div>
                  </div>

                  <div className="flex items-start justify-end gap-1">
                    <button
                      onClick={() => feedback(memory.id, "use_less")}
                      disabled={busy === memory.id}
                      className="h-8 w-8 rounded-lg border border-gray-100 text-gray-400 hover:text-amber-600 hover:border-amber-200"
                      title="降低使用"
                    >
                      <ThumbsDown className="mx-auto w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => deleteMemory(memory.id)}
                      disabled={busy === memory.id}
                      className="h-8 w-8 rounded-lg border border-gray-100 text-gray-400 hover:text-rose-600 hover:border-rose-200"
                      title="删除"
                    >
                      {busy === memory.id ? (
                        <Loader2 className="mx-auto w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Trash2 className="mx-auto w-3.5 h-3.5" />
                      )}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
