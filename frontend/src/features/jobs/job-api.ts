import { apiRequest } from "../../lib/api-client";
import type {
  JobDetail,
  JobListParameters,
  JobListResponse,
} from "./types";
export async function getJobs(
  parameters: JobListParameters,
): Promise<JobListResponse> {
  const query = new URLSearchParams();

  if (parameters.search) {
    query.set("search", parameters.search);
  }

  parameters.skills?.forEach((skill) => {
    query.append("skills", skill);
  });

  parameters.remoteRegions?.forEach((region) => {
    query.append("remote_regions", region);
  });

  if (parameters.employmentType) {
    query.set(
      "employment_type",
      parameters.employmentType,
    );
  }

  if (parameters.experienceLevel) {
    query.set(
      "experience_level",
      parameters.experienceLevel,
    );
  }

  if (parameters.minimumSalary !== undefined) {
    query.set(
      "minimum_salary",
      String(parameters.minimumSalary),
    );
  }

  if (parameters.salaryCurrency) {
    query.set(
      "salary_currency",
      parameters.salaryCurrency,
    );
  }

  query.set("limit", String(parameters.limit ?? 20));
  query.set("offset", String(parameters.offset ?? 0));

  return apiRequest<JobListResponse>(
    `/jobs?${query.toString()}`,
  );
}
export async function getJob(
  jobId: string,
): Promise<JobDetail> {
  return apiRequest<JobDetail>(`/jobs/${jobId}`);
}