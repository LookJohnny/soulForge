export interface DeviceInfo {
  id: string;
  characterId?: string;
  endUserId?: string;
  firmwareVer?: string;
  hardwareModel?: string;
  lastSeen?: string;
  status: "ACTIVE" | "OFFLINE" | "MAINTENANCE";
}

export interface DeviceActivation {
  deviceId: string;
  characterId: string;
  endUserId: string;
}
