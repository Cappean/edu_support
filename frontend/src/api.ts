export function token(role = "student") {
  return sessionStorage.getItem(`${role}_token`) || "";
}
export async function api(
  path: string,
  options: RequestInit = {},
  role = "student",
) {
  const response = await fetch("/api/v1" + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token(role)}`,
      ...options.headers,
    },
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "请求未完成，请检查填写内容",
    );
  return data;
}
export const post = (path: string, data: unknown, role = "student") =>
  api(path, { method: "POST", body: JSON.stringify(data) }, role);
export const uid = () => crypto.randomUUID();
export async function consume(
  runId: string,
  signal: AbortSignal,
  onEvent: (name: string, data: any) => void,
) {
  const response = await fetch(`/api/v1/runs/${runId}/events`, {
    headers: { Authorization: `Bearer ${token()}` },
    signal,
  });
  if (!response.ok || !response.body)
    throw new Error("无法获取回复，请刷新会话查看结果");
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let pending = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    pending += decoder.decode(value, { stream: true });
    let index;
    while ((index = pending.indexOf("\n\n")) >= 0) {
      const frame = pending.slice(0, index);
      pending = pending.slice(index + 2);
      const name = frame
        .split("\n")
        .find((l) => l.startsWith("event:"))
        ?.slice(6)
        .trim();
      const raw = frame
        .split("\n")
        .find((l) => l.startsWith("data:"))
        ?.slice(5)
        .trim();
      if (name && raw) onEvent(name, JSON.parse(raw));
    }
  }
}
