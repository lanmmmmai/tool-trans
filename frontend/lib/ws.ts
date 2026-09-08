export function connectProjectWS(
  projectId: string,
  onMessage: (data: unknown) => void
): WebSocket {
  const base = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";
  const ws = new WebSocket(`${base}/ws/projects/${projectId}/progress`);
  ws.onmessage = (event) => {
    onMessage(JSON.parse(event.data));
  };
  return ws;
}
