import {
  ApiError,
  apiMutation,
  apiRequest,
  clearCsrfToken,
} from "../../lib/api-client";
import type {
  AuthUser,
  LoginInput,
  MessageResponse,
  RegisterInput,
} from "./types";

export async function registerUser(
  input: RegisterInput,
): Promise<AuthUser> {
  return apiRequest<AuthUser>("/auth/register", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function loginUser(
  input: LoginInput,
): Promise<AuthUser> {
  const user = await apiRequest<AuthUser>("/auth/login", {
    method: "POST",
    body: JSON.stringify(input),
  });

  clearCsrfToken();

  return user;
}

export async function getCurrentUser(): Promise<AuthUser | null> {
  try {
    return await apiRequest<AuthUser>("/auth/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return null;
    }

    throw error;
  }
}

export async function logoutUser(): Promise<MessageResponse> {
  const response = await apiMutation<MessageResponse>(
    "/auth/logout",
    {
      method: "POST",
    },
  );

  clearCsrfToken();

  return response;
}