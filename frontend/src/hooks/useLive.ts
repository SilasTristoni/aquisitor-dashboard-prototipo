import { useEffect, useRef, useState } from "react";
import type { Alert, Reading } from "../types";

type ConnectionState = "connecting" | "connected" | "disconnected";

export function useLive(maxPoints = 600) {
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [readings, setReadings] = useState<Reading[]>([]);
  const [lastAlert, setLastAlert] = useState<Alert | null>(null);
  const retry = useRef(0);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: number | null = null;
    let stopped = false;
    const connect = () => {
      const token = localStorage.getItem("thermopower.token");
      if (!token || stopped) return;
      setConnection("connecting");
      const base = import.meta.env.VITE_WS_URL ?? `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/v1/ws`;
      socket = new WebSocket(`${base}?token=${encodeURIComponent(token)}`);
      socket.onopen = () => { retry.current = 0; setConnection("connected"); };
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "measurement.created") {
          setReadings((current) => [...current, message.payload].slice(-maxPoints));
        }
        if (message.type === "alert.created") setLastAlert(message.payload);
      };
      socket.onclose = () => {
        setConnection("disconnected");
        if (!stopped) {
          retry.current += 1;
          timer = window.setTimeout(connect, Math.min(1000 * 2 ** retry.current, 15000));
        }
      };
    };
    connect();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      socket?.close();
    };
  }, [maxPoints]);
  return { connection, readings, setReadings, lastAlert };
}
