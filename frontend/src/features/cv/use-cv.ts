import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  deleteCV,
  getCV,
  getCVSkills,
  parseCV,
  uploadCV,
} from "./cv-api";
import type { CVDocument } from "./types";

export const cvQueryKey = ["cv", "document"] as const;
export const cvSkillsQueryKey = ["cv", "skills"] as const;

export function useCV() {
  return useQuery({
    queryKey: cvQueryKey,
    queryFn: getCV,
    retry: false,
  });
}

export function useCVSkills(enabled: boolean) {
  return useQuery({
    queryKey: cvSkillsQueryKey,
    queryFn: getCVSkills,
    enabled,
    retry: false,
  });
}

export function useUploadCV() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (file: File) => uploadCV(file),
    onSuccess: async (document) => {
      queryClient.setQueryData<CVDocument>(
        cvQueryKey,
        document,
      );

      queryClient.removeQueries({
        queryKey: cvSkillsQueryKey,
      });

      await queryClient.invalidateQueries({
        queryKey: ["jobs", "matches"],
      });
    },
  });
}

export function useParseCV() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: parseCV,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: cvQueryKey,
        }),
        queryClient.invalidateQueries({
          queryKey: cvSkillsQueryKey,
        }),
        queryClient.invalidateQueries({
          queryKey: ["jobs", "matches"],
        }),
      ]);
    },
  });
}

export function useDeleteCV() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: deleteCV,
    onSuccess: async () => {
      queryClient.setQueryData<CVDocument | null>(
        cvQueryKey,
        null,
      );

      queryClient.removeQueries({
        queryKey: cvSkillsQueryKey,
      });

      await queryClient.invalidateQueries({
        queryKey: ["jobs", "matches"],
      });
    },
  });
}