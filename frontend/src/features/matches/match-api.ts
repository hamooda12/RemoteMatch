import { apiRequest } from "../../lib/api-client";
import type {
  JobMatchListResponse,
  JobMatchParameters,
} from "./types";

export async function getJobMatches(
  parameters: JobMatchParameters,
): Promise<JobMatchListResponse> {
  const query = new URLSearchParams({
    minimum_score: String(parameters.minimumScore),
    limit: String(parameters.limit ?? 20),
    offset: String(parameters.offset ?? 0),
  });

  return apiRequest<JobMatchListResponse>(
    `/jobs/matches?${query.toString()}`,
  );
}