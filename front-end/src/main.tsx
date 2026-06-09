import { StrictMode, useCallback, useEffect, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import {
  BookOpen,
  CalendarDays,
  ExternalLink,
  FileText,
  FlaskConical,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  Settings,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./styles.css";

type Profile = {
  id: string;
  name: string;
  description: string;
  broad_discovery: boolean;
  sources: Array<{ name: string; kind: string; issn?: string; url?: string }>;
};

type Digest = {
  id: number;
  profile_id: string;
  period: "daily" | "weekly";
  start_date: string;
  end_date: string;
  generated_at: string;
  markdown_path: string;
  title: string;
  summary: string;
};

type Paper = {
  uid: string;
  title: string;
  authors: string[];
  abstract: string;
  source: string;
  published_at: string | null;
  url: string;
  doi: string | null;
  journal: string | null;
  profile_id: string | null;
  total_score: number | null;
  labels?: string[];
  reasons?: string[];
  insight?: PaperInsight | null;
  feedback_rating?: string | null;
};

type PaperInsight = {
  chinese_summary: string;
  content_analysis: string;
  critique: string;
  follow_up: string;
  evidence_scope: string;
  reading_path: string | null;
  source_path: string | null;
  confidence: string;
};

type AppState = {
  profiles: Profile[];
  digests: Digest[];
  papers: Paper[];
  runs: AgentRun[];
  profileConfig: ProfileConfig | null;
  digestText: string;
  loading: boolean;
  error: string;
};

type AgentRun = {
  id: number;
  action: string;
  profile_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  attempts: number;
  parent_run_id: number | null;
  result_count: number;
  error: string;
};

type ProfileConfig = {
  path: string;
  yaml_text: string;
};

type Notice = {
  tone: "info" | "success" | "error";
  text: string;
};

const API = "";

function useDashboardData(): AppState & {
  reload: () => void;
  setDigestText: (text: string) => void;
  setProfileConfig: (config: ProfileConfig | null) => void;
} {
  const [state, setState] = useState<AppState>({
    profiles: [],
    digests: [],
    papers: [],
    runs: [],
    profileConfig: null,
    digestText: "",
    loading: true,
    error: "",
  });

  const load = useCallback(async () => {
    setState((current) => ({ ...current, loading: true, error: "" }));
    try {
      const [profiles, digests, papers] = await Promise.all([
        fetchJson<Profile[]>("/api/profiles"),
        fetchJson<Digest[]>("/api/digests"),
        fetchJson<Paper[]>("/api/papers?limit=300"),
      ]);
      const runs = await fetchJson<AgentRun[]>("/api/runs?limit=12").catch(() => []);
      setState({
        profiles,
        digests,
        papers,
        runs,
        profileConfig: null,
        digestText: "",
        loading: false,
        error: "",
      });
    } catch (error) {
      setState((current) => ({
        ...current,
        loading: false,
        error: error instanceof Error ? error.message : "Failed to load data.",
      }));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return {
    ...state,
    reload: load,
    setDigestText: (digestText) => setState((current) => ({ ...current, digestText })),
    setProfileConfig: (profileConfig) => setState((current) => ({ ...current, profileConfig })),
  };
}

function App() {
  const {
    profiles,
    digests,
    papers,
    runs,
    profileConfig,
    digestText,
    loading,
    error,
    reload,
    setDigestText,
    setProfileConfig,
  } =
    useDashboardData();
  const [profileId, setProfileId] = useState("all");
  const [query, setQuery] = useState("");
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busyAction, setBusyAction] = useState<string>("");

  const selectedProfile = profiles.find((profile) => profile.id === profileId);
  const visiblePapers = papers.filter((paper) => {
    const profileMatch = profileId === "all" || paper.profile_id === profileId;
    const haystack = `${paper.title} ${paper.abstract} ${paper.journal ?? ""} ${
      paper.labels?.join(" ") ?? ""
    } ${paper.insight?.chinese_summary ?? ""} ${paper.insight?.content_analysis ?? ""} ${
      paper.insight?.critique ?? ""
    }`.toLowerCase();
    return profileMatch && haystack.includes(query.trim().toLowerCase());
  });

  const visibleDigests = digests.filter(
    (digest) => profileId === "all" || digest.profile_id === profileId,
  );
  const topDigest = visibleDigests[0];

  async function openDigest(digest: Digest) {
    await runUiTask(`open-digest-${digest.id}`, "Loading digest...", async () => {
      const text = await fetchText(`/api/digest-file?path=${encodeURIComponent(digest.markdown_path)}`);
      setDigestText(text);
      return "Digest loaded.";
    });
  }

  async function runNow(action: "daily" | "weekly") {
    await runUiTask(`run-${action}`, `Starting ${action} run...`, async () => {
      const result = await postJson<{ run_id: number; result_count: number }>("/api/run-now", {
        action,
        profile_id: profileId,
        use_llm: false,
        fetch_lookback_days: 3,
      });
      await reload();
      return `${action} run ${result.run_id} finished with ${result.result_count} selected papers.`;
    });
  }

  async function retryRun(runId: number) {
    await runUiTask(`retry-${runId}`, `Retrying run ${runId}...`, async () => {
      const result = await postJson<{ run_id: number; result_count: number }>(`/api/runs/${runId}/retry`, {});
      await reload();
      return `Retry run ${result.run_id} finished with ${result.result_count} selected papers.`;
    });
  }

  async function loadProfileConfig() {
    await runUiTask("load-profile-config", "Loading profile config...", async () => {
      setProfileConfig(await fetchJson<ProfileConfig>("/api/profile-config"));
      return "Profile config loaded.";
    });
  }

  async function saveProfileConfig(yamlText: string) {
    await runUiTask("save-profile-config", "Saving profile config...", async () => {
      await putJson("/api/profile-config", { yaml_text: yamlText });
      setProfileConfig(null);
      await reload();
      return "Profile config saved.";
    });
  }

  async function runUiTask(actionId: string, startText: string, task: () => Promise<string>) {
    if (busyAction) return;
    setBusyAction(actionId);
    setNotice({ tone: "info", text: startText });
    try {
      const doneText = await task();
      setNotice({ tone: "success", text: doneText });
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "Request failed." });
    } finally {
      setBusyAction("");
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand-block">
          <div>
            <p className="eyebrow">AI Systems / Software / Evaluation / ML</p>
            <h1>{selectedProfile?.name ?? "科研情报总览"}</h1>
          </div>
          <p>
            {selectedProfile?.description ??
              "Daily and weekly tracking for configurable research topics, paper insights, and follow-up reading."}
          </p>
        </div>
        <div className="topbar-actions">
          <div className="topbar-stats" aria-label="Research radar counts">
            <Stat label="Profiles" value={profiles.length} />
            <Stat label="Digests" value={digests.length} />
            <Stat label="Papers" value={visiblePapers.length} />
          </div>
          <button className="icon-button" type="button" onClick={reload} aria-label="Reload data">
            <RefreshCw size={17} />
          </button>
        </div>
      </header>

      <main>
        <section className="controls">
          <div className="tabs" aria-label="Watch profiles">
            <button
              type="button"
              className={profileId === "all" ? "active" : ""}
              onClick={() => setProfileId("all")}
            >
              All
            </button>
            {profiles.map((profile) => (
              <button
                type="button"
                className={profileId === profile.id ? "active" : ""}
                key={profile.id}
                onClick={() => setProfileId(profile.id)}
              >
                {shortName(profile.name)}
              </button>
            ))}
          </div>
          <label className="search-box">
            <Search size={16} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              type="search"
              placeholder="Search title, abstract, journal, labels"
            />
          </label>
        </section>

        {error && <div className="empty-state">API 未连接或暂无数据库：{error}</div>}
        {loading && <div className="empty-state">Loading research radar...</div>}
        {notice && <div className={`notice ${notice.tone}`}>{notice.text}</div>}

        {!loading && !error && (
          <div className="grid">
            <section className="panel digest-panel">
              <PanelTitle icon={<FileText size={17} />} label="Digest Archive" />
              {visibleDigests.length === 0 ? (
                <p className="muted">还没有生成摘要。先运行 `uv run daa daily all`。</p>
              ) : (
                <div className="digest-list">
                  {visibleDigests.slice(0, 12).map((digest) => (
                    <button
                      key={digest.id}
                      type="button"
                      disabled={Boolean(busyAction)}
                      onClick={() => void openDigest(digest)}
                    >
                      <span>{digest.period}</span>
                      <strong>{digest.title}</strong>
                      <small>
                        {digest.start_date} - {digest.end_date}
                      </small>
                    </button>
                  ))}
                </div>
              )}
            </section>

            <section className="panel ops-panel">
              <PanelTitle icon={<Play size={17} />} label="Agent Operations" />
              <div className="ops-buttons">
                <button
                  className="text-button"
                  type="button"
                  disabled={Boolean(busyAction)}
                  onClick={() => void runNow("daily")}
                >
                  {busyAction === "run-daily" ? "Running" : "Daily"}
                </button>
                <button
                  className="text-button secondary"
                  type="button"
                  disabled={Boolean(busyAction)}
                  onClick={() => void runNow("weekly")}
                >
                  {busyAction === "run-weekly" ? "Running" : "Weekly"}
                </button>
                <button
                  className="icon-button"
                  type="button"
                  disabled={Boolean(busyAction)}
                  onClick={() => void loadProfileConfig()}
                  aria-label="Edit profiles"
                >
                  <Settings size={17} />
                </button>
              </div>
              <div className="run-list">
                {runs.slice(0, 8).map((run) => (
                  <div className="run-row" key={run.id}>
                    <span className={`status ${run.status}`}>{run.status}</span>
                    <strong>{run.action}</strong>
                    <small>{run.profile_id} · {new Date(run.started_at).toLocaleString()}</small>
                    <span>{run.result_count} papers</span>
                    {run.status === "failed" && (
                      <button
                        className="mini-button"
                        type="button"
                        disabled={Boolean(busyAction)}
                        onClick={() => void retryRun(run.id)}
                      >
                        <RotateCcw size={14} /> Retry
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </section>

            <section className="panel summary-panel">
              <PanelTitle icon={<BookOpen size={17} />} label="Current Summary" />
              {digestText ? (
                <MarkdownView markdown={digestText} />
              ) : topDigest ? (
                <div>
                  <h3>{topDigest.title}</h3>
                  <div className="summary-text">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{topDigest.summary}</ReactMarkdown>
                  </div>
                  <button className="text-button" type="button" onClick={() => void openDigest(topDigest)}>
                    Open Markdown
                  </button>
                </div>
              ) : (
                <p className="muted">选择左侧摘要查看 Markdown 全文。</p>
              )}
            </section>

            <section className="panel papers-panel">
              <PanelTitle icon={<FlaskConical size={17} />} label="Selected Papers" />
              <div className="paper-list">
                {visiblePapers.map((paper) => (
                  <button key={`${paper.profile_id}-${paper.uid}`} type="button" onClick={() => setSelectedPaper(paper)}>
                    <div className="paper-meta">
                      <span>{paper.total_score ?? "-"} / 100</span>
                      <span>{paper.journal ?? paper.source}</span>
                      <span>{paper.published_at ?? "unknown date"}</span>
                    </div>
                    <h3>{paper.title}</h3>
                    <p>{paper.insight?.chinese_summary || paper.abstract || "No abstract available from metadata."}</p>
                    {paper.insight?.critique && (
                      <div className="paper-judge">
                        <strong>Judge</strong>
                        <span>{paper.insight.critique}</span>
                      </div>
                    )}
                    <div className="tag-row">
                      {(paper.labels ?? []).slice(0, 5).map((label) => (
                        <span key={label}>{label}</span>
                      ))}
                    </div>
                  </button>
                ))}
              </div>
            </section>

            <section className="panel source-panel">
              <PanelTitle icon={<CalendarDays size={17} />} label="Source Policy" />
              {(selectedProfile ? [selectedProfile] : profiles).map((profile) => (
                <div className="source-block" key={profile.id}>
                  <h3>{profile.name}</h3>
                  <p>{profile.description}</p>
                  <div className="tag-row">
                    {profile.sources.map((source) => (
                      <span key={`${profile.id}-${source.name}`}>{source.kind}: {source.name}</span>
                    ))}
                    {profile.broad_discovery && <span>宽发现 ML</span>}
                  </div>
                </div>
              ))}
            </section>
          </div>
        )}
      </main>

      {selectedPaper && (
        <PaperDrawer
          paper={selectedPaper}
          onClose={() => setSelectedPaper(null)}
          busy={Boolean(busyAction)}
          onTask={runUiTask}
          onChanged={() => {
            setSelectedPaper(null);
            void reload();
          }}
        />
      )}
      {profileConfig && (
        <ProfileEditor
          config={profileConfig}
          busy={Boolean(busyAction)}
          onClose={() => setProfileConfig(null)}
          onSave={(yamlText) => void saveProfileConfig(yamlText)}
        />
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="stat">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function PanelTitle({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <div className="panel-title">
      {icon}
      <span>{label}</span>
    </div>
  );
}

function MarkdownView({ markdown }: { markdown: string }) {
  return (
    <article className="markdown-view">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </article>
  );
}

function PaperDrawer({
  paper,
  onClose,
  onChanged,
  onTask,
  busy,
}: {
  paper: Paper;
  onClose: () => void;
  onChanged: () => void;
  onTask: (actionId: string, startText: string, task: () => Promise<string>) => Promise<void>;
  busy: boolean;
}) {
  async function sendFeedback(rating: string) {
    if (!paper.profile_id) return;
    await onTask(`feedback-${rating}`, `Saving ${rating} feedback...`, async () => {
      await postJson("/api/feedback", {
        paper_uid: paper.uid,
        profile_id: paper.profile_id,
        rating,
      });
      onChanged();
      return "Feedback saved.";
    });
  }

  async function uploadPdf(file: File | null) {
    if (!file || !paper.profile_id) return;
    const profileId = paper.profile_id;
    await onTask("upload-pdf", "Uploading PDF and reanalyzing...", async () => {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch(
        `${API}/api/papers/${encodeURIComponent(paper.uid)}/upload-pdf?profile_id=${encodeURIComponent(
          profileId,
        )}&use_llm=true`,
        {
          method: "POST",
          body: form,
        },
      );
      if (!response.ok) {
        throw new Error(`${response.status} ${response.statusText}`);
      }
      onChanged();
      return "PDF uploaded and paper insight refreshed.";
    });
  }

  return (
    <div className="drawer-backdrop" onClick={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="drawer">
        <div className="drawer-head">
          <span>{paper.journal ?? paper.source}</span>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close paper">
            <X size={17} />
          </button>
        </div>
        <h2>{paper.title}</h2>
        <p className="muted">{paper.authors?.join(", ") || "Unknown authors"}</p>
        {paper.insight ? (
          <div className="insight-blocks">
            <InsightBlock title="中文总结" body={paper.insight.chinese_summary} />
            <InsightBlock title="内容 Insight" body={paper.insight.content_analysis} />
            <InsightBlock title="Judge / 不足" body={paper.insight.critique} />
            <InsightBlock title="后续跟进" body={paper.insight.follow_up} />
            <div className="evidence-box">
              <h3>阅读证据</h3>
              <p>{paper.insight.evidence_scope}</p>
              <p>置信度：{paper.insight.confidence}</p>
              {paper.insight.reading_path && <p>本地阅读片段：{paper.insight.reading_path}</p>}
              {paper.insight.source_path && <p>本地原始文件：{paper.insight.source_path}</p>}
            </div>
          </div>
        ) : (
          <div className="evidence-box">
            <h3>暂无 Agent Insight</h3>
            <p>{paper.abstract || "No abstract available from source metadata."}</p>
          </div>
        )}
        <div className="tag-row">
          {(paper.labels ?? []).map((label) => (
            <span key={label}>{label}</span>
          ))}
        </div>
        <div className="feedback-row">
          {(["save", "up", "down", "skip"] as const).map((rating) => (
            <button
              className={paper.feedback_rating === rating ? "active" : ""}
              key={rating}
              type="button"
              disabled={busy}
              onClick={() => void sendFeedback(rating)}
            >
              {rating}
            </button>
          ))}
        </div>
        <label className="upload-box">
          <span>Upload PDF and reanalyze</span>
          <input
            type="file"
            accept="application/pdf,.pdf"
            disabled={busy}
            onChange={(event) => void uploadPdf(event.currentTarget.files?.[0] ?? null)}
          />
        </label>
        {paper.reasons?.length ? (
          <div className="reasons">
            <h3>入选依据</h3>
            {paper.reasons.map((reason) => (
              <p key={reason}>{reason}</p>
            ))}
          </div>
        ) : null}
        <a className="external-link" href={paper.url} target="_blank" rel="noreferrer">
          Open source <ExternalLink size={15} />
        </a>
      </aside>
    </div>
  );
}

function ProfileEditor({
  config,
  onClose,
  onSave,
  busy,
}: {
  config: ProfileConfig;
  onClose: () => void;
  onSave: (yamlText: string) => void;
  busy: boolean;
}) {
  const [yamlText, setYamlText] = useState(config.yaml_text);
  return (
    <div className="drawer-backdrop" onClick={(event) => event.target === event.currentTarget && onClose()}>
      <aside className="drawer profile-editor">
        <div className="drawer-head">
          <span>{config.path}</span>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close profile editor">
            <X size={17} />
          </button>
        </div>
        <textarea
          value={yamlText}
          onChange={(event) => setYamlText(event.target.value)}
          disabled={busy}
          spellCheck={false}
        />
        <button className="text-button" type="button" disabled={busy} onClick={() => onSave(yamlText)}>
          {busy ? "Saving" : "Save Profiles"}
        </button>
      </aside>
    </div>
  );
}

function InsightBlock({ title, body }: { title: string; body: string }) {
  return (
    <section className="insight-block">
      <h3>{title}</h3>
      <p>{body}</p>
    </section>
  );
}

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(`${API}${url}`);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

async function fetchText(url: string): Promise<string> {
  const response = await fetch(`${API}${url}`);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.text();
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(`${API}${url}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

async function putJson<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(`${API}${url}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

function shortName(name: string): string {
  return name
    .replace("AI Systems ", "")
    .replace("Software ", "")
    .replace("Interesting ", "")
    .replace(" Methods", "");
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
