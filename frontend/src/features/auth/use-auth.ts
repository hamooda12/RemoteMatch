import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import {
  getCurrentUser,
  loginUser,
  logoutUser,
  registerUser,
} from "./auth-api";
import type {
  AuthUser,
  LoginInput,
  RegisterInput,
} from "./types";

export const authQueryKey = ["auth", "current-user"] as const;

export function useCurrentUser() {
  return useQuery({
    queryKey: authQueryKey,
    queryFn: getCurrentUser,
    retry: false,
  });
}

export function useRegister() {
  return useMutation({
    mutationFn: (input: RegisterInput) =>
      registerUser(input),
  });
}

export function useLogin() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: LoginInput) => loginUser(input),
    onSuccess: (user) => {
      queryClient.setQueryData<AuthUser>(
        authQueryKey,
        user,
      );
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: logoutUser,
    onSuccess: () => {
      queryClient.setQueryData<AuthUser | null>(
        authQueryKey,
        null,
      );

      queryClient.removeQueries({
        predicate: (query) =>
          query.queryKey[0] !== "auth",
      });
    },
  });
}