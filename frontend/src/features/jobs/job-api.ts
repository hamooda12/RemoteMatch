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