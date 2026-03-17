export interface VoiceProfileInput {
  name: string;
  description?: string;
  tags: string[];
  dashscopeVoiceId?: string;
}

export interface VoicePreviewRequest {
  text: string;
  voiceId: string;
  speed?: number;
}
