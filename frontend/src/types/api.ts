export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface User {
  id: number;
  email: string;
  name: string;
  created_at: string;
}

export interface Workspace {
  id: number;
  name: string;
  role: string | null;
}

export interface Me {
  user: User;
  workspaces: Workspace[];
  github: { login: string; scopes: string; connected_at: string } | null;
}

export interface Project {
  id: number;
  workspace_id: number;
  name: string;
  description: string;
  repository_url: string | null;
  source_type: 'manual' | 'github' | 'archive' | 'demo';
  github_full_name: string | null;
  default_branch: string | null;
  languages: string[];
  frameworks: string[];
  status: 'new' | 'importing' | 'analysing' | 'ready' | 'error';
  is_demo: boolean;
  created_at: string;
  updated_at: string;
  latest_snapshot_id: number | null;
  latest_analysis_at: string | null;
  latest_run: { id: number; status: string; passed: number; failed: number; total: number; created_at: string } | null;
  open_findings: number;
}

export interface Job {
  id: number;
  job_type: string;
  project_id: number | null;
  status: string;
  error: string | null;
  result: Record<string, unknown>;
  attempts: number;
  max_attempts: number;
  cancel_requested: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface LanguageStat { name: string; files: number; bytes: number; supported: boolean }
export interface Gap { file: string; language: string; reason: string }
export interface Symbol { kind: string; name: string; line?: number; methods?: string[]; params?: string[] }

export interface AnalysisSummary {
  languages: LanguageStat[];
  supported_languages: string[];
  frameworks: string[];
  test_frameworks: string[];
  test_commands: string[];
  build_scripts: Record<string, string>;
  package_name: string | null;
  dependencies: { python: string[]; python_dev: string[]; javascript: string[]; javascript_dev: string[] };
  config_files: string[];
  top_level_directories: Record<string, number>;
  source_directories: string[];
  test_directories: string[];
  totals: { files: number; supported_source_files: number; test_files: number; skipped_files: number };
  test_files: string[];
  testing_gaps: Gap[];
  skipped: { path: string; reason: string }[];
  warnings: string[];
  symbols: Record<string, Symbol[]>;
  complexity_top: { file: string; name: string; line: number; complexity: number; length: number }[];
  snapshot: { id: number; source: string; ref: string | null; commit_sha: string | null };
}

export interface Analysis {
  id: number;
  project_id: number;
  snapshot_id: number;
  summary: AnalysisSummary;
  tools: Record<string, { status: string; reason?: string; version?: string; files?: number; note?: string; findings?: number }>;
  files_inspected: number;
  files_skipped: number;
  duration_ms: number;
  created_at: string;
}

export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';

export interface Finding {
  id: number;
  rule_id: string;
  file_path: string;
  line: number | null;
  column: number | null;
  severity: Severity;
  category: string;
  title: string;
  description: string;
  evidence: string | null;
  suggestion: string | null;
  method: string;
  certainty: 'definite' | 'potential';
  status: 'open' | 'accepted' | 'false_positive' | 'resolved';
  created_at: string;
}

export interface GeneratedTest {
  id: number;
  name: string;
  description: string;
  target: string;
  target_file: string;
  category: string;
  language: string;
  framework: string;
  expected_behaviour: string;
  code: string;
  rationale: string;
  source_files: string[];
  generator: string;
  status: 'proposed' | 'approved' | 'rejected';
  validation: { syntax_ok?: boolean; error?: string; forbidden_calls?: string[]; strategy?: string; edited_by_user?: boolean; check?: string };
  reviewed_at: string | null;
  created_at: string;
}

export interface Coverage {
  id: number;
  run_id: number;
  tool: string;
  line_percent: number | null;
  branch_percent: number | null;
  function_percent: number | null;
  lines_covered: number | null;
  lines_total: number | null;
  files: { path: string; line_percent: number | null; statements?: number; covered?: number; missing_lines?: number[]; branch_percent?: number | null; function_percent?: number | null }[];
  created_at: string;
}

export interface TestRun {
  id: number;
  project_id: number;
  snapshot_id: number;
  job_id: number | null;
  language: string;
  framework: string;
  provider: string;
  include_existing: boolean;
  generated_test_ids: number[];
  status: string;
  total: number;
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
  duration_seconds: number | null;
  exit_code: number | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  coverage: { line_percent: number | null; branch_percent: number | null; function_percent: number | null; tool: string } | null;
}

export interface RuleAnalysis {
  kind: string;
  exception_type: string | null;
  exception_message: string | null;
  location: { file: string; line: number } | null;
  meaning: string;
  possible_causes: string[];
  suggested_fixes: string[];
  disclaimer: string;
}

export interface AIAnalysis {
  kind: string;
  provider: string;
  summary: string;
  location: string;
  error_meaning: string;
  likely_causes: string[];
  suggested_fixes: string[];
  additional_tests: string[];
  confidence: string;
}

export interface TestResult {
  id: number;
  run_id: number;
  node_id: string;
  name: string;
  file_path: string | null;
  classname: string | null;
  status: 'passed' | 'failed' | 'error' | 'skipped';
  duration_seconds: number | null;
  message: string | null;
  traceback: string | null;
  generated_test_id: number | null;
  rule_analysis: RuleAnalysis | null;
  ai_analysis: AIAnalysis | null;
}

export interface Bug {
  id: number;
  project_id: number;
  title: string;
  file_path: string | null;
  line: number | null;
  severity: Severity;
  category: string;
  description: string;
  reproduction_steps: string | null;
  expected_behaviour: string | null;
  actual_behaviour: string | null;
  error_output: string | null;
  suggested_solution: string | null;
  ai_explanation: string | null;
  notes: string | null;
  status: 'open' | 'in_progress' | 'resolved' | 'wont_fix';
  source_type: string;
  source_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface Report {
  id: number;
  project_id: number;
  title: string;
  status: string;
  run_id: number | null;
  summary: { severity_counts?: Record<string, number>; verdict?: string; recommendations?: string[] };
  created_at: string;
  job_id: number | null;
}

export interface ChatMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  provider: string | null;
  sources: string[];
  created_at: string;
}

export interface Capabilities {
  version: string;
  environment: string;
  ai: { configured: boolean; provider: string | null; model: string | null };
  github: { oauth_configured: boolean; public_repositories: boolean };
  execution: { provider: string; available: boolean; reason: string; isolation: string };
  demo_mode: boolean;
  queue: { queued_jobs: number; oldest_queued_at: string | null };
  limits: { max_repository_size_mb: number; execution_timeout: number };
}

export interface Overview {
  projects: number;
  demo_projects: number;
  repositories_analysed: number;
  tests_generated: number;
  tests_approved: number;
  test_runs: number;
  tests_executed: number;
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
  open_findings: number;
  open_findings_by_severity: Partial<Record<Severity, number>>;
  recent_runs: { id: number; project_id: number; project: string; status: string; passed: number; failed: number; errors: number; total: number; is_demo: boolean; created_at: string; duration_seconds: number | null }[];
  recent_activity: { id: number; action: string; detail: string; project_id: number | null; project: string | null; created_at: string }[];
}

export interface Trends {
  days: number;
  daily: { date: string; generated: number; executed: number; passed: number; failed: number; runs: number }[];
  coverage: { date: string; line_percent: number | null; project_id: number; run_id: number }[];
  average_run_duration_seconds: number | null;
  findings_by_status: Record<string, number>;
  activity_by_project: { project: string; events: number }[];
}
