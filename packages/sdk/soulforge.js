/**
 * SoulForge JS SDK — 在任何设备上接入 AI 灵魂
 *
 * 支持: 浏览器 / 小程序 / Node.js / 耳机固件(WebView)
 *
 * 用法:
 *   const soul = new SoulForge({ apiKey: "sk-xxx", baseUrl: "https://api.soulforge.ai" });
 *   const reply = await soul.chat("你好呀", { characterId: "..." });
 *   console.log(reply.text, reply.emotion, reply.relationshipStage);
 *
 * 流式:
 *   for await (const event of soul.chatStream("你好呀", { characterId: "..." })) {
 *     if (event.type === "text") console.log(event.chunk);
 *     if (event.type === "audio") playAudio(event.audioBase64);
 *     if (event.type === "emotion") updateFace(event.emotion);
 *   }
 */

class SoulForge {
  /**
   * @param {Object} options
   * @param {string} options.apiKey - API Key (sk-xxx)
   * @param {string} options.baseUrl - AI Core 服务地址
   * @param {string} [options.characterId] - 默认角色 ID
   * @param {string} [options.endUserId] - 用户 ID (启用记忆/关系)
   * @param {string} [options.deviceId] - 设备 ID
   * @param {string} [options.sessionId] - 会话 ID (自动生成)
   */
  constructor(options) {
    if (!options.apiKey) throw new Error("apiKey is required");
    if (!options.baseUrl) throw new Error("baseUrl is required");

    this.apiKey = options.apiKey;
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.characterId = options.characterId || null;
    this.endUserId = options.endUserId || null;
    this.deviceId = options.deviceId || "web-" + this._uuid();
    this.sessionId = options.sessionId || this._uuid();
    this.history = [];
    this.maxHistory = 20;
  }

  /**
   * 单轮对话 (非流式)
   * @param {string} text - 用户输入
   * @param {Object} [opts] - 覆盖选项
   * @returns {Promise<{text: string, emotion?: string, relationshipStage?: string, affinity?: number, audioBase64?: string, audioFormat?: string}>}
   */
  async chat(text, opts = {}) {
    const characterId = opts.characterId || this.characterId;
    if (!characterId) throw new Error("characterId is required");

    const body = {
      character_id: characterId,
      text,
      history: this.history,
      with_audio: opts.withAudio !== false,
      session_id: this.sessionId,
    };

    const res = await this._fetch("/chat/preview", body);

    // Maintain history
    this.history.push({ role: "user", content: text });
    this.history.push({ role: "assistant", content: res.text });
    if (this.history.length > this.maxHistory * 2) {
      this.history = this.history.slice(-this.maxHistory * 2);
    }

    return {
      text: res.text,
      emotion: res.emotion,
      audioBase64: res.audio_base64,
      audioFormat: res.audio_format,
      latencyMs: res.latency_ms,
    };
  }

  /**
   * 全管线对话 (支持语音输入 + 记忆 + 关系)
   * @param {string} text - 用户文本输入
   * @param {Object} [opts]
   * @returns {Promise<{text: string, emotion?: string, relationshipStage?: string, affinity?: number, audioData?: string}>}
   */
  async pipelineChat(text, opts = {}) {
    const characterId = opts.characterId || this.characterId;
    if (!characterId) throw new Error("characterId is required");

    const body = {
      character_id: characterId,
      end_user_id: opts.endUserId || this.endUserId,
      device_id: opts.deviceId || this.deviceId,
      session_id: this.sessionId,
      text_input: text,
    };

    const res = await this._fetch("/pipeline/chat", body);

    return {
      text: res.text,
      emotion: res.emotion,
      relationshipStage: res.relationship_stage,
      affinity: res.affinity,
      audioData: res.audio_data,
      latencyMs: res.latency_ms,
    };
  }

  /**
   * 流式对话 (SSE)
   * @param {string} text
   * @param {Object} [opts]
   * @yields {{type: string, chunk?: string, emotion?: string, audioBase64?: string}}
   */
  async *chatStream(text, opts = {}) {
    const characterId = opts.characterId || this.characterId;
    if (!characterId) throw new Error("characterId is required");

    const body = {
      character_id: characterId,
      text,
      history: this.history,
      with_audio: opts.withAudio !== false,
      session_id: this.sessionId,
    };

    const response = await fetch(`${this.baseUrl}/chat/preview/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || err.error || `HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let fullText = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const data = JSON.parse(line.slice(6));

        if (data.type === "text") {
          fullText += data.chunk;
        }

        yield data;
      }
    }

    // Update history
    if (fullText) {
      this.history.push({ role: "user", content: text });
      this.history.push({ role: "assistant", content: fullText });
      if (this.history.length > this.maxHistory * 2) {
        this.history = this.history.slice(-this.maxHistory * 2);
      }
    }
  }

  /**
   * 获取可用声音列表
   * @returns {Promise<Array<{id: string, name: string}>>}
   */
  async getVoices() {
    const res = await this._fetch("/tts/voices", null, "GET");
    return res.voices;
  }

  /**
   * 重置会话 (清空历史，新 session)
   */
  resetSession() {
    this.history = [];
    this.sessionId = this._uuid();
  }

  // ─── Internal ──────────────────────

  async _fetch(path, body, method = "POST") {
    const opts = {
      method,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.apiKey}`,
      },
    };
    if (body && method !== "GET") {
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(`${this.baseUrl}${path}`, opts);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.error || `HTTP ${res.status}`);
    }
    return res.json();
  }

  _uuid() {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }
}

// Export for various environments
if (typeof module !== "undefined" && module.exports) {
  module.exports = { SoulForge };
}
if (typeof window !== "undefined") {
  window.SoulForge = SoulForge;
}
