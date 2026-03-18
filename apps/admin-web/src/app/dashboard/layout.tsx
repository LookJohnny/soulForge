"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Flame, Music, Cpu, Package, Settings, Sparkles } from "lucide-react";

const navItems = [
  { href: "/dashboard/characters", label: "角色", icon: Flame },
  { href: "/dashboard/idol", label: "虚拟偶像", icon: Sparkles },
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
      {/* Sidebar */}
      <aside className="w-[220px] fixed top-0 left-0 h-full z-40 flex flex-col border-r border-white/[0.04] bg-black/40 backdrop-blur-2xl">
        {/* Logo */}
        <Link
          href="/"
          className="flex items-center gap-2.5 px-5 h-[60px] border-b border-white/[0.04]"
        >
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-amber-400 to-amber-700 flex items-center justify-center shadow-lg shadow-amber-900/20">
            <Flame className="w-3.5 h-3.5 text-white" />
          </div>
          <span className="text-[15px] font-semibold tracking-tight text-gold">
            SoulForge
          </span>
        </Link>

        {/* Nav */}
        <nav className="flex-1 px-3 py-5 space-y-0.5">
          {navItems.map((item) => {
            const isActive =
              pathname === item.href || pathname.startsWith(item.href + "/");
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2.5 px-3 py-[9px] rounded-[10px] text-[13px] transition-all duration-300 ${
                  isActive
                    ? "bg-white/[0.07] text-amber-200 shadow-sm shadow-black/10"
                    : "text-white/35 hover:text-white/60 hover:bg-white/[0.03]"
                }`}
              >
                <item.icon
                  className={`w-[16px] h-[16px] ${isActive ? "text-amber-400" : ""}`}
                  strokeWidth={isActive ? 2.2 : 1.8}
                />
                <span className="font-medium">{item.label}</span>
              </Link>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-white/[0.04]">
          <div className="text-[11px] text-white/15">SoulForge v0.1</div>
        </div>
      </aside>

      {/* Main content area */}
      <main className="flex-1 ml-[220px] p-8 relative z-10">{children}</main>
    </div>
  );
}
