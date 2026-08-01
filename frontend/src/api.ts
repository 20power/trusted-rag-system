export type ExtensionStat = {
  extension: string;
  count: number;
  total_bytes: number;
};

export type StatusStat = {
  status: string;
  count: number;
};

export type DocumentStats = {
  total: number;
  active: number;
  duplicates: number;
  total_bytes: number;
  indexed_chunks: number;
  by_extension: ExtensionStat[];
  by_status: StatusStat[];
};

export type DocumentItem = {
  id: number;
  doc_id: string;
  source_title: string;
  original_filename: string;
  extension: string;
  size_bytes: number;
  year_hint: number | null;
  version_status: string;
  duplicate_of_doc_id: string | null;
  ingest_status: string;
  error_message: string | null;
};

export type DocumentList = {
  items: DocumentItem[];
  total: number;
  page: number;
  page_size: number;
};

export type SystemInfo = {
  app_name: string;
  version: string;
  environment: string;
  llm_provider: string;
  llm_configured: boolean;
  llm_model: string | null;
  llm_base_url: string;
  embedding_provider: string;
  embedding_configured: boolean;
  source_data_dir: string;
  source_data_available: boolean;
  qa_workbook_available: boolean;
  qdrant_url: string;
};

export type ScanResponse = {
  run_id: string;
  discovered_files: number;
  new_files: number;
  updated_files: number;
  duplicate_files: number;
  failed_files: number;
  manifest_path: string;
  extension_counts: Record<string, number>;
  total_bytes: number;
};

export type EvidenceItem = {
  chunk_id: string;
  doc_id: string;
  title: string;
  source_file: string;
  locator: string;
  chunk_type: string;
  content: string;
  score: number;
  metadata: Record<string, unknown>;
};

export type AskResponse = {
  status: string;
  answer: string;
  answer_mode: string;
  retrieval_mode: string;
  evidence: EvidenceItem[];
  citations: {
    evidence_index: number;
    doc_id: string;
    title: string;
    locator: string;
    cell: string | null;
  }[];
  warnings: string[];
  trace_id: string;
};

export type RetrievalBaseline = {
  source_type: "excel" | "word" | "pdf";
  available: boolean;
  case_count: number;
  top_k: number;
  document_recall_at_k: number;
  evidence_recall_at_k: number;
  evidence_mrr: number;
  generated_at: string | null;
};

export type EvaluationSummary = {
  baselines: RetrievalBaseline[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail ?? `请求失败：${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  getStats: () => request<DocumentStats>("/api/v1/documents/stats"),
  getSystemInfo: () => request<SystemInfo>("/api/v1/system/info"),
  getEvaluation: () => request<EvaluationSummary>("/api/v1/evaluation/summary"),
  getDocuments: (query = "") =>
    request<DocumentList>(`/api/v1/documents?page=1&page_size=100${query}`),
  scan: () => request<ScanResponse>("/api/v1/ingestion/scan", { method: "POST" }),
  parseBatch: (limit = 10) =>
    request<{ parsed: number; failed: number }>("/api/v1/ingestion/parse-batch", {
      method: "POST",
      body: JSON.stringify({ limit }),
    }),
  ask: (question: string) =>
    request<AskResponse>("/api/v1/questions/ask", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
};
