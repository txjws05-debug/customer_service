"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Check,
  ClipboardList,
  Copy,
  Loader2,
  MessageCircle,
  Package,
  RefreshCw,
  Send,
  Square,
} from "lucide-react";
import { toast } from "sonner";
import ReactMarkdown from "react-markdown";

import {
  fetchHistory,
  streamChat,
  type ChatObject,
} from "@/lib/api";

interface UIMessage {
  id: string;
  role: "user" | "bot";
  text?: string;
  object?: ChatObject;
}

// 演示用对象（独立前端没有商城页面，用它走通对象消息链路）
const MOCK_PRODUCT: ChatObject = {
  type: "product",
  id: "P1001",
  title: "春季纯棉卫衣",
  attributes: { 价格: "¥129", 分类: "服装" },
};

const MOCK_ORDER: ChatObject = {
  type: "order",
  id: "A1001",
  title: "订单 A1001",
  attributes: { 状态: "已发货", 金额: "¥129" },
};

function ObjectCard({
  object,
  onClick,
}: {
  object: ChatObject;
  onClick?: () => void;
}) {
  const isProduct = object.type === "product";
  const Icon = isProduct ? Package : ClipboardList;
  return (
    <div
      onClick={onClick}
      className={`w-52 rounded-xl border p-3 ${
        onClick
          ? "cursor-pointer border-slate-200 bg-white transition hover:border-indigo-300 hover:shadow-sm"
          : "border-slate-200 bg-white"
      }`}
    >
      <div className="flex items-center gap-2 text-slate-800">
        <Icon size={16} className="text-indigo-500" />
        <span className="truncate text-sm font-medium">
          {object.title || object.id}
        </span>
      </div>
      {object.attributes &&
        Object.entries(object.attributes).map(([k, v]) => (
          <div
            key={k}
            className="mt-2 flex justify-between text-xs text-slate-500"
          >
            <span>{k}</span>
            <span className="text-slate-700">{v}</span>
          </div>
        ))}
      {onClick && (
        <div className="mt-2 text-[11px] text-slate-400">
          点击卡片，向客服咨询该{isProduct ? "商品" : "订单"}
        </div>
      )}
    </div>
  );
}

export default function ChatPage() {
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  useEffect(() => {
    (async () => {
      try {
        const data = await fetchHistory();
        const loaded: UIMessage[] = (data.messages || []).map(
          (m: { role: string; text?: string; object?: ChatObject }, i: number) => ({
            id: `h${i}`,
            role: m.role === "user" ? "user" : "bot",
            text: m.text || undefined,
            object: m.object || undefined,
          }),
        );
        setMessages(loaded);
      } catch {
        // 未登录或无历史：保持空会话
      }
    })();
  }, []);

  // 统一的流式请求：payload 为文本或对象；regenerate=true 时不新增用户消息
  const runChat = useCallback(
    async (
      payload: { text?: string; object?: ChatObject },
      regenerate = false,
    ) => {
      if (!regenerate) {
        setMessages((prev) => [
          ...prev,
          { id: `u-${Date.now()}`, role: "user", ...payload },
        ]);
      }
      const botId = `b-${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        { id: botId, role: "bot", text: "" },
      ]);
      setLoading(true);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const stream = await streamChat(payload, controller.signal);
        const reader = stream.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let acc = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";
          for (const line of lines) {
            const t = line.trim();
            if (!t.startsWith("data:")) continue;
            const data = t.slice(5).trim();
            if (data === "[DONE]") continue;
            try {
              const json = JSON.parse(data);
              if (json.text) {
                acc += json.text;
                const text = acc;
                setMessages((prev) =>
                  prev.map((m) => (m.id === botId ? { ...m, text } : m)),
                );
              } else if (json.error) {
                toast.error(json.error);
                setMessages((prev) => prev.filter((m) => m.id !== botId));
              }
            } catch {
              // 忽略非 JSON / 心跳行
            }
          }
        }
      } catch (err) {
        if ((err as Error).name === "AbortError") {
          // 用户主动停止：保留已生成内容，完全为空才移除空气泡
          setMessages((prev) =>
            prev.filter((m) => m.id !== botId || m.text),
          );
        } else {
          toast.error((err as Error).message);
          setMessages((prev) => prev.filter((m) => m.id !== botId));
        }
      } finally {
        setLoading(false);
        abortRef.current = null;
      }
    },
    [],
  );

  const handleSend = () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    runChat({ text });
  };

  const sendObject = (object: ChatObject) => {
    if (loading) return;
    runChat({ object });
  };

  const stopGeneration = () => {
    abortRef.current?.abort();
  };

  const regenerate = () => {
    if (loading) return;
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    const lastBot = [...messages].reverse().find((m) => m.role === "bot");
    if (!lastUser || !lastBot) return;
    setMessages((prev) => prev.filter((m) => m.id !== lastBot.id));
    const payload = lastUser.object
      ? { object: lastUser.object }
      : { text: lastUser.text };
    runChat(payload, true);
  };

  const copyMessage = async (m: UIMessage) => {
    if (!m.text) return;
    try {
      await navigator.clipboard.writeText(m.text);
      setCopiedId(m.id);
      setTimeout(() => setCopiedId(null), 1500);
    } catch {
      toast.error("复制失败，请手动选择文本");
    }
  };

  const lastBotId = [...messages].reverse().find((m) => m.role === "bot")?.id;

  return (
    // 外壳（AppShell）已经提供了侧栏、顶栏标题和整屏高度，
    // 这里只要把消息区做成「可滚动」、输入区固定在底部即可。
    <div className="flex h-full min-h-0 flex-col">
      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-2 py-4 sm:px-4">
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
          {messages.length === 0 && (
            <div className="mt-20 text-center text-slate-400">
              <MessageCircle size={40} className="mx-auto mb-3 opacity-40" />
              <p className="text-sm">有什么可以帮您？随时开始对话</p>
            </div>
          )}
          {messages.map((m) => (
            <div
              key={m.id}
              className={`group relative flex ${
                m.role === "user" ? "justify-end" : "justify-start"
              }`}
            >
              <div
                className={`max-w-[85%] sm:max-w-[75%] ${
                  m.role === "user"
                    ? "rounded-2xl bg-indigo-500 px-4 py-2.5 text-white"
                    : "rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-slate-800"
                }`}
              >
                {m.text ? (
                  m.role === "bot" ? (
                    <div className="markdown-body text-sm leading-relaxed">
                      <ReactMarkdown>{m.text}</ReactMarkdown>
                    </div>
                  ) : (
                    <span className="whitespace-pre-wrap text-sm">
                      {m.text}
                    </span>
                  )
                ) : null}
                {m.object && (
                  <ObjectCard
                    object={m.object}
                    onClick={
                      m.role === "user"
                        ? () => sendObject(m.object!)
                        : undefined
                    }
                  />
                )}
                {m.role === "bot" && loading && !m.text && (
                  <Loader2 className="animate-spin" size={16} />
                )}
              </div>

              {/* Bot 气泡工具条：复制 + 重新生成（仅最后一条） */}
              {m.role === "bot" && m.text && (
                <div className="absolute -bottom-7 right-0 flex gap-1 opacity-0 transition group-hover:opacity-100">
                  <button
                    onClick={() => copyMessage(m)}
                    title="复制"
                    className="rounded-md p-1.5 text-slate-400 hover:bg-slate-200 hover:text-slate-600"
                  >
                    {copiedId === m.id ? (
                      <Check size={13} className="text-green-500" />
                    ) : (
                      <Copy size={13} />
                    )}
                  </button>
                  {m.id === lastBotId && (
                    <button
                      onClick={regenerate}
                      disabled={loading}
                      title="重新生成"
                      className="rounded-md p-1.5 text-slate-400 hover:bg-slate-200 hover:text-slate-600 disabled:opacity-40"
                    >
                      <RefreshCw size={13} />
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-slate-200 bg-white px-2 py-3 sm:px-4">
        <div className="mx-auto max-w-3xl">
          {/* 演示对象入口 */}
          <div className="mb-2 flex flex-wrap gap-2">
            <button
              onClick={() => sendObject(MOCK_PRODUCT)}
              disabled={loading}
              className="flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600 transition hover:border-indigo-300 hover:text-indigo-600 disabled:opacity-40"
            >
              <Package size={13} />
              发送商品卡片
            </button>
            <button
              onClick={() => sendObject(MOCK_ORDER)}
              disabled={loading}
              className="flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600 transition hover:border-indigo-300 hover:text-indigo-600 disabled:opacity-40"
            >
              <ClipboardList size={13} />
              发送订单卡片
            </button>
          </div>
          <div className="flex items-center gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSend()}
              placeholder="输入您的问题…"
              // 必须显式写文字色：这个输入框在 bg-white 上，而全局 body 的
              // color 是近白色（深色星空主题），不写就会「白字白底」看不见输入内容
              className="flex-1 rounded-xl border border-slate-200 px-4 py-2.5 text-sm text-slate-900 placeholder:text-slate-400 outline-none transition focus:border-indigo-400"
            />
            {loading ? (
              <button
                onClick={stopGeneration}
                title="停止生成"
                className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-500 text-white transition hover:bg-red-600"
              >
                <Square size={17} />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim()}
                className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500 text-white transition hover:bg-indigo-600 disabled:opacity-40"
              >
                <Send size={17} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
