import { useQuery } from "@tanstack/react-query";


import type { JobListParameters } from "./types";
import { getJob, getJobs } from "./job-api";
export function useJobs(
  parameters: JobListParameters,
) {
  return useQuery({
    queryKey: ["jobs", "list", parameters],
    queryFn: () => getJobs(parameters),
  });
}
export function useJob(jobId: string | undefined) {
  return useQuery({
    queryKey: ["jobs", "detail", jobId],
    queryFn: () => getJob(jobId as string),
    enabled: Boolean(jobId),
  });
}