import {
  ApiError,
  apiDownload,
  apiMutation,
  apiRequest,
} from "../../lib/api-client";
import type {
  CVDocument,
  CVSkillsResponse,
  CVTextResponse,
} from "./types";

export async function getCV(): Promise<CVDocument | null> {
  try {
    return await apiRequest<CVDocument>("/cv");
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }

    throw error;
  }
}

export async function uploadCV(
  file: File,
): Promise<CVDocument> {
  const formData = new FormData();
  formData.append("file", file);

  return apiMutation<CVDocument>("/cv", {
    method: "POST",
    body: formData,
  });
}

export async function parseCV(): Promise<CVTextResponse> {
  return apiMutation<CVTextResponse>("/cv/parse", {
    method: "POST",
  });
}

export async function getCVSkills(): Promise<CVSkillsResponse> {
  return apiRequest<CVSkillsResponse>("/cv/skills");
}

export async function deleteCV(): Promise<void> {
  return apiMutation<void>("/cv", {
    method: "DELETE",
  });
}

export async function downloadCV(): Promise<Blob> {
  return apiDownload("/cv/download");
}