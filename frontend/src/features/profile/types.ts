export type ExperienceLevel =
  | "no_experience"
  | "internship"
  | "entry_level"
  | "junior"
  | "mid_level"
  | "senior";

export type ProfileUpsert = {
  location: string | null;
  timezone: string;
  target_roles: string[];
  experience_level: ExperienceLevel | null;
  minimum_salary: number | null;
  salary_currency: string | null;
  excluded_technologies: string[];
  availability: Record<string, string>;
};

export type ProfileResponse = ProfileUpsert & {
  user_id: string;
  created_at: string;
  updated_at: string;
};