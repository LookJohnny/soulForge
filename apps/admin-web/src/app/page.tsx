"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { Flame, Music, Cpu, ChevronRight, Package, Settings } from "lucide-react";

const cards = [
  { href: "/dashboard/characters", icon: Flame, title: "角色", desc: "创建和管理 AI 角色", gradient: "from-amber-500/15 to-orange-500/10" },
  { href: "/dashboard/voices", icon: Music, title: "音色", desc: "管理和试听角色音色", gradient: "from-amber-600/10 to-amber-400/10" },
  { href: "/dashboard/devices", icon: Cpu, title: "设备", desc: "查看已连接设备状态", gradient: "from-amber-700/10 to-amber-500/8" },
  { href: "/dashboard/soul-packs", icon: Package, title: "灵魂包", desc: "导出加密灵魂包", gradient: "from-amber-500/10 to-amber-700/8" },
  { href: "/dashboard/settings", icon: Settings, title: "设置", desc: "密钥与许可证管理", gradient: "from-amber-600/8 to-amber-800/8" },
];

export default function Home() {
  return (
    <main className="min-h-screen flex items-center justify-center px-6 relative">
      {/* Background orbs */}
      <div className="orb w-[500px] h-[500px] bg-amber-600/20 top-[-10%] left-[15%] animate-blob" />
      <div className="orb w-[400px] h-[400px] bg-amber-800/15 bottom-[-5%] right-[10%] animate-blob" style={{ animationDelay: "-5s" }} />

      <div className="relative z-10 text-center max-w-4xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        >
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-amber-400 to-amber-700 flex items-center justify-center mx-auto mb-6 shadow-xl shadow-amber-900/20">
            <Flame className="w-6 h-6 text-white" />
          </div>
          <h1 className="text-5xl md:text-6xl font-bold mb-3 tracking-tight text-shimmer">
            SoulForge
          </h1>
          <p className="text-[15px] text-white/30 mb-14">
            为角色注入灵魂的设计平台
          </p>
        </motion.div>

        <motion.div
          className="grid grid-cols-1 md:grid-cols-3 gap-4"
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.2, ease: [0.16, 1, 0.3, 1] }}
        >
          {cards.slice(0, 3).map((card) => (
            <motion.div
              key={card.href}
              whileHover={{ y: -3, scale: 1.01 }}
              whileTap={{ scale: 0.98 }}
              transition={{ type: "spring", stiffness: 400, damping: 25 }}
            >
              <Link href={card.href} className="group relative block p-6 rounded-2xl glass overflow-hidden text-left">
                <div className={`absolute inset-0 bg-gradient-to-br ${card.gradient} opacity-0 group-hover:opacity-100 transition-opacity duration-500`} />
                <div className="relative z-10">
                  <card.icon className="w-6 h-6 text-amber-400/70 mb-4 group-hover:scale-110 transition-transform duration-300" />
                  <h2 className="text-[16px] font-semibold text-white/85 mb-1">{card.title}</h2>
                  <p className="text-[12px] text-white/30 mb-5">{card.desc}</p>
                  <div className="flex items-center text-[12px] text-amber-400/50 group-hover:text-amber-300 transition-colors">
                    <span>进入</span>
                    <ChevronRight className="w-3.5 h-3.5 ml-0.5 group-hover:translate-x-1 transition-transform" />
                  </div>
                </div>
              </Link>
            </motion.div>
          ))}
        </motion.div>

        <motion.div
          className="grid grid-cols-2 gap-4 mt-4 max-w-md mx-auto"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.7, delay: 0.4 }}
        >
          {cards.slice(3).map((card) => (
            <Link key={card.href} href={card.href} className="group block p-4 rounded-xl glass text-left hover:bg-white/[0.04] transition-colors">
              <div className="flex items-center gap-2.5">
                <card.icon className="w-4 h-4 text-amber-400/50" />
                <span className="text-[13px] text-white/50 group-hover:text-white/70 transition-colors">{card.title}</span>
                <ChevronRight className="w-3 h-3 text-white/15 ml-auto group-hover:translate-x-0.5 transition-transform" />
              </div>
            </Link>
          ))}
        </motion.div>
      </div>
    </main>
  );
}
