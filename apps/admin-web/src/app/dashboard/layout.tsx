"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Flame, Music, Cpu, Package, Settings, Eye } from "lucide-react";

const navItems = [
  { href: "/dashboard/characters", label: "灵魂祭坛", icon: Flame },
  { href: "/dashboard/voices", label: "梵音圣殿", icon: Music },
  { href: "/dashboard/devices", label: "神器星图", icon: Cpu },
  { href: "/dashboard/soul-packs", label: "灵魂圣匣", icon: Package },
  { href: "/dashboard/settings", label: "圣殿设置", icon: Settings },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen flex">
      {/* Sidebar — dark temple panel */}
      <aside className="w-60 fixed top-0 left-0 h-full z-40 flex flex-col glass border-r border-amber-900/20">
        {/* Logo */}
        <Link
          href="/"
          className="flex items-center gap-2.5 px-5 py-5 border-b border-amber-900/15"
        >
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-600 to-amber-900 flex items-center justify-center animate-candle">
            <Eye className="w-4 h-4 text-amber-200" />
          </div>
          <span className="text-lg font-bold rune-text">
            SoulForge
          </span>
        </Link>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-1">
          {navItems.map((item) => {
            const isActive =
              pathname === item.href || pathname.startsWith(item.href + "/");
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-all duration-200 ${
                  isActive
                    ? "bg-amber-700/15 text-amber-300"
                    : "text-amber-200/30 hover:text-amber-200/60 hover:bg-amber-900/10"
                }`}
              >
                <item.icon
                  className={`w-4.5 h-4.5 ${isActive ? "text-amber-400" : ""}`}
                />
                <span className="font-medium">{item.label}</span>
                {isActive && (
                  <div className="ml-auto w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse-glow" />
                )}
              </Link>
            );
          })}
        </nav>

        {/* Footer — sacred inscription */}
        <div className="px-4 py-4 border-t border-amber-900/15">
          <div className="text-xs text-amber-700/40 italic">SoulForge v0.1.0</div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 ml-60 p-8">{children}</main>
    </div>
  );
}
