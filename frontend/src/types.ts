export type Device = {
  id: number;
  name: string;
  manufacturer?: string;
  model?: string;
  serial_number?: string;
  connection_type: string;
  protocol: string;
  port?: string;
  baud_rate: number;
  active: boolean;
  metadata?: Record<string, unknown>;
  configuration_conflicts?: Array<{
    id: number;
    name: string;
    port?: string;
    baud_rate?: number | null;
    active: boolean;
    configuration_status: string;
  }>;
  last_connected_at?: string;
};

export type Session = {
  id: number;
  name: string;
  description?: string;
  notes?: string;
  status: string;
  device_id: number;
  device_name: string;
  operator: string;
  started_at: string;
  ended_at?: string;
  duration_seconds: number;
  sample_count: number;
  average_power_w?: number;
  maximum_temperature_c?: number;
  alert_count: number;
  electrical_sample_count?: number;
  temperature_sample_count?: number;
  devices?: Array<{ role: string; name: string }>;
};

export type PageResult<T> = { items: T[]; page: number; page_size: number; total: number; pages: number };
export type Reading = {
  timestamp: string;
  device_timestamp?: string | null;
  received_timestamp?: string;
  device_id: number;
  session_id?: number;
  raw_power: number | null;
  raw_power_unit: string;
  power_w: number | null;
  temperatures_c: Array<number | null>;
  channel_quality?: string[];
  quality: string;
  device_name?: string;
  device_protocol?: string;
  source_role?: "temperature" | "electrical" | "combined";
  raw_payload?: Record<string, unknown>;
  ambient_temperature_c?: number | null;
};

export type RuntimeStatus = {
  device_id: number;
  state: string;
  connected: boolean;
  reading?: boolean;
  last_message_at?: string;
  messages_per_second?: number;
  sample_count?: number;
  valid_channels?: number;
  last_error?: string | null;
  identity_status?: string;
  protocol_status?: string;
};

export type SourceConnectionOutcome = {
  device_id: number | null;
  requested: boolean;
  success: boolean;
  status: "connected" | "error" | "not_requested";
  error: string | null;
  runtime_status: RuntimeStatus | null;
};

export type SourceConnectionResult = {
  electrical: SourceConnectionOutcome;
  thermal: SourceConnectionOutcome;
  overall: "both" | "partial" | "none";
};

export type SessionStartResult = {
  id: number;
  device_id: number;
  status: string;
  started_at: string;
  devices: Array<{ role: string; device: Device }>;
  connection: SourceConnectionResult;
};

export type Channel = {
  id: number;
  device_id: number;
  channel: number;
  name: string;
  enabled: boolean;
  sensor_type: string;
  unit: "°C";
  correction_offset: number;
  warning_limit?: number;
  critical_limit?: number;
  color: string;
  description?: string;
  physical_location?: string;
  display_order: number;
};

export type Alert = {
  id: number;
  session_id: number;
  timestamp: string;
  metric: string;
  channel?: number;
  measured_value: number;
  threshold: number;
  severity: string;
  acknowledged: boolean;
  acknowledged_by?: number;
  acknowledged_at?: string;
};
