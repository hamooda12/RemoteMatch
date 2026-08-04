import {
  ApiError,
  apiMutation,
  apiRequest,
} from "../../lib/api-client";
import type {
  ProfileResponse,
  ProfileUpsert,
} from "./types";

export async function getProfile(): Promise<ProfileResponse | null> {
  try {
    return await apiRequest<ProfileResponse>("/profile");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }

    throw error;
  }
}

export async function saveProfile(
  profile: ProfileUpsert,
): Promise<ProfileResponse> {
  return apiMutation<ProfileResponse>("/profile", {
    method: "PUT",
    body: JSON.stringify(profile),
  });
}