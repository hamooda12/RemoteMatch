import {
  apiMutation,
  apiRequest,
} from "../../lib/api-client";
import type {
  ApplicationStatus,
  JobApplicationCreate,
  JobApplicationUpdate,
  TrackedJob,
  TrackedJobListResponse,
} from "./types";

export async function getApplications(
  status?: ApplicationStatus,
): Promise<TrackedJobListResponse> {
  const query = new URLSearchParams({
    limit: "100",
    offset: "0",
  });

  if (status) {
    query.set("status", status);
  }

  return apiRequest<TrackedJobListResponse>(
    `/applications?${query.toString()}`,
  );
}

export async function createApplication(
  input: JobApplicationCreate,
): Promise<TrackedJob> {
  return apiMutation<TrackedJob>("/applications", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateApplication(
  applicationId: string,
  input: JobApplicationUpdate,
): Promise<TrackedJob> {
  return apiMutation<TrackedJob>(
    `/applications/${applicationId}`,
    {
      method: "PATCH",
      body: JSON.stringify(input),
    },
  );
}

export async function deleteApplication(
  applicationId: string,
): Promise<void> {
  return apiMutation<void>(
    `/applications/${applicationId}`,
    {
      method: "DELETE",
    },
  );
}