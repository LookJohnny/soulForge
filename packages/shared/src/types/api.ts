/** Standard API response wrapper */
export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
}

/** Paginated list response */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

/** Prompt build request to ai-core */
export interface PromptBuildRequest {
  characterId: string;
  endUserId?: string;
  userInput: string;
}

/** Chat pipeline request to ai-core */
export interface ChatRequest {
  characterId: string;
  endUserId?: string;
  deviceId: string;
  sessionId: string;
  audioData?: string; // base64 encoded PCM
  textInput?: string; // text fallback
}
