import { describe, expect, it, vi } from "vitest";
import { connectProjectWS } from "./ws";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onmessage: ((event: { data: string }) => void) | null = null;
  url: string;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }
}

describe("connectProjectWS", () => {
  it("connects to the right project progress URL and forwards parsed messages", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
    vi.stubEnv("NEXT_PUBLIC_WS_URL", "ws://localhost:8000");

    const onMessage = vi.fn();
    connectProjectWS("project-123", onMessage);

    const ws = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
    expect(ws.url).toBe("ws://localhost:8000/ws/projects/project-123/progress");

    ws.onmessage?.({ data: JSON.stringify({ progress_pct: 42 }) });
    expect(onMessage).toHaveBeenCalledWith({ progress_pct: 42 });
  });
});
