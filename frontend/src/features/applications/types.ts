import type { JobSummary } from "../jobs/types";

export const applicationStatuses = [
  "saved",
  "applied",
  "interview",
  "offer",
  "rejected",
] as const;

export type ApplicationStatus =
  (typeof applicationStatuses)[number];

export type JobApplication = {
  id: string;
  user_id: string;
  job_id: string;
  status: ApplicationStatus;
  notes: string | null;
  applied_at: string | null;
  status_changed_at: string;
  created_at: string;
  updated_at: string;
};

export type TrackedJob = {
  application: JobApplication;
  job: JobSummary;
};

export type TrackedJobListResponse = {
  items: TrackedJob[];
  total: number;
  limit: number;
  offset: number;
};

export type JobApplicationCreate = {
  job_id: string;
  status: ApplicationStatus;
  notes: string | null;
  applied_at: string | null;
};

export type JobApplicationUpdate = {
  status?: ApplicationStatus;
  notes?: string | null;
  applied_at?: string | null;
};