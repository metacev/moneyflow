/* 网络层：REST / SSE 流式 / WebSocket */
const API = {
  async get(url) {
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `请求失败 ${res.status}`);
    return data;
  },
  async post(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `请求失败 ${res.status}`);
    return data;
  },
  /** 读取 SSE 流，逐个事件回调 */
  async stream(url, body, onEvent) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) {
      let msg = `请求失败 ${res.status}`;
      try { msg = (await res.json()).error || msg; } catch (e) {}
      throw new Error(msg);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        const chunk = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        for (const line of chunk.split("\n")) {
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (payload === "[DONE]") return;
          try { onEvent(JSON.parse(payload)); } catch (e) {}
        }
      }
    }
  },
};
