"use client";

import { useState, useEffect } from "react";
import { Package, Download, Upload, Flame } from "lucide-react";

interface Character {
  id: string;
  name: string;
  species: string;
  status: string;
}

interface SoulPackInfo {
  id: string;
  characterId: string;
  version: string;
  fileSize: number;
  createdAt: string;
}

export default function SoulPacksPage() {
  const [characters, setCharacters] = useState<Character[]>([]);
  const [packs, setPacks] = useState<SoulPackInfo[]>([]);
  const [exporting, setExporting] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [exportResult, setExportResult] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/characters").then((r) => r.json()).then(setCharacters);
    fetch("/api/soul-packs").then((r) => r.json()).then(setPacks);
  }, []);

  async function handleExport(characterId: string) {
    setExporting(characterId);
    setExportResult(null);
    try {
      const res = await fetch("/api/soul-packs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "export", characterId }),
      });
      if (res.ok) {
        const data = await res.json();
        const blob = new Blob(
          [Uint8Array.from(atob(data.soulpack_b64), (c) => c.charCodeAt(0))],
          { type: "application/octet-stream" }
        );
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${data.character_name || "character"}.soulpack`;
        a.click();
        URL.revokeObjectURL(url);
        setExportResult(`封印完成: ${data.character_name} (${(data.size / 1024).toFixed(1)} KB)`);
      } else {
        setExportResult("封印仪式失败");
      }
    } catch {
      setExportResult("封印失败: 锻造炉不可达");
    }
    setExporting(null);
  }

  async function handleImport() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".soulpack";
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;

      setImporting(true);
      const arrayBuffer = await file.arrayBuffer();
      const bytes = new Uint8Array(arrayBuffer);
      const b64 = btoa(String.fromCharCode(...bytes));

      try {
        const res = await fetch("/api/soul-packs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "import", soulpackB64: b64 }),
        });
        if (res.ok) {
          const data = await res.json();
          setExportResult(
            `灵魂已苏醒: ${data.character?.name || "未知灵魂"}`
          );
        } else {
          setExportResult("解封失败: 神印不符或圣匣损坏");
        }
      } catch {
        setExportResult("解封仪式失败");
      }
      setImporting(false);
    };
    input.click();
  }

  return (
    <div className="space-y-8 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold rune-text flex items-center gap-3">
            <Package className="w-6 h-6 text-amber-400" />
            灵魂圣匣
          </h1>
          <p className="text-sm text-amber-600/40 mt-1">
            将灵魂封印为圣匣，跨越时空部署至神器
          </p>
        </div>
        <button
          onClick={handleImport}
          disabled={importing}
          className="btn-primary flex items-center gap-2 text-sm"
        >
          <Upload className="w-4 h-4" />
          {importing ? "解封中..." : "导入圣匣"}
        </button>
      </div>

      {exportResult && (
        <div className="p-4 rounded-xl bg-amber-600/8 border border-amber-600/15 text-sm text-amber-300/80">
          {exportResult}
        </div>
      )}

      {/* Character list for export */}
      <section className="glass rounded-2xl p-6">
        <h2 className="text-lg font-semibold text-amber-200/80 mb-4">可封印灵魂</h2>
        <div className="space-y-3">
          {characters.map((char) => (
            <div
              key={char.id}
              className="flex items-center justify-between p-4 rounded-xl bg-amber-900/5 border border-amber-800/10"
            >
              <div className="flex items-center gap-3">
                <Flame className="w-5 h-5 text-amber-500/50" />
                <div>
                  <span className="text-sm text-amber-200/80">{char.name}</span>
                  <span className="text-xs text-amber-600/30 ml-2">{char.species}</span>
                </div>
              </div>
              <button
                onClick={() => handleExport(char.id)}
                disabled={exporting === char.id}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs
                           bg-amber-700/10 text-amber-300/70 border border-amber-700/15
                           hover:bg-amber-700/20 transition-colors disabled:opacity-50"
              >
                <Download className="w-3.5 h-3.5" />
                {exporting === char.id ? "封印中..." : "封印 .soulpack"}
              </button>
            </div>
          ))}
          {characters.length === 0 && (
            <p className="text-sm text-amber-600/30 text-center py-4">祭坛上尚无灵魂</p>
          )}
        </div>
      </section>

      {/* History */}
      {packs.length > 0 && (
        <section className="glass rounded-2xl p-6">
          <h2 className="text-lg font-semibold text-amber-200/80 mb-4">封印记录</h2>
          <div className="space-y-2">
            {packs.map((pack) => (
              <div
                key={pack.id}
                className="flex items-center justify-between p-3 rounded-lg bg-amber-900/5 border border-amber-800/10 text-sm"
              >
                <span className="text-amber-400/60">v{pack.version}</span>
                <span className="text-amber-700/30 text-xs">
                  {(pack.fileSize / 1024).toFixed(1)} KB
                </span>
                <span className="text-amber-700/30 text-xs">
                  {new Date(pack.createdAt).toLocaleDateString("zh-CN")}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
