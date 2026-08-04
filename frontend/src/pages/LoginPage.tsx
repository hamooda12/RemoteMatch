import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, LoaderCircle } from "lucide-react";
import { useForm } from "react-hook-form";
import {
  Link,
  useLocation,
  useNavigate,
} from "react-router";

import { AuthLayout } from "../components/AuthLayout";
import {
  loginSchema,
  type LoginFormValues,
} from "../features/auth/schemas";
import { useLogin } from "../features/auth/use-auth";

type LoginLocationState = {
  from?: string;
  message?: string;
};

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const loginMutation = useLogin();

  const locationState =
    location.state as LoginLocationState | null;

  const destination =
    typeof locationState?.from === "string"
      ? locationState.from
      : "/dashboard";

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: {
      email: "",
      password: "",
    },
  });

  async function submitLogin(
    values: LoginFormValues,
  ): Promise<void> {
    try {
      await loginMutation.mutateAsync(values);

      navigate(destination, {
        replace: true,
      });
    } catch {
      return;
    }
  }

  return (
    <AuthLayout
      title="Welcome back"
      description="Sign in to continue to your RemoteMatch workspace."
    >
      {locationState?.message && (
        <div className="success-message" role="status">
          {locationState.message}
        </div>
      )}

      {loginMutation.error && (
        <div className="form-error" role="alert">
          {loginMutation.error instanceof Error
            ? loginMutation.error.message
            : "Unable to sign in."}
        </div>
      )}

      <form
        className="auth-form"
        onSubmit={handleSubmit(submitLogin)}
        noValidate
      >
        <div className="form-field">
          <label htmlFor="email">Email address</label>

          <input
            id="email"
            type="email"
            autoComplete="email"
            aria-invalid={errors.email ? "true" : "false"}
            {...register("email")}
          />

          {errors.email && (
            <p className="field-error">{errors.email.message}</p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor="password">Password</label>

          <input
            id="password"
            type="password"
            autoComplete="current-password"
            aria-invalid={errors.password ? "true" : "false"}
            {...register("password")}
          />

          {errors.password && (
            <p className="field-error">
              {errors.password.message}
            </p>
          )}
        </div>

        <button
          className="primary-button"
          type="submit"
          disabled={loginMutation.isPending}
        >
          {loginMutation.isPending ? (
            <>
              <LoaderCircle
                className="spinner"
                aria-hidden="true"
                size={18}
              />
              Signing in...
            </>
          ) : (
            <>
              Sign in
              <ArrowRight aria-hidden="true" size={18} />
            </>
          )}
        </button>
      </form>

      <p className="auth-switch">
        Don&apos;t have an account?{" "}
        <Link to="/register">Create one</Link>
      </p>
    </AuthLayout>
  );
}