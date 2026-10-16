import type { PluginListenerHandle } from '@capacitor/core';
export interface AuthorizationResult { url?: string; error?: string; state?: string }
export declare const NativeAuth: {
  getRedirectUri(): Promise<{ uri: string }>;
  authorize(options: { url: string; redirectUri: string; state: string }): Promise<AuthorizationResult>;
  cancel(): Promise<void>;
  getPendingResult(): Promise<AuthorizationResult>;
  clearPendingResult(): Promise<void>;
  addListener(event: 'authorizationResult', listener: (result: AuthorizationResult) => void): Promise<PluginListenerHandle>;
};
