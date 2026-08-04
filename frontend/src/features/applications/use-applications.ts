import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  createApplication,
  deleteApplication,
  getApplications,
  updateApplication,
} from "./application-api";
import type {
  ApplicationStatus,
  JobApplicationCreate,
  JobApplicationUpdate,
} from "./types";

export const applicationsQueryKey = [
  "applications",
] as const;

export function useApplications(
  status?: ApplicationStatus,
) {
  return useQuery({
    queryKey: [...applicationsQueryKey, status ?? "all"],
    queryFn: () => getApplications(status),
  });
}

export function useCreateApplication() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: JobApplicationCreate) =>
      createApplication(input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: applicationsQueryKey,
      });
    },
  });
}

export function useUpdateApplication(
  applicationId: string,
) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: JobApplicationUpdate) =>
      updateApplication(applicationId, input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: applicationsQueryKey,
      });
    },
  });
}

export function useDeleteApplication(
  applicationId: string,
) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () =>
      deleteApplication(applicationId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: applicationsQueryKey,
      });
    },
  });
}