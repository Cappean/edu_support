import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowUp,
  Plus,
  MessageSquare,
  BookOpen,
  ArrowUpRight,
  PanelLeftClose,
  RefreshCw,
  X,
  LogOut,
  Search,
  Check,
  FileText,
  LayoutDashboard,
  Users,
  GraduationCap,
  ShoppingBag,
  Undo2,
  Inbox,
  ShieldCheck,
} from "lucide-react";
import Markdown from "react-markdown";
import { api, post, uid, consume, token } from "./api";
import "./style.css";
import "./operations.css";

type Row = Record<string, any>;
const labels: Row = {
  pending: "待处理",
  paid: "已支付",
  completed: "已完成",
  cancelled: "已取消",
  refunded: "已退款",
  partial_refunded: "部分已退",
  rejected: "已驳回",
  approved: "已批准",
  in_progress: "处理中",
  closed: "已结单",
  published: "已发布",
  draft: "草稿",
  offline: "已下架",
  active: "在读",
  faq: "FAQ",
  article: "文章",
  after_sales: "售后",
  complaint: "投诉",
  refund: "退款相关",
};
const text = (v: any): string =>
  v == null
    ? "—"
    : typeof v === "object"
      ? Array.isArray(v)
        ? v.map(text).join("\n") || "暂无记录"
        : Object.entries(v)
            .map(([key, value]) => `${fieldNames[key] || key}：${text(value)}`)
            .join("\n")
      : labels[String(v)] || String(v);
function Badge({ value }: { value: any }) {
  return <span className={`badge b-${value}`}>{text(value)}</span>;
}
function ErrorBox({ error }: { error: string }) {
  return error ? (
    <div className="error" role="alert">
      {error}
    </div>
  ) : null;
}
function App() {
  return location.pathname.startsWith("/admin") ? <Admin /> : <Student />;
}

function Student() {
  const [students, setStudents] = useState<Row[]>([]),
    [selected, setSelected] = useState<Row | null>(null);
  const [history, setHistory] = useState<Row[]>([]),
    [cid, setCid] = useState(""),
    [messages, setMessages] = useState<Row[]>([]);
  const [input, setInput] = useState(""),
    [busy, setBusy] = useState(false),
    [status, setStatus] = useState(""),
    [error, setError] = useState("");
  const [resource, setResource] = useState(""),
    [records, setRecords] = useState<Row[]>([]),
    [ticket, setTicket] = useState<Row | null>(null),
    [supplement, setSupplement] = useState("");
  const [tasks, setTasks] = useState<Row[]>([]),
    [collapsed, setCollapsed] = useState(false);
  const [operations, setOperations] = useState<Row[]>([]);
  const abort = useRef<AbortController | null>(null),
    bottom = useRef<HTMLDivElement>(null);
  const epoch = useRef(0);
  const refresh = async (version = epoch.current) => {
    const records = await api("/conversations");
    if (version === epoch.current) setHistory(records);
  };
  useEffect(() => {
    api("/demo/students")
      .then(setStudents)
      .catch((e) => setError(e.message));
    return () => abort.current?.abort();
  }, []);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, status]);
  async function choose(userId: number) {
    const version = ++epoch.current;
    abort.current?.abort();
    setSelected(null);
    setBusy(false);
    setError("");
    setMessages([]);
    setCid("");
    setTasks([]);
    setOperations([]);
    setTicket(null);
    setResource("");
    setHistory([]);
    try {
      const data = await post("/auth/demo", { user_id: userId });
      if (version !== epoch.current) return;
      sessionStorage.setItem("student_token", data.token);
      setSelected(data.student);
      await refresh(version);
    } catch (e: any) {
      if (version === epoch.current) setError(e.message);
    }
  }
  async function open(id: string) {
    const version = ++epoch.current;
    abort.current?.abort();
    setError("");
    setCid(id);
    setBusy(false);
    setStatus("");
    try {
      const data = await api(`/conversations/${id}`);
      if (version !== epoch.current) return;
      setMessages(data.messages);
      setTasks(data.tasks);
      setOperations(data.operations || []);
      const running = data.runs.find((r: Row) => r.status === "running");
      if (running) {
        setBusy(true);
        await listen(running.id, id);
      }
    } catch (e: any) {
      if (version === epoch.current) setError(e.message);
    }
  }
  async function listen(runId: string, id: string) {
    const version = epoch.current;
    const controller = new AbortController();
    abort.current = controller;
    let answer = "";
    setMessages((m) => [
      ...m,
      { role: "assistant", content: "", temporary: true },
    ]);
    try {
      await consume(runId, controller.signal, (name, data) => {
        if (version !== epoch.current) return;
        if (name === "delta") {
          answer += data.text;
          setMessages((m) => [
            ...m.filter((x) => !x.temporary),
            { role: "assistant", content: answer, temporary: true },
          ]);
        }
        if (name === "tool_start") setStatus("正在核实相关信息");
        if (name === "operation_result")
          setOperations((m) => [...m, { id: uid(), payload: data }]);
        if (name === "done") setStatus("");
        if (name === "error") setError(data.message);
      });
      if (!controller.signal.aborted) {
        const data = await api(`/conversations/${id}`);
        if (version !== epoch.current) return;
        setMessages(data.messages);
        setTasks(data.tasks);
        setOperations(data.operations || []);
        await refresh(version);
      }
    } catch (e: any) {
      if (version === epoch.current && e.name !== "AbortError")
        setError(e.message);
    } finally {
      if (!controller.signal.aborted && version === epoch.current) {
        setBusy(false);
        setStatus("");
      }
    }
  }
  async function send(value = input) {
    if (!selected || !value.trim() || busy) return;
    const version = epoch.current;
    setError("");
    setInput("");
    setBusy(true);
    setStatus("正在理解您的问题");
    try {
      let id = cid;
      if (!id) {
        id = (await post("/conversations", {})).id;
        if (version !== epoch.current) return;
        setCid(id);
      }
      setMessages((m) => [...m, { role: "user", content: value }]);
      const run = await post(`/conversations/${id}/messages`, {
        content: value,
        request_id: uid(),
      });
      if (version !== epoch.current) return;
      await listen(run.run_id, id);
    } catch (e: any) {
      if (version === epoch.current) {
        setError(e.message);
        setBusy(false);
      }
    }
  }
  async function showResource(kind: string) {
    const version = epoch.current;
    setResource(kind);
    setTicket(null);
    setError("");
    try {
      const result = await api(`/me/${kind}`);
      if (version === epoch.current) setRecords(result);
    } catch (e: any) {
      if (version === epoch.current) setError(e.message);
    }
  }
  return (
    <div className={`student-shell ${collapsed ? "compact" : ""}`}>
      <aside className="sidebar">
        <a className="brand" href="/">
          知行<span>学习服务台</span>
        </a>
        <button
          className="new-chat"
          onClick={() => {
            epoch.current++;
            abort.current?.abort();
            setCid("");
            setMessages([]);
            setTasks([]);
            setOperations([]);
            setBusy(false);
            setStatus("");
          }}
        >
          <Plus size={17} /> 开始新的咨询
        </button>
        <div className="nav-label">最近咨询</div>
        <nav className="history">
          {history.map((h) => (
            <button
              key={h.id}
              className={cid === h.id ? "active" : ""}
              onClick={() => open(h.id)}
            >
              <MessageSquare size={15} />
              <span>{h.title}</span>
            </button>
          ))}
          {!history.length && (
            <p className="muted small">您的咨询记录会保存在这里</p>
          )}
        </nav>
        <div className="sidebar-bottom">
          <span className="nav-label">当前体验学员</span>
          <select
            aria-label="选择演示学员"
            value={selected?.user_id || ""}
            onChange={(e) => choose(Number(e.target.value))}
          >
            <option value="" disabled>
              选择一位学员
            </option>
            {students.map((s) => (
              <option key={s.user_id} value={s.user_id}>
                {s.real_name || s.nickname} · {s.order_count} 个订单
              </option>
            ))}
          </select>
          <p className="small muted">不同学员的咨询和业务信息相互隔离。</p>
          <a className="admin-link" href="/admin">
            管理工作台 <ArrowUpRight size={14} />
          </a>
        </div>
      </aside>
      <main className="chat-main">
        <header className="chat-header">
          <button
            className="icon-button"
            title="收起导航"
            onClick={() => setCollapsed(!collapsed)}
          >
            <PanelLeftClose size={18} />
          </button>
          <span>
            学习服务 <span className="dot" /> 在线
          </span>
          <div className="header-links">
            <button
              disabled={!selected}
              onClick={() => showResource("refunds")}
            >
              退款进度
            </button>
            <button
              disabled={!selected}
              onClick={() => showResource("tickets")}
            >
              我的工单
            </button>
          </div>
        </header>
        <ErrorBox error={error} />
        <section className={`chat-body ${!messages.length ? "empty" : ""}`}>
          {!messages.length ? (
            <div className="welcome">
              <div className="eyebrow">让学习中的问题，有一个回应</div>
              <h1>
                你好，{selected?.real_name || "欢迎来到知行"}。<br />
                今天有什么可以帮你？
              </h1>
              <p>课程咨询、订单与学习进度，或是需要我们跟进的问题。</p>
              <div className="suggestions">
                {[
                  ["课程咨询", "帮我看看有哪些 Python 课程"],
                  ["订单查询", "帮我查询我的订单"],
                  ["学习进度", "我想了解已报名班次的学习进度"],
                  ["售后帮助", "如何申请退款？"],
                ].map(([title, value]) => (
                  <button
                    key={title}
                    disabled={!selected}
                    onClick={() => send(value)}
                  >
                    <span>{title}</span>
                    <ArrowUpRight size={17} />
                    <small>{value}</small>
                  </button>
                ))}
              </div>
              {!selected && (
                <div className="select-hint">请先在左侧选择一位演示学员</div>
              )}
            </div>
          ) : (
            <div className="message-list">
              {messages.map((m, i) => (
                <article key={m.id || i} className={`message ${m.role}`}>
                  <div className="message-avatar">
                    {m.role === "user" ? "我" : "知"}
                  </div>
                  <div className="message-content">
                    <span className="message-author">
                      {m.role === "user" ? "你" : "知行客服"}
                    </span>
                    <Markdown>{m.content || "正在处理…"}</Markdown>
                  </div>
                </article>
              ))}
              {status && (
                <p className="thinking">
                  <span className="dot" />
                  {status}
                </p>
              )}
              <div ref={bottom} />
            </div>
          )}
        </section>
        <footer className="composer-wrap">
          {operations.length > 0 && messages.length > 0 && (
            <div className="operation-strip">
              {operations.slice(-2).map((op) => {
                const r = op.payload.result?.result || op.payload.result;
                return (
                  <div key={op.id}>
                    <Check size={14} />
                    <span>
                      {op.payload.tool === "submit_refund_application"
                        ? "退款申请提交回执"
                        : op.payload.tool === "submit_ticket"
                          ? "工单"
                          : "工单补充"}{" "}
                      · {r.number || r.id} · {text(r.status)}
                      {r.amount ? ` · ¥${r.amount}` : ""}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
          {tasks.some((t) => t.status === "paused") && (
            <div className="task-hint">
              有暂存的办理事项，可以说“继续刚才的申请”恢复。
            </div>
          )}
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <textarea
              aria-label="咨询内容"
              placeholder={
                selected
                  ? "描述您的问题，也可以直接告诉我订单号或班次名称…"
                  : "请先选择演示学员"
              }
              disabled={!selected || busy}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  send();
                }
              }}
            />
            <div className="composer-foot">
              <span>Enter 发送 · Shift + Enter 换行</span>
              <button
                className="send"
                disabled={!input.trim() || !selected || busy}
                title="发送"
              >
                <ArrowUp size={19} />
              </button>
            </div>
          </form>
          <p className="fineprint">
            业务结果以平台记录为准。退款申请由管理员审核，人工问题通过工单异步处理。
          </p>
        </footer>
      </main>
      {resource && (
        <div className="drawer-backdrop" onClick={() => setResource("")}>
          <aside className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="section-heading">
              <h2>{resource === "tickets" ? "我的工单" : "退款进度"}</h2>
              <button className="icon-button" onClick={() => setResource("")}>
                <X />
              </button>
            </div>
            {ticket ? (
              <>
                <button className="text-button" onClick={() => setTicket(null)}>
                  ← 返回工单列表
                </button>
                <h3>{ticket.title}</h3>
                <Badge value={ticket.ticket_status} />
                <p>{ticket.ticket_content}</p>
                <div className="timeline">
                  {ticket.records.map((r: Row) => (
                    <div key={r.id}>
                      <small>{r.followed_at}</small>
                      <p>{r.follow_content}</p>
                    </div>
                  ))}
                </div>
                {ticket.ticket_status !== "closed" && (
                  <form
                    onSubmit={async (e) => {
                      e.preventDefault();
                      try {
                        await post(`/me/tickets/${ticket.id}/messages`, {
                          content: supplement,
                          operation_id: uid(),
                        });
                        setSupplement("");
                        setTicket(await api(`/me/tickets/${ticket.id}`));
                      } catch (e: any) {
                        setError(e.message);
                      }
                    }}
                  >
                    <textarea
                      placeholder="补充问题说明"
                      value={supplement}
                      onChange={(e) => setSupplement(e.target.value)}
                    />
                    <button className="primary" disabled={!supplement.trim()}>
                      提交补充
                    </button>
                  </form>
                )}
              </>
            ) : (
              records.map((r) => (
                <button
                  className="record-card"
                  key={r.id}
                  onClick={async () => {
                    if (resource === "tickets")
                      try {
                        setTicket(await api(`/me/tickets/${r.id}`));
                      } catch (e: any) {
                        setError(e.message);
                      }
                  }}
                >
                  <small>{r.ticket_no || r.refund_no}</small>
                  <h3>{r.title || r.item_name}</h3>
                  <Badge value={r.ticket_status || r.refund_status} />
                  {r.apply_amount && <p>申请金额 ¥{r.apply_amount}</p>}
                  {r.remark && <p>{r.remark}</p>}
                </button>
              ))
            )}
            {!records.length && !ticket && <p className="muted">暂无记录</p>}
          </aside>
        </div>
      )}
    </div>
  );
}

const menus: [string, string, React.ReactNode][] = [
  ["overview", "工作概览", <LayoutDashboard size={17} />],
  ["tickets", "问题工单", <Inbox size={17} />],
  ["refunds", "退款审批", <Undo2 size={17} />],
  ["knowledge", "知识内容", <BookOpen size={17} />],
  ["students", "学员查询", <Users size={17} />],
  ["courses", "课程查询", <GraduationCap size={17} />],
  ["cohorts", "班次查询", <GraduationCap size={17} />],
  ["orders", "订单查询", <ShoppingBag size={17} />],
  ["learning", "学习记录", <FileText size={17} />],
  ["audit", "操作记录", <ShieldCheck size={17} />],
];
const columns: Row = {
  tickets: ["ticket_no", "title", "ticket_status", "user_id", "created_at"],
  refunds: [
    "refund_no",
    "refund_reason",
    "apply_amount",
    "refund_status",
    "user_id",
  ],
  students: ["id", "real_name", "nickname", "user_id"],
  courses: ["id", "series_name", "sale_status", "delivery_mode"],
  cohorts: ["id", "cohort_name", "series_id", "sale_price", "start_date"],
  orders: ["order_no", "user_id", "order_status", "paid_amount", "created_at"],
  learning: ["id", "student_id", "cohort_id", "enroll_status", "enroll_at"],
  audit: ["actor", "action", "detail", "created_at"],
};
const fieldNames: Row = {
  attendance: "考勤",
  video: "视频学习",
  homework: "作业",
  exam: "考试",
  totalSessions: "课次记录数",
  presentCount: "出勤次数",
  absentCount: "缺勤次数",
  totalVideos: "视频总数",
  completedVideos: "完成视频数",
  watchedSeconds: "观看秒数",
  totalHomeworks: "作业总数",
  submittedCount: "已提交数",
  correctedCount: "已批改数",
  expiredUnsubmittedCount: "逾期未交数",
  totalExams: "考试总数",
  scores: "成绩记录",
  examId: "考试编号",
  examName: "考试名称",
  totalScore: "满分",
  score: "成绩",
  enrollStatusCode: "报名状态",
  id: "编号",
  ticket_no: "工单编号",
  title: "问题标题",
  ticket_status: "状态",
  user_id: "学员账号",
  created_at: "创建时间",
  refund_no: "退款编号",
  refund_reason: "退款原因",
  apply_amount: "申请金额",
  refund_status: "状态",
  real_name: "姓名",
  nickname: "昵称",
  series_name: "课程名称",
  sale_status: "销售状态",
  delivery_mode: "授课形式",
  cohort_name: "班次名称",
  series_id: "课程编号",
  sale_price: "售价",
  start_date: "开课日期",
  order_no: "订单号",
  order_status: "订单状态",
  paid_amount: "实付金额",
  student_id: "学员档案",
  cohort_id: "班次编号",
  enroll_status: "报名状态",
  enroll_at: "报名时间",
  actor: "操作人",
  action: "操作",
  detail: "详情",
  updated_at: "更新时间",
  body: "正文",
  category: "分类",
  kind: "内容类型",
  aliases: "相似问法",
  status: "发布状态",
  version: "版本",
};
function Admin() {
  const [logged, setLogged] = useState(!!token("admin")),
    [password, setPassword] = useState(""),
    [section, setSection] = useState("overview");
  const [items, setItems] = useState<Row[]>([]),
    [total, setTotal] = useState(0),
    [page, setPage] = useState(1),
    [q, setQ] = useState(""),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<Row | null>(null),
    [note, setNote] = useState(""),
    [internal, setInternal] = useState(false),
    [pending, setPending] = useState(false),
    [editor, setEditor] = useState<Row | null>(null),
    [preview, setPreview] = useState<Row[] | null>(null),
    [stats, setStats] = useState<Row>({});
  async function load() {
    setLoading(true);
    setError("");
    try {
      if (section === "overview") {
        const [t, r, k] = await Promise.all([
          api("/admin/education/tickets?size=1", {}, "admin"),
          api("/admin/education/refunds?size=1", {}, "admin"),
          api("/admin/knowledge", {}, "admin"),
        ]);
        setStats({ tickets: t.total, refunds: r.total, knowledge: k.length });
        return;
      }
      const data = await api(
        section === "knowledge"
          ? `/admin/knowledge?q=${encodeURIComponent(q)}`
          : section === "audit"
            ? "/admin/audit"
            : `/admin/education/${section}?q=${encodeURIComponent(q)}&page=${page}`,
        {},
        "admin",
      );
      setItems(Array.isArray(data) ? data : data.items);
      setTotal(data.total || data.length || 0);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    if (logged) load();
  }, [logged, section, page]);
  async function inspect(row: Row) {
    setError("");
    setNote("");
    setInternal(false);
    try {
      if (section === "learning") {
        const progress = await api(
          `/admin/learning/${row.user_id}/${row.cohort_id}`,
          {},
          "admin",
        );
        setDetail({ ...row, ...progress });
      } else
        setDetail(
          section === "tickets"
            ? await api(`/admin/tickets/${row.id}`, {}, "admin")
            : row,
        );
    } catch (e: any) {
      setError(e.message);
    }
  }
  async function action(kind: string) {
    if (!detail || !note.trim()) return;
    setPending(true);
    try {
      if (section === "refunds")
        await post(
          `/admin/refunds/${detail.id}/review`,
          { decision: kind, note, operation_id: uid() },
          "admin",
        );
      else
        await post(
          `/admin/tickets/${detail.id}/messages`,
          {
            content: note,
            internal,
            close: kind === "close",
            operation_id: uid(),
          },
          "admin",
        );
      setDetail(null);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setPending(false);
    }
  }
  async function save() {
    if (!editor) return;
    setPending(true);
    try {
      await api(
        "/admin/knowledge" + (editor.id ? "/" + editor.id : ""),
        { method: editor.id ? "PUT" : "POST", body: JSON.stringify(editor) },
        "admin",
      );
      setEditor(null);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setPending(false);
    }
  }
  if (!logged)
    return (
      <div className="login-page">
        <a className="brand" href="/">
          知行<span>学习服务台</span>
        </a>
        <form
          className="login-card"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              const data = await post(
                "/auth/admin",
                { username: "admin", password },
                "admin",
              );
              sessionStorage.setItem("admin_token", data.token);
              setLogged(true);
              setError("");
            } catch (e: any) {
              setError(e.message);
            }
          }}
        >
          <div className="eyebrow">OPERATIONS WORKSPACE</div>
          <h1>管理工作台</h1>
          <p className="muted">处理服务事项，维护准确的知识内容。</p>
          <label>
            管理员账号
            <input value="admin" readOnly />
          </label>
          <label>
            密码
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          <ErrorBox error={error} />
          <button className="primary">
            登录工作台 <ArrowUpRight size={16} />
          </button>
          <a className="text-button" href="/">
            返回学员客服
          </a>
        </form>
      </div>
    );
  return (
    <div className="admin-shell">
      <aside className="sidebar">
        <a className="brand" href="/admin">
          知行<span>管理工作台</span>
        </a>
        <div className="nav-label">服务与运营</div>
        <nav>
          {menus.map(([key, label, icon]) => (
            <button
              key={key}
              className={section === key ? "active" : ""}
              onClick={() => {
                setSection(key);
                setPage(1);
                setQ("");
                setDetail(null);
                setEditor(null);
              }}
            >
              {icon}
              {label}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <a className="admin-link" href="/">
            打开学员客服 <ArrowUpRight size={14} />
          </a>
          <button
            className="text-button"
            onClick={() => {
              sessionStorage.removeItem("admin_token");
              setLogged(false);
            }}
          >
            <LogOut size={15} />
            退出登录
          </button>
        </div>
      </aside>
      <main className="admin-main">
        <header className="admin-header">
          <span>服务运营 / {menus.find((m) => m[0] === section)?.[1]}</span>
          <span className="admin-identity">
            <span className="dot" />
            管理员
          </span>
        </header>
        <div className="admin-content">
          <div className="section-heading">
            <div>
              <div className="eyebrow">
                {section === "overview" ? "WORKSPACE" : "SERVICE OPERATIONS"}
              </div>
              <h1>{menus.find((m) => m[0] === section)?.[1]}</h1>
              <p className="muted">
                {section === "knowledge"
                  ? "让每一次回答，都有清晰可靠的依据。"
                  : section === "tickets"
                    ? "跟进学员问题，留下清晰的处理结果。"
                    : section === "refunds"
                      ? "核实全额退款申请，通过后执行模拟退款。"
                      : "教育业务数据与服务事项，一处查看。"}
              </p>
            </div>
            <button className="secondary" onClick={load}>
              <RefreshCw size={15} />
              刷新
            </button>
          </div>
          <ErrorBox error={error} />
          {section === "overview" ? (
            <>
              <div className="stat-grid">
                {[
                  ["tickets", "问题工单", "全部工单"],
                  ["refunds", "退款申请", "全部申请"],
                  ["knowledge", "知识内容", "FAQ 与文章"],
                ].map(([key, label, sub]) => (
                  <button key={key} onClick={() => setSection(key)}>
                    <small>{label}</small>
                    <strong>{stats[key] ?? "—"}</strong>
                    <span>
                      {sub}
                      <ArrowUpRight size={16} />
                    </span>
                  </button>
                ))}
              </div>
              <div className="overview-note">
                <h2>从待办开始，有序处理每个问题。</h2>
                <p>
                  工单支持公开回复和内部备注；结单时请填写学员可见的结果。退款仅支持系统计算的全额金额，不接真实支付。
                </p>
                <button
                  className="primary"
                  onClick={() => setSection("tickets")}
                >
                  查看问题工单 <ArrowUpRight size={16} />
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="table-toolbar">
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    setPage(1);
                    load();
                  }}
                >
                  <Search size={17} />
                  <input
                    aria-label="搜索"
                    placeholder={
                      section === "knowledge"
                        ? "搜索标题或正文"
                        : "搜索名称或编号"
                    }
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                  />
                  <button>搜索</button>
                </form>
                {section === "knowledge" && (
                  <div className="button-group">
                    <button
                      className="secondary"
                      onClick={async () => {
                        try {
                          setPreview(
                            await api(
                              "/admin/knowledge-search?q=" +
                                encodeURIComponent(q),
                              {},
                              "admin",
                            ),
                          );
                        } catch (e: any) {
                          setError(e.message);
                        }
                      }}
                    >
                      检索预览
                    </button>
                    <button
                      className="primary"
                      onClick={() =>
                        setEditor({
                          kind: "faq",
                          title: "",
                          body: "",
                          aliases: "",
                          category: "通用",
                          status: "draft",
                        })
                      }
                    >
                      <Plus size={16} />
                      新增内容
                    </button>
                  </div>
                )}
              </div>
              {loading ? (
                <div className="empty-state">正在读取…</div>
              ) : section === "knowledge" ? (
                <div className="knowledge-list">
                  {items.map((k) => (
                    <button key={k.id} onClick={() => setEditor(k)}>
                      <div>
                        <Badge value={k.kind} />
                        <Badge value={k.status} />
                        <small>
                          v{k.version} · {k.category}
                        </small>
                      </div>
                      <h3>{k.title}</h3>
                      <p>{k.body}</p>
                      <small>
                        更新于 {k.updated_at?.slice(0, 16).replace("T", " ")}
                      </small>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        {(columns[section] || []).map((c: string) => (
                          <th key={c}>{fieldNames[c] || c}</th>
                        ))}
                        <th>操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((row, i) => (
                        <tr key={row.id || i}>
                          {(columns[section] || []).map((c: string) => (
                            <td key={c}>
                              {c.endsWith("status") || c.endsWith("_status") ? (
                                <Badge value={row[c]} />
                              ) : (
                                text(row[c])
                              )}
                            </td>
                          ))}
                          <td>
                            <button
                              className="text-button"
                              onClick={() => inspect(row)}
                            >
                              查看详情 <ArrowUpRight size={13} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!items.length && (
                    <div className="empty-state">暂无匹配记录</div>
                  )}
                </div>
              )}
              <div className="pagination">
                <span>共 {total} 条记录</span>
                {!["knowledge", "audit"].includes(section) && (
                  <div>
                    <button
                      disabled={page === 1}
                      onClick={() => setPage(page - 1)}
                    >
                      上一页
                    </button>
                    <span>{page}</span>
                    <button
                      disabled={page * 20 >= total}
                      onClick={() => setPage(page + 1)}
                    >
                      下一页
                    </button>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </main>
      {detail && (
        <div className="drawer-backdrop" onClick={() => setDetail(null)}>
          <aside className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="section-heading">
              <h2>
                {section === "tickets"
                  ? "工单详情"
                  : section === "refunds"
                    ? "退款申请"
                    : "记录详情"}
              </h2>
              <button className="icon-button" onClick={() => setDetail(null)}>
                <X />
              </button>
            </div>
            <ErrorBox error={error} />
            {Object.entries(detail)
              .filter(([k]) => k !== "records")
              .map(([k, v]) => (
                <div className="detail-row" key={k}>
                  <span>{fieldNames[k] || k}</span>
                  <div>{text(v)}</div>
                </div>
              ))}
            {detail.records && (
              <div className="timeline">
                {detail.records.map((r: Row) => (
                  <div key={r.id}>
                    <small>
                      {r.follow_type === "internal_note"
                        ? "内部备注"
                        : "公开记录"}{" "}
                      · {r.followed_at}
                    </small>
                    <p>{r.follow_content}</p>
                  </div>
                ))}
              </div>
            )}
            {((section === "tickets" && detail.ticket_status !== "closed") ||
              (section === "refunds" &&
                detail.refund_status === "pending")) && (
              <div className="action-form">
                <label>
                  {section === "refunds" ? "审批说明" : "回复或处理结果"}
                  <textarea
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder="请填写清晰、具体的处理说明"
                  />
                </label>
                {section === "tickets" && (
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={internal}
                      onChange={(e) => setInternal(e.target.checked)}
                    />
                    仅内部可见
                  </label>
                )}
                <div className="button-group">
                  {section === "refunds" ? (
                    <>
                      <button
                        className="secondary"
                        disabled={pending || note.trim().length < 2}
                        onClick={() => action("reject")}
                      >
                        驳回申请
                      </button>
                      <button
                        className="primary"
                        disabled={pending || note.trim().length < 2}
                        onClick={() => action("approve")}
                      >
                        通过并模拟退款
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        className="secondary"
                        disabled={pending || !note.trim()}
                        onClick={() => action("reply")}
                      >
                        保存{internal ? "备注" : "回复"}
                      </button>
                      <button
                        className="primary"
                        disabled={pending || internal || !note.trim()}
                        onClick={() => action("close")}
                      >
                        回复并结单
                      </button>
                    </>
                  )}
                </div>
              </div>
            )}
          </aside>
        </div>
      )}
      {editor && (
        <div className="drawer-backdrop" onClick={() => setEditor(null)}>
          <aside className="drawer wide" onClick={(e) => e.stopPropagation()}>
            <div className="section-heading">
              <h2>{editor.id ? "编辑知识" : "新增知识"}</h2>
              <button className="icon-button" onClick={() => setEditor(null)}>
                <X />
              </button>
            </div>
            <ErrorBox error={error} />
            <form
              onSubmit={(e) => {
                e.preventDefault();
                save();
              }}
            >
              {["kind", "title", "category", "aliases", "body", "status"].map(
                (key) => (
                  <label key={key}>
                    {fieldNames[key]}
                    {key === "kind" || key === "status" ? (
                      <select
                        value={editor[key]}
                        onChange={(e) =>
                          setEditor({ ...editor, [key]: e.target.value })
                        }
                      >
                        {(key === "kind"
                          ? ["faq", "article"]
                          : ["draft", "published", "offline"]
                        ).map((v) => (
                          <option key={v} value={v}>
                            {text(v)}
                          </option>
                        ))}
                      </select>
                    ) : key === "body" ? (
                      <textarea
                        className="body-editor"
                        required
                        value={editor[key]}
                        onChange={(e) =>
                          setEditor({ ...editor, [key]: e.target.value })
                        }
                      />
                    ) : (
                      <input
                        required={key === "title"}
                        value={editor[key]}
                        onChange={(e) =>
                          setEditor({ ...editor, [key]: e.target.value })
                        }
                      />
                    )}
                  </label>
                ),
              )}
              <div className="button-group">
                <button className="primary" disabled={pending}>
                  <Check size={16} />
                  保存内容
                </button>
                {editor.id && editor.status === "draft" && (
                  <button
                    type="button"
                    className="danger"
                    onClick={async () => {
                      try {
                        await api(
                          "/admin/knowledge/" + editor.id,
                          { method: "DELETE" },
                          "admin",
                        );
                        setEditor(null);
                        load();
                      } catch (e: any) {
                        setError(e.message);
                      }
                    }}
                  >
                    删除草稿
                  </button>
                )}
              </div>
            </form>
          </aside>
        </div>
      )}
      {preview && (
        <div className="drawer-backdrop" onClick={() => setPreview(null)}>
          <aside className="drawer" onClick={(e) => e.stopPropagation()}>
            <div className="section-heading">
              <h2>检索预览</h2>
              <button className="icon-button" onClick={() => setPreview(null)}>
                <X />
              </button>
            </div>
            <p className="muted">搜索词：{q || "（空）"}</p>
            {preview.map((k) => (
              <div className="record-card" key={k.id}>
                <h3>{k.title}</h3>
                <p>{k.snippet}</p>
                <small>{k.source}</small>
              </div>
            ))}
            {!preview.length && <p>未找到已发布内容。</p>}
          </aside>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
