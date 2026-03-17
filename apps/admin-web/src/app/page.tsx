"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { Sparkles, Music, Cpu, ChevronRight } from "lucide-react";

const cards = [
  {
    href: "/dashboard/characters",
    icon: Sparkles,
    title: "角色工坊",
    desc: "创建和编辑角色灵魂",
    gradient: "from-purple-500/20 to-fuchsia-500/20",
    iconColor: "text-purple-400",
    count: "角色管理",
  },
  {
    href: "/dashboard/voices",
    icon: Music,
    title: "音色殿堂",
    desc: "管理和试听角色音色",
    gradient: "from-cyan-500/20 to-blue-500/20",
    iconColor: "text-cyan-400",
    count: "音色库",
  },
  {
    href: "/dashboard/devices",
    icon: Cpu,
    title: "设备星图",
    desc: "查看已连接设备状态",
    gradient: "from-amber-500/20 to-orange-500/20",
    iconColor: "text-amber-400",
    count: "设备管理",
  },
];

export default function Home() {
  return (
    <main className="min-h-screen flex items-center justify-center px-6">
      {/* Floating orbs */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/4 left-1/4 w-64 h-64 bg-purple-500/10 rounded-full blur-3xl animate-float" />
        <div
          className="absolute bottom-1/3 right-1/4 w-80 h-80 bg-blue-500/8 rounded-full blur-3xl animate-float"
          style={{ animationDelay: "2s" }}
        />
        <div
          className="absolute top-1/2 right-1/3 w-48 h-48 bg-pink-500/8 rounded-full blur-3xl animate-float"
          style={{ animationDelay: "4s" }}
        />
      </div>

      <div className="relative z-10 text-center max-w-4xl mx-auto">
        <motion.div
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease: "easeOut" }}
        >
          {/* Logo */}
          <div className="mb-4">
            <span className="text-sm tracking-[0.3em] uppercase text-purple-400/70 font-medium">
              AI Soul Injection System
            </span>
          </div>
          <h1 className="text-6xl md:text-7xl font-bold mb-4 glow-text">
            <span className="bg-gradient-to-r from-purple-400 via-fuchsia-400 to-pink-400 bg-clip-text text-transparent">
              SoulForge
            </span>
          </h1>
          <p className="text-lg text-white/40 mb-16">
            为每一只玩具注入独特的灵魂
          </p>
        </motion.div>

        <motion.div
          className="grid grid-cols-1 md:grid-cols-3 gap-5"
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.3, ease: "easeOut" }}
        >
          {cards.map((card, i) => (
            <motion.div
              key={card.href}
              whileHover={{ y: -4, scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              transition={{ type: "spring", stiffness: 400, damping: 25 }}
            >
              <Link
                href={card.href}
                className={`group relative block p-7 rounded-2xl glass overflow-hidden`}
              >
                {/* Gradient overlay */}
                <div
                  className={`absolute inset-0 bg-gradient-to-br ${card.gradient} opacity-0 group-hover:opacity-100 transition-opacity duration-500`}
                />

                <div className="relative z-10">
                  <card.icon
                    className={`w-8 h-8 ${card.iconColor} mb-5 group-hover:scale-110 transition-transform duration-300`}
                  />

                  <h2 className="text-xl font-semibold text-white/90 mb-2 text-left">
                    {card.title}
                  </h2>
                  <p className="text-sm text-white/35 text-left mb-6">
                    {card.desc}
                  </p>

                  <div className="flex items-center text-sm text-purple-400/70 group-hover:text-purple-300 transition-colors">
                    <span>进入{card.count}</span>
                    <ChevronRight className="w-4 h-4 ml-1 group-hover:translate-x-1 transition-transform" />
                  </div>
                </div>
              </Link>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </main>
  );
}
