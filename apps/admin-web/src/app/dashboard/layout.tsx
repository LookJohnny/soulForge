"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Flame, Music, Cpu, Package, Settings, Sparkles, MessageCircle } from "lucide-react";

const navItems = [
  { href: "/dashboard/characters", label: "角色", icon: Flame },
  { href: "/dashboard/idol", label: "虚拟偶像", icon: Sparkles },
  { href: "/dashboard/chat-logs", label: "聊天记录", icon: MessageCircle },
  { href: "/dashboard/voices", label: "音色", icon: Music },
  { href: "/dashboard/devices", label: "设备", icon: Cpu },
  { href: "/dashboard/soul-packs", label: "灵魂包", icon: Package },
  { href: "/dashboard/settings", label: "设置", icon: Settings },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen flex relative z-10">
      {/* Sidebar — Apple Finder style */}
      <aside className="w-[230px] fixed top-0 left-0 h-full z-40 flex flex-col border-r border-black/[0.06] bg-white/70 backdrop-blur-2xl">
        {/* Logo */}
        <Link
          href="/"
          className="flex items-center gap-2.5 px-5 h-[52px] border-b border-black/[0.06]"
        >
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-500 to-blue-600 flex items-center justify-center">
            <Flame className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="text-[15px] font-semibold tracking-tight text-gray-900">
            SoulForge
          </span>
        </Link>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5">
          {navItems.map((item) => {
            const isActive =
              pathname === item.href || pathname.startsWith(item.href + "/");
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2.5 px-3 py-[7px] rounded-lg text-[13px] transition-all duration-200 ${
                  isActive
                    ? "bg-blue-500/10 text-blue-600 font-medium"
                    : "text-gray-500 hover:text-gray-800 hover:bg-black/[0.04]"
                }`}
              >
                <item.icon
                  className={`w-[16px] h-[16px] ${isActive ? "text-blue-500" : "text-gray-400"}`}
                  strokeWidth={isActive ? 2 : 1.6}
                />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-black/[0.06]">
          <div className="text-[11px] text-gray-400">SoulForge v0.1</div>
        </div>
      </aside>

      {/* Main content area — scrollable */}
      <main className="flex-1 ml-[230px] min-h-screen overflow-y-auto">
        <div className="max-w-6xl mx-auto px-8 py-8">{children}</div>
      </main>
    </div>
  );
}
