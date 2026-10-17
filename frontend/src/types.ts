export type Role = 'operator' | 'supervisor' | 'admin' | 'jury' | 'ui';

export interface User {
  name: string;
  login: string;
  role: Role;
  user_id: number | null;
  camera_ids: string[] | null;
  kind: 'user' | 'key' | 'anon';
}

export interface Me {
  user: User;
  analyzer: string;
  version: string;
  features: { clips: boolean; telegram: boolean; live_findings: boolean; retention_days: number };
}

export interface Frame { timestamp_sec: number; image_base64: string }

export interface RuleRef { document: string; act?: string; point?: string; quote?: string | null; paraphrase?: string | null; url?: string }
export interface Rule { kind?: string; refs?: RuleRef[]; caveat?: string | null }

export interface Violation {
  type: string;
  timecode_sec: number;
  description: string;
  evidence_frames: Frame[];
  type_code?: string;
  confidence?: number;
  rule?: Rule;
}

export interface JobRow {
  job_id: string;
  status: string;
  public_status: string;
  stage?: string;
  progress?: number;
  source: string;
  filename: string;
  duration_sec?: number;
  verdict?: string | null;
  n_violations?: number | null;
  partial?: number;
  error?: string | null;
  created_at: number;
  finished_at?: number | null;
  created_by?: string | null;
  queue_position?: number | null;
  processing_sec?: number;
  confirmed?: number;
  rejected?: number;
  reviewed?: number;
}

export interface FindingBrief {
  id: number;
  source: 'upload' | 'camera';
  job_id: string | null;
  violation_index: number | null;
  camera_id: string | null;
  camera_name: string | null;
  alert_id: number | null;
  type_code: string;
  type_name: string | null;
  t_sec: number | null;
  confidence: number | null;
  description_ai: string | null;
  description_edit: string | null;
  decision: 'confirm' | 'reject' | null;
  decided_by: string | null;
  decided_at: number | null;
  decision_comment: string | null;
  verified: boolean;
  verify_result: 'agree' | 'disagree' | null;
  verified_by: string | null;
  verified_at: number | null;
  verify_comment: string | null;
  created_at: number;
  updated_at: number;
  edited: boolean;
  below_threshold?: boolean;
  filename?: string | null;
  decided_by_name?: string | null;
  verified_by_name?: string | null;
}

export interface HistoryItem {
  id: number; actor: string | null; actor_role: string | null; action: string; payload: Record<string, unknown>; created_at: number; actor_name?: string;
}

export interface Finding extends FindingBrief {
  rule: Rule;
  description: string;
  frames: Frame[];
  video_url: string | null;
  clip_url: string | null;
  duration_sec: number | null;
  sequence: { n: number; t: number; url: string }[];
  history: HistoryItem[];
  siblings: { id: number; violation_index: number | null; type_name: string | null; t_sec: number | null; decision: string | null }[];
  alert?: Alert | null;
  frames_dir?: string | null;
}

export interface Job {
  job_id: string;
  status: 'processing' | 'done' | 'failed';
  verdict?: 'violation' | 'no_violation';
  violations?: Violation[];
  stage?: string;
  progress?: number;
  queue_position?: number;
  eta_sec?: number | null;
  timeline?: Record<string, number[]> & { t: number[] };
  meta?: Record<string, unknown>;
  partial?: boolean;
  warning?: string;
  error?: string;
  processing_sec?: number;
  filename?: string;
  duration_sec?: number;
  created_at?: number;
  created_by?: string | null;
  source?: string;
  analyzer?: string;
  clips?: number[];
  decisions?: Record<string, string>;
  findings?: FindingBrief[];
  video_available?: boolean;
}

export interface Alert {
  id: number;
  job_id: string | null;
  camera_id: string | null;
  camera_name?: string | null;
  filename?: string | null;
  type_code: string;
  type_name: string | null;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  state: 'open' | 'acknowledged' | 'resolved' | 'false_positive';
  message?: string | null;
  count: number;
  escalation_level: number;
  acked_by?: string | null;
  t_sec?: number | null;
  link?: string;
  finding_id?: number | null;
  created_at: number;
  updated_at: number;
}

export interface Camera {
  id: string;
  name: string;
  url: string;
  enabled: boolean;
  fps: number;
  state: { status: string; fps?: number; frames?: number; ms?: number; active?: string[]; last_error?: string | null };
}

export interface AdminUser {
  id: number; login: string; name: string; role: 'operator' | 'supervisor' | 'admin'; active: boolean;
  camera_ids: string[] | null; created_at: number; last_login_at: number | null;
}

export interface RuleType {
  code: string; type: string; visual?: string; why?: string; norm_kind?: string; caveat?: string | null; refs: RuleRef[];
}

export interface QualityThreshold { base: number; applied: number; status: 'few' | 'ok' | 'raised' | 'retrain'; samples: number; precision?: number; kept?: number }
export interface QualityType {
  type_code: string; type_name: string | null; total: number; decided: number; confirmed: number; rejected: number;
  verified: number; violations: number; confirm_rate: number | null; threshold: QualityThreshold;
}
export interface QualityOperator {
  login: string; name: string; role: string | null; cameras: string[]; decided: number; rejected: number; edited: number;
  verified: number; disagreed: number; flagged_rejects: number; reject_rate: number | null; coverage: number | null;
  disagree_rate: number | null; flagged: boolean; flag_reason: 'disagree' | 'rejects' | null;
}
export interface Quality {
  period: { days: number; since: number | null; until: number };
  summary: {
    total: number; decided: number; confirmed: number; rejected: number; verified: number; disagreed: number; edited: number;
    flagged: number; overruled_confirm: number; true_verified: number; false_verified: number;
    basis: 'verified' | 'operators'; basis_n: number; accuracy: number | null; coverage: number | null; accuracy_delta_pp: number | null;
  };
  by_type: QualityType[];
  weekly: { week: number; start: number; decided: number; false: number; verified: number; rate: number | null }[];
  operators: QualityOperator[];
  thresholds: { base: number; target: number; min_samples: number; raised: string[]; retrain: string[] };
  dataset: { examples: number; verified: number; negatives: number; positives: number };
}
