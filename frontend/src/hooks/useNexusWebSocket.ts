"use client";
import { useCallback, useEffect, useRef, useState } from "react";

export interface WSMessage {
  type: "connected" | "token" | "tool_call" | "tool_result" | "complete" | "status" | "error" | "pong";
  content?: string;
  session_id?: string;
  message?: string;
  done?: boolean;
  tool?: string;
  status?: string;
  available_tools?: string[];
  result?: string;
}

export function useNexusWebSocket(url: string = "ws://localhost:8082/ws/chat") {
  const wsRef = useRef<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeTools, setActiveTools] = useState<string[]>([]);
  const onCompleteRef = useRef<((text: string) => void) | null>(null);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(url);

    ws.onopen = () => {
      setIsConnected(true);
      console.log("[NexusOps] WebSocket connected");
    };

    ws.onmessage = (event) => {
      const data: WSMessage = JSON.parse(event.data);

      switch (data.type) {
        case "connected":
          setSessionId(data.session_id || null);
          break;

        case "status":
          setIsStreaming(true);
          setStreamingText("");
          break;

        case "tool_call":
          setActiveTools((prev) => [...prev, data.tool || ""]);
          break;

        case "token":
          setStreamingText((prev) => prev + (data.content || ""));
          break;

        case "complete":
          setIsStreaming(false);
          setActiveTools([]);
          if (onCompleteRef.current && data.content) {
            onCompleteRef.current(data.content);
          }
          setStreamingText("");
          break;

        case "error":
          setIsStreaming(false);
          setActiveTools([]);
          console.error("[NexusOps] Error:", data.message);
          break;
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      console.log("[NexusOps] WebSocket disconnected");
      // Auto-reconnect after 3s
      setTimeout(connect, 3000);
    };

    ws.onerror = (err) => {
      console.error("[NexusOps] WebSocket error:", err);
    };

    wsRef.current = ws;
  }, [url]);

  const sendMessage = useCallback(
    (message: string, onComplete?: (text: string) => void) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        onCompleteRef.current = onComplete || null;
        setStreamingText("");
        setIsStreaming(true);
        wsRef.current.send(JSON.stringify({ type: "chat", message }));
      }
    },
    []
  );

  const disconnect = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return {
    isConnected,
    sessionId,
    streamingText,
    isStreaming,
    activeTools,
    sendMessage,
    connect,
    disconnect,
  };
}
