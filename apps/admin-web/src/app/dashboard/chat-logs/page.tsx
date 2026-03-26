"use client";

import { useState, useEffect } from "react";
import { MessageCircle, ChevronLeft, Clock, User, Bot } from "lucide-react";

interface Conversation {
  visitorId: string;
  characterId: string;
  characterName: string;
  messageCount: number;
  firstAt: string;
  lastAt: string;
}

interface ChatMsg {
  id: string;
  role: string;
  content: string;
  action: string | null;
  thought: string | null;
  emotion: string | null;
  createdAt: string;
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  return `${days} 天前`;
}

function formatTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString("zh-CN", {
    month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
    hour12: false,
  });
}

export default function ChatLogsPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<{ visitorId: string; characterId: string; characterName: string } | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMsgs, setLoadingMsgs] = useState(false);

  useEffect(() => {
    fetch("/api/chat-logs")
      .then((r) => r.json())
      .then((d) => setConversations(d.conversations || []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const openConversation = async (c: Conversation) => {
    setSelected({ visitorId: c.visitorId, characterId: c.characterId, characterName: c.characterName });
    setLoadingMsgs(true);
    try {
      const r = await fetch(`/api/chat-logs?visitor=${c.visitorId}&character=${c.characterId}`);
      const d = await r.json();
      setMessages(d.messages || []);
    } catch {
      setMessages([]);
    } finally {
      setLoadingMsgs(false);
    }
  };

  // ── Conversation list view ──
  if (!selected) {
    return (
      <div>
        <div className="flex items-center gap-3 mb-6">
          <MessageCircle className="w-6 h-6 text-blue-500" />
          <h1 className="text-xl font-semibold text-gray-900">聊天记录</h1>
          <span className="text-sm text-gray-400 ml-2">
            {loading ? "加载中..." : `${conversations.length} 个会话`}
          </span>
        </div>

        {!loading && conversations.length === 0 && (
          <div className="text-center py-20 text-gray-400">
            <MessageCircle className="w-12 h-12 mx-auto mb-3 opacity-30" />
            <p>还没有聊天记录</p>
          </div>
        )}

        <div className="space-y-2">
          {conversations.map((c) => (
            <button
              key={`${c.visitorId}-${c.characterId}`}
              onClick={() => openConversation(c)}
              className="w-full flex items-center gap-4 p-4 bg-white rounded-xl border border-gray-100 hover:border-blue-200 hover:shadow-sm transition-all text-left"
            >
              <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-400 to-blue-600 flex items-center justify-center text-white text-sm font-bold flex-shrink-0">
                {c.characterName[0]}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-900 text-sm">{c.characterName}</span>
                  <span className="text-xs text-gray-400 bg-gray-50 px-1.5 py-0.5 rounded">
                    {c.messageCount} 条
                  </span>
                </div>
                <div className="text-xs text-gray-400 mt-0.5 truncate">
                  访客 {c.visitorId.slice(0, 8)}...
                </div>
              </div>
              <div className="text-right flex-shrink-0">
                <div className="text-xs text-gray-400">{timeAgo(c.lastAt)}</div>
              </div>
            </button>
          ))}
        </div>
      </div>
    );
  }

  // ── Conversation detail view ──
  return (
    <div>
      <button
        onClick={() => { setSelected(null); setMessages([]); }}
        className="flex items-center gap-1 text-sm text-blue-500 hover:text-blue-700 mb-4"
      >
        <ChevronLeft className="w-4 h-4" />
        返回列表
      </button>

      <div className="flex items-center gap-3 mb-6">
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-400 to-blue-600 flex items-center justify-center text-white text-xs font-bold">
          {selected.characterName[0]}
        </div>
        <div>
          <h2 className="text-lg font-semibold text-gray-900">{selected.characterName}</h2>
          <p className="text-xs text-gray-400">访客 {selected.visitorId.slice(0, 12)}...</p>
        </div>
      </div>

      {loadingMsgs && <p className="text-sm text-gray-400 py-8 text-center">加载中...</p>}

      <div className="space-y-3">
        {messages.map((m) => (
          <div key={m.id} className={`flex gap-3 ${m.role === "user" ? "" : ""}`}>
            <div className={`w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5 ${
              m.role === "user"
                ? "bg-gray-100 text-gray-500"
                : "bg-blue-50 text-blue-500"
            }`}>
              {m.role === "user" ? <User className="w-3.5 h-3.5" /> : <Bot className="w-3.5 h-3.5" />}
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-medium text-gray-500">
                  {m.role === "user" ? "用户" : selected.characterName}
                </span>
                <span className="text-[10px] text-gray-300">{formatTime(m.createdAt)}</span>
                {m.emotion && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-500">
                    {m.emotion}
                  </span>
                )}
              </div>
              <p className="text-sm text-gray-800 leading-relaxed">{m.content}</p>
              {m.action && (
                <p className="text-xs text-gray-400 italic mt-1">*{m.action}*</p>
              )}
              {m.thought && (
                <p className="text-xs text-gray-300 mt-1">💭 {m.thought}</p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
