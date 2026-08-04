import type { JobSummary } from "../jobs/types";

export type JobMatchBreakdown = {
  skill_score: number;
  role_score: number;
  experience_score: number;
  salary_score: number;
};

export type JobMatch = {
  job: JobSummary;
  score: number;
  is_eligible: boolean;
  breakdown: JobMatchBreakdown;
  matched_skills: string[];
  missing_skills: string[];
  excluded_skills: string[];
  reasons: string[];
};

export type JobMatchListResponse = {
  items: JobMatch[];
  total: number;
  minimum_score: number;
  limit: number;
  offset: number;
};

export type JobMatchParameters = {
  minimumScore: number;
  limit?: number;
  offset?: number;
};