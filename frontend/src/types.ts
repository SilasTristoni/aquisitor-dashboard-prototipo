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
};

export type PageResult<T> = { items: T[]; page: number; page_size: number; total: number; pages: number };
export type Reading = {
  timestamp: string;
  device_id: number;
  session_id?: number;
  raw_power: number;
  raw_power_unit: string;
  power_w: number;
  temperatures_c: Array<number | null>;
  quality: string;
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
