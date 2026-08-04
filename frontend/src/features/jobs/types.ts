export type JobSummary = {
  id: string;
  title: string;
  company_name: string;
  location: string | null;
  remote_regions: string[];
  employment_type: string | null;
  experience_level: string | null;
  salary_min: string | number | null;
  salary_max: string | number | null;
  salary_currency: string | null;
  skills: string[];
  is_remote: boolean;
  source_name: string;
  source_url: string;
  application_url: string | null;
  published_at: string | null;
  first_seen_at: string;
};
export type JobDetail = JobSummary & {
  description: string;
  requirements: string | null;
  expires_at: string | null;
  last_seen_at: string;
};
export type JobListResponse = {
  items: JobSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type JobListParameters = {
  search?: string;
  limit?: number;
  offset?: number;
};