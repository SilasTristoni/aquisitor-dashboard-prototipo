import { api } from "./api";

export interface ClientConfig {
  version: string;
  environment: string;
  virtual_lab: boolean;
  login_prefill: {
    enabled: boolean;
    email?: string;
    password?: string;
  };
}

export function loadClientConfig(): Promise<ClientConfig> {
  return api<ClientConfig>("/public-config");
}
