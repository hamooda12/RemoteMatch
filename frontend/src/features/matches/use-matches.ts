import { useQuery } from "@tanstack/react-query";

import { getJobMatches } from "./match-api";
import type { JobMatchParameters } from "./types";

export function useJobMatches(
  parameters: JobMatchParameters,
  enabled = true,
) {
  return useQuery({
    queryKey: ["jobs", "matches", parameters],
    queryFn: () => getJobMatches(parameters),
    enabled,
  });
}