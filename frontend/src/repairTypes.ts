export type JsonObject = Record<string, unknown>;
export type RepairAction = { id: string; label: string; payload: JsonObject };
export type RepairCase = {
  id: string; title: string; service: string; description: string; filename: string;
  source: string; initial_state: JsonObject; actions: RepairAction[];
  reproduction: JsonObject[]; expected_behavior: string | string[];
  source_kind: 'sample' | 'manual' | 'generated'; language: string;
};
export type RepairReport = {
  status: string; passed: number | boolean; total: number;
  checks: { name: string; passed: boolean; detail?: string }[];
  preview: { state: JsonObject; results: unknown[] };
  duration_ms?: number; isolation?: string | { kind?: string; enforced?: string[]; detail?: string };
};
export type Repair = {
  id: string; case_id: string; title: string; source: string; code: string;
  summary: string; diff: string; report: RepairReport; condition: string;
  model?: string; checkpoint?: string; prompt_hash?: string;
  human_feedback?: { reason: string; code: string; approved: boolean };
  machine_feedback?: { reason: string; code: string; approved: boolean; source?: string };
  curriculum_job_id?: string;
  created_at: string; origin: 'river' | 'manual';
};
export type RepairCheckpoint = {
  id: string; name: string; checkpoint: string; model?: string; example_count: number;
  dataset_hash?: string; method: string; created_at: string;
};
export type RepairEvaluation = {
  id: string; checkpoint: string; status: string; error?: string; case_count: number;
  matched_prompts?: boolean; dataset_hash?: string;
  conditions: { name: 'base' | 'memory' | 'learned'; passed: number; total: number; success_rate: number;
    results: { case_id: string; title: string; report?: RepairReport; error?: string; prompt_hash?: string }[];
  }[];
};
export type RepairState = {
  cases: RepairCase[]; repairs: Repair[]; checkpoints: RepairCheckpoint[];
  evaluations: RepairEvaluation[]; jobs: RepairJob[];
  provider: { configured: boolean; verified: boolean; model?: string };
  stats: { attempts: number; accepted: number; checkpoints: number; eligible?: number; machine_verified?: number };
  training_error?: string | null;
};
export type RepairEvent = { type: string; message?: string; timestamp?: string; created_at?: string; [key: string]: unknown };
export type RepairJob = { id: string; status: string; kind?: string; payload?: { case_id?: string; [key: string]: unknown }; result?: unknown; error?: string; events?: RepairEvent[] };
export const EMPTY_REPAIR_STATE: RepairState = { cases: [], repairs: [], checkpoints: [], evaluations: [], jobs: [], provider: { configured: false, verified: false }, stats: { attempts: 0, accepted: 0, checkpoints: 0 } };
