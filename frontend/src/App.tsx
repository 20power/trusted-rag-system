import { FormEvent, useEffect, useState } from "react";
import {
  api,
  type AskResponse,
  type DocumentItem,
  type DocumentStats,
  type EvaluationSummary,
  type SystemInfo,
} from "./api";

type View = "overview" | "documents" | "ask" | "evaluation" | "settings";

const navItems: { id: View; label: string; icon: string }[] = [
  { id: "overview", label: "运行概览", icon: "⌂" },
  { id: "documents", label: "知识库", icon: "▤" },
  { id: "ask", label: "可信问答", icon: "◇" },
  { id: "evaluation", label: "评测中心", icon: "◎" },
  { id: "settings", label: "系统配置", icon: "⚙" },
];

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function statusLabel(status: string): string {
  return (
    {
      discovered: "待解析",
      parsing: "解析中",
      parsed: "已解析",
      indexed: "已索引",
      failed: "失败",
    }[status] ?? status
  );
}

function evidenceSection(metadata: Record<string, unknown>): string | null {
  const path = Array.isArray(metadata.section_path)
    ? metadata.section_path.filter((value): value is string => typeof value === "string")
    : [];
  const article = typeof metadata.article_no === "string" ? metadata.article_no : null;
  const parts = [...path];
  if (article && !parts.includes(article)) parts.push(article);
  return parts.length > 0 ? parts.join(" › ") : null;
}

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`status-dot ${ok ? "ok" : "muted"}`}>
      <i /> {label}
    </span>
  );
}

function MetricCard({ label, value, detail, tone }: { label: string; value: string; detail: string; tone: string }) {
  return (
    <article className="metric-card">
      <div className={`metric-mark ${tone}`} />
      <p>{label}</p>
      <strong>{value}</strong>
      <span>{detail}</span>
    </article>
  );
}

function EmptyState({ children }: { children: string }) {
  return <div className="empty-state">{children}</div>;
}

export default function App() {
  const [view, setView] = useState<View>("overview");
  const [stats, setStats] = useState<DocumentStats | null>(null);
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [evaluation, setEvaluation] = useState<EvaluationSummary | null>(null);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskResponse | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [nextStats, nextSystem, nextDocuments, nextEvaluation] = await Promise.all([
        api.getStats(),
        api.getSystemInfo(),
        api.getDocuments(),
        api.getEvaluation(),
      ]);
      setStats(nextStats);
      setSystem(nextSystem);
      setDocuments(nextDocuments.items);
      setEvaluation(nextEvaluation);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法连接后端服务");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, []);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const keyword = search.trim();
        const query = keyword ? `&search=${encodeURIComponent(keyword)}` : "";
        const result = await api.getDocuments(query);
        if (!cancelled) {
          setDocuments(result.items);
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "文档检索失败");
        }
      }
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [search]);

  async function handleScan() {
    setAction("scan");
    setError(null);
    setNotice(null);
    try {
      const result = await api.scan();
      setNotice(
        `扫描完成：发现 ${result.discovered_files} 份文件，新增 ${result.new_files}，重复 ${result.duplicate_files}。`,
      );
      await loadData();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "扫描失败");
    } finally {
      setAction(null);
    }
  }

  async function handleParseBatch() {
    setAction("parse");
    setError(null);
    setNotice(null);
    try {
      const result = await api.parseBatch(10);
      setNotice(`批量解析完成：成功 ${result.parsed}，失败 ${result.failed}。`);
      await loadData();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "解析失败");
    } finally {
      setAction(null);
    }
  }

  async function handleAsk(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    setAction("ask");
    setAnswer(null);
    setError(null);
    try {
      setAnswer(await api.ask(question.trim()));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "问答请求失败");
    } finally {
      setAction(null);
    }
  }

  const parsedCount =
    (stats?.by_status.find((item) => item.status === "parsed")?.count ?? 0) +
    (stats?.by_status.find((item) => item.status === "indexed")?.count ?? 0);
  const failedCount = stats?.by_status.find((item) => item.status === "failed")?.count ?? 0;
  const baseline = (sourceType: "excel" | "word" | "pdf") =>
    evaluation?.baselines.find((item) => item.source_type === sourceType);
  const percentage = (value: number | undefined) =>
    value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-seal">信</div>
          <div>
            <strong>可信监管 RAG</strong>
            <span>Regulatory Intelligence</span>
          </div>
        </div>
        <nav aria-label="主导航">
          {navItems.map((item) => (
            <button
              key={item.id}
              className={view === item.id ? "active" : ""}
              onClick={() => setView(item.id)}
            >
              <span>{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <StatusDot ok={Boolean(system?.source_data_available)} label="原始语料" />
          <StatusDot ok={Boolean(system?.llm_configured)} label="本地模型" />
          <small>v{system?.version ?? "0.1.0"} · 离线优先</small>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div>
            <p className="eyebrow">南京银行赛题 · 开发环境</p>
            <h1>{navItems.find((item) => item.id === view)?.label}</h1>
          </div>
          <div className="top-actions">
            <span className="environment">{system?.environment ?? "development"}</span>
            <button className="icon-button" onClick={() => void loadData()} title="刷新">
              ↻
            </button>
          </div>
        </header>

        {error && <div className="alert error">{error}</div>}
        {notice && <div className="alert success">{notice}</div>}

        {view === "overview" && (
          <section className="page-content">
            <div className="hero-panel">
              <div>
                <span className="pill">证据优先 · 低幻觉</span>
                <h2>让每一个监管答案，都能回到原始条款或单元格。</h2>
                <p>
                  系统正在建立文件台账与结构化解析基础。原始材料只读保存，所有派生结果均可重建、可审计。
                </p>
              </div>
              <div className="hero-actions">
                <button className="primary" onClick={() => void handleScan()} disabled={action !== null}>
                  {action === "scan" ? "正在扫描…" : "扫描原始语料"}
                </button>
                <button className="secondary" onClick={() => setView("documents")}>
                  查看知识库
                </button>
              </div>
            </div>

            <div className="metrics-grid">
              <MetricCard
                label="有效文件"
                value={loading ? "—" : String(stats?.active ?? 0)}
                detail={`共 ${formatBytes(stats?.total_bytes ?? 0)}`}
                tone="blue"
              />
              <MetricCard
                label="已完成解析"
                value={loading ? "—" : String(parsedCount)}
                detail={`失败 ${failedCount} 份`}
                tone="green"
              />
              <MetricCard
                label="内容重复"
                value={loading ? "—" : String(stats?.duplicates ?? 0)}
                detail="保留别名与原始文件"
                tone="amber"
              />
              <MetricCard
                label="模型状态"
                value={system?.llm_configured ? "就绪" : "未配置"}
                detail={system?.llm_provider ?? "disabled"}
                tone="violet"
              />
            </div>

            <div className="two-column">
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <p>Corpus composition</p>
                    <h3>语料格式分布</h3>
                  </div>
                  <span>{stats?.active ?? 0} files</span>
                </div>
                <div className="format-list">
                  {(stats?.by_extension ?? []).map((item, index) => {
                    const ratio = stats?.active ? (item.count / stats.active) * 100 : 0;
                    return (
                      <div className="format-row" key={item.extension}>
                        <span className={`file-chip file-${index}`}>{item.extension.slice(1).toUpperCase()}</span>
                        <div>
                          <strong>{item.count}</strong>
                          <div className="bar"><i style={{ width: `${ratio}%` }} /></div>
                        </div>
                        <small>{ratio.toFixed(1)}%</small>
                      </div>
                    );
                  })}
                  {!stats?.by_extension.length && <EmptyState>扫描后显示文件格式分布</EmptyState>}
                </div>
              </section>

              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <p>Pipeline</p>
                    <h3>入库流水线</h3>
                  </div>
                  <span className="live-badge">LIVE</span>
                </div>
                <ol className="pipeline-list">
                  <li className="done"><i>1</i><div><strong>原件登记</strong><span>路径、大小、SHA-256、格式签名</span></div></li>
                  <li className={stats?.active ? "ready" : ""}><i>2</i><div><strong>结构化解析</strong><span>条款、页面、工作表与单元格</span></div></li>
                  <li><i>3</i><div><strong>混合索引</strong><span>稀疏、稠密与元数据过滤</span></div></li>
                  <li><i>4</i><div><strong>可信问答</strong><span>引用、校验、澄清与拒答</span></div></li>
                </ol>
              </section>
            </div>
          </section>
        )}

        {view === "documents" && (
          <section className="page-content">
            <div className="toolbar panel">
              <div>
                <p className="eyebrow">只读原件 · 可重建派生数据</p>
                <h2>知识库文件台账</h2>
              </div>
              <div className="toolbar-actions">
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="搜索标题、文件名或 doc_id"
                  aria-label="搜索文档"
                />
                <button className="secondary" onClick={() => void handleScan()} disabled={action !== null}>
                  {action === "scan" ? "扫描中…" : "重新扫描"}
                </button>
                <button className="primary" onClick={() => void handleParseBatch()} disabled={action !== null}>
                  {action === "parse" ? "解析中…" : "解析下一批"}
                </button>
              </div>
            </div>

            <div className="table-panel panel">
              <table>
                <thead>
                  <tr>
                    <th>文档</th>
                    <th>格式</th>
                    <th>年份</th>
                    <th>大小</th>
                    <th>版本状态</th>
                    <th>入库状态</th>
                  </tr>
                </thead>
                <tbody>
                  {documents.map((item) => (
                    <tr key={item.doc_id}>
                      <td>
                        <strong>{item.source_title}</strong>
                        <span title={item.original_filename}>{item.doc_id}</span>
                      </td>
                      <td><span className="format-tag">{item.extension.slice(1).toUpperCase()}</span></td>
                      <td>{item.year_hint ?? "—"}</td>
                      <td>{formatBytes(item.size_bytes)}</td>
                      <td><span className="neutral-tag">{item.version_status === "unknown" ? "未核验" : item.version_status}</span></td>
                      <td>
                        <span className={`ingest-status status-${item.ingest_status}`}>
                          {statusLabel(item.ingest_status)}
                        </span>
                        {item.error_message && <small className="row-error" title={item.error_message}>查看错误</small>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!documents.length && <EmptyState>未找到匹配文件，或尚未扫描原始语料目录。</EmptyState>}
            </div>
          </section>
        )}

        {view === "ask" && (
          <section className="page-content ask-layout">
            <div className="ask-intro">
              <span className="pill">Evidence grounded</span>
              <h2>监管制度与统计报表问答</h2>
              <p>答案将显示原始文件、条款、页码或工作表单元格。模型未配置时，系统会明确返回当前状态。</p>
            </div>
            <div className="chat-panel panel">
              <div className="chat-empty">
                <div className="evidence-orbit"><span>证</span></div>
                <h3>从一个可核验的问题开始</h3>
                <p>例如：2023年第四季度保险业资金运用余额是多少？请给出工作表和单元格。</p>
              </div>
              {answer && (
                <div className="answer-card">
                  <div className="answer-status">
                    {answer.status} · {answer.answer_mode} · {answer.retrieval_mode}
                  </div>
                  <p>{answer.answer}</p>
                  {answer.citations.length > 0 && (
                    <div className="citation-strip">
                      {answer.citations.map((citation) => (
                        <span key={`${citation.evidence_index}-${citation.locator}`}>
                          [{citation.evidence_index}] {citation.cell ?? citation.locator}
                        </span>
                      ))}
                    </div>
                  )}
                  {answer.evidence.length > 0 && (
                    <div className="evidence-list">
                      {answer.evidence.map((item, index) => (
                        <article className="evidence-card" key={item.chunk_id}>
                          <div>
                            <span>证据 {index + 1}</span>
                            <strong>{item.title}</strong>
                            <code>{item.locator}</code>
                            {evidenceSection(item.metadata) && (
                              <em>{evidenceSection(item.metadata)}</em>
                            )}
                          </div>
                          <p>{item.content}</p>
                          <small title={item.source_file}>
                            相关度 {item.score.toFixed(3)} · {item.doc_id}
                          </small>
                        </article>
                      ))}
                    </div>
                  )}
                  {answer.warnings.map((warning) => <small key={warning}>{warning}</small>)}
                  <code>trace_id: {answer.trace_id}</code>
                </div>
              )}
              <form className="question-form" onSubmit={(event) => void handleAsk(event)}>
                <textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="请输入监管制度、业务流程或统计报表问题…"
                  rows={3}
                />
                <div>
                  <span>系统会优先查找证据；依据不足时不会强行回答。</span>
                  <button className="primary" disabled={action !== null || !question.trim()}>
                    {action === "ask" ? "正在查询…" : "发送问题"}
                  </button>
                </div>
              </form>
            </div>
          </section>
        )}

        {view === "evaluation" && (
          <section className="page-content">
            <div className="section-lead">
              <p className="eyebrow">Evaluation contract</p>
              <h2>可复现的双轨评测</h2>
              <p>选择题用于客观基线，开放式问答用于验证事实、证据、表达和拒答。</p>
            </div>
            <div className="metrics-grid evaluation-grid">
              <MetricCard label="Excel 证据 Recall@5" value={percentage(baseline("excel")?.evidence_recall_at_k)} detail={`${baseline("excel")?.case_count ?? 0} 道甲方题`} tone="green" />
              <MetricCard label="PDF 证据 Recall@5" value={percentage(baseline("pdf")?.evidence_recall_at_k)} detail={`${baseline("pdf")?.case_count ?? 0} 道甲方题`} tone="blue" />
              <MetricCard label="Word 证据 Recall@5" value={percentage(baseline("word")?.evidence_recall_at_k)} detail="旧 DOC 尚待服务器转换" tone="violet" />
              <MetricCard label="已建立知识块" value={(stats?.indexed_chunks ?? 0).toLocaleString()} detail={`${parsedCount} 份文件已索引`} tone="amber" />
            </div>
            <div className="two-column">
              <section className="panel prose-panel">
                <p>Retrieval</p><h3>检索与引用</h3>
                <ul><li>Recall@5 / Recall@10</li><li>MRR 与首条正确证据排名</li><li>引用精确率与必要证据覆盖率</li></ul>
              </section>
              <section className="panel prose-panel">
                <p>Answer quality</p><h3>开放式答案</h3>
                <ul><li>事实点 Precision / Recall / F1</li><li>数字、单位、期间确定性校验</li><li>拒答 Precision / Recall / F1</li></ul>
              </section>
            </div>
          </section>
        )}

        {view === "settings" && (
          <section className="page-content">
            <div className="section-lead"><p className="eyebrow">Runtime configuration</p><h2>系统运行信息</h2></div>
            <div className="settings-panel panel">
              {[
                ["运行环境", system?.environment],
                ["原始数据目录", system?.source_data_dir],
                ["原始语料可用", system?.source_data_available ? "是" : "否"],
                ["QA 数据可用", system?.qa_workbook_available ? "是" : "否"],
                ["生成模型 Provider", system?.llm_provider],
                ["生成模型已配置", system?.llm_configured ? "是" : "否"],
                ["生成模型", system?.llm_model ?? "未配置"],
                ["模型接口", system?.llm_base_url],
                ["Embedding Provider", system?.embedding_provider],
                ["Qdrant", system?.qdrant_url],
              ].map(([label, value]) => (
                <div key={label}><span>{label}</span><strong>{value ?? "—"}</strong></div>
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
