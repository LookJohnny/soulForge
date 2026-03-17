import { PrismaClient } from "@prisma/client";
import { hashSync } from "bcryptjs";

const prisma = new PrismaClient();

async function main() {
  // Seed a default brand
  const brand = await prisma.brand.upsert({
    where: { slug: "demo" },
    update: {},
    create: {
      name: "SoulForge Demo",
      slug: "demo",
    },
  });

  // Seed a default admin user (password: admin123)
  const hashedPassword = hashSync("admin123", 10);
  await prisma.user.upsert({
    where: { email: "admin@soulforge.dev" },
    update: { hashedPassword },
    create: {
      brandId: brand.id,
      email: "admin@soulforge.dev",
      name: "Admin",
      hashedPassword,
      role: "admin",
    },
  });

  // Seed a FREE license for the demo brand
  const existingLicense = await prisma.license.findFirst({ where: { brandId: brand.id } });
  if (!existingLicense) {
    await prisma.license.create({
      data: {
        brandId: brand.id,
        tier: "FREE",
        maxCharacters: 3,
        maxDevices: 10,
        maxDailyConvos: 100,
      },
    });
  }

  // Seed voice profiles with real DashScope voice IDs
  const voices = [
    { name: "甜美少女", dashscopeVoiceId: "longxiaochun", tags: ["可爱", "元气", "少女"], description: "清亮甜美的少女声线" },
    { name: "温柔姐姐", dashscopeVoiceId: "longxiaoxia", tags: ["温柔", "成熟", "治愈"], description: "温暖治愈的姐姐声线" },
    { name: "活力少女", dashscopeVoiceId: "longjielidou", tags: ["活力", "元气", "明亮"], description: "充满活力的明亮女声" },
    { name: "知性女声", dashscopeVoiceId: "longshu", tags: ["知性", "大方", "温和"], description: "成熟知性的女声" },
    { name: "阳光男孩", dashscopeVoiceId: "longshuo", tags: ["阳光", "少年", "活泼"], description: "阳光开朗的少年声线" },
    { name: "沉稳男声", dashscopeVoiceId: "longcheng", tags: ["低沉", "沉稳", "安全感"], description: "有安全感的低沉嗓音" },
    { name: "东北老铁", dashscopeVoiceId: "longlaotie", tags: ["搞笑", "东北", "亲切"], description: "东北味儿十足的热情嗓音" },
    { name: "优雅女声", dashscopeVoiceId: "longyue", tags: ["优雅", "温柔", "清新"], description: "优雅清新的女声" },
  ];

  for (const v of voices) {
    const existing = await prisma.voiceProfile.findFirst({ where: { name: v.name } });
    if (!existing) {
      await prisma.voiceProfile.create({
        data: {
          name: v.name,
          referenceAudio: `voice-profiles/${v.dashscopeVoiceId}.wav`,
          description: v.description,
          tags: v.tags,
          dashscopeVoiceId: v.dashscopeVoiceId,
        },
      });
    } else if (!existing.dashscopeVoiceId) {
      await prisma.voiceProfile.update({
        where: { id: existing.id },
        data: { dashscopeVoiceId: v.dashscopeVoiceId },
      });
    }
  }

  // Seed a demo character (skip if already exists)
  const existingChar = await prisma.character.findFirst({ where: { name: "棉花糖", brandId: brand.id } });
  if (existingChar) {
    console.log("Demo character already exists, skipping");
  } else {
  await prisma.character.create({
    data: {
      brandId: brand.id,
      name: "棉花糖",
      species: "兔子",
      ageSetting: 5,
      backstory: "棉花糖是一只来自云朵王国的小兔子，最喜欢在彩虹上滑滑梯。",
      relationship: "好朋友",
      personality: {
        extrovert: 85,
        humor: 70,
        warmth: 90,
        curiosity: 80,
        energy: 75,
      },
      catchphrases: ["嘻嘻", "好棒好棒", "棉花糖最喜欢你啦"],
      suffix: "~咪",
      topics: ["太空", "动物", "美食", "冒险"],
      forbidden: ["暴力", "恐怖", "政治"],
      responseLength: "SHORT",
      voiceSpeed: 1.1,
      status: "PUBLISHED",
    },
  });
  }

  console.log("Seed data created successfully");
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
