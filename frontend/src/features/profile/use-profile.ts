import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { getProfile, saveProfile } from "./profile-api";
import type {
  ProfileResponse,
  ProfileUpsert,
} from "./types";

export const profileQueryKey = ["profile"] as const;

export function useProfile() {
  return useQuery({
    queryKey: profileQueryKey,
    queryFn: getProfile,
    retry: false,
  });
}

export function useSaveProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (profile: ProfileUpsert) =>
      saveProfile(profile),
    onSuccess: async (profile) => {
      queryClient.setQueryData<ProfileResponse>(
        profileQueryKey,
        profile,
      );

      await queryClient.invalidateQueries({
        queryKey: ["jobs", "matches"],
      });
    },
  });
}