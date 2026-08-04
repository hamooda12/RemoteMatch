import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, LoaderCircle } from "lucide-react";
import { useForm } from "react-hook-form";
import { Link, useNavigate } from "react-router";

import { AuthLayout } from "../components/AuthLayout";
import {
  registerSchema,
  type RegisterFormValues,
} from "../features/auth/schemas";
import { useRegister } from "../features/auth/use-auth";

export function RegisterPage() {
  const navigate = useNavigate();
  const registerMutation = useRegister();

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<RegisterFormValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: {
      display_name: "",
      email: "",
      password: "",
      confirmPassword: "",
    },
  });

  async function submitRegistration(
    values: RegisterFormValues,
  ): Promise<void> {
    try {
      await registerMutation.mutateAsync({
        display_name: values.display_name,
        email: values.email,
        password: values.password,
      });

      navigate("/login", {
        replace: true,
        state: {
          message:
            "Your account was created. You can now sign in.",
        },
      });
    } catch {
      return;
    }
  }

  return (
    <AuthLayout
      title="Create your account"
      description="Start receiving remote jobs matched to your skills."
    >
      {registerMutation.error && (
        <div className="form-error" role="alert">
          {registerMutation.error instanceof Error
            ? registerMutation.error.message
            : "Unable to create your account."}
        </div>
      )}

      <form
        className="auth-form"
        onSubmit={handleSubmit(submitRegistration)}
        noValidate
      >
        <div className="form-field">
          <label htmlFor="display-name">Display name</label>

          <input
            id="display-name"
            type="text"
            autoComplete="name"
            {...register("display_name")}
          />

          {errors.display_name && (
            <p className="field-error">
              {errors.display_name.message}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor="register-email">Email address</label>

          <input
            id="register-email"
            type="email"
            autoComplete="email"
            {...register("email")}
          />

          {errors.email && (
            <p className="field-error">{errors.email.message}</p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor="register-password">Password</label>

          <input
            id="register-password"
            type="password"
            autoComplete="new-password"
            {...register("password")}
          />

          {errors.password && (
            <p className="field-error">
              {errors.password.message}
            </p>
          )}
        </div>

        <div className="form-field">
          <label htmlFor="confirm-password">
            Confirm password
          </label>

          <input
            id="confirm-password"
            type="password"
            autoComplete="new-password"
            {...register("confirmPassword")}
          />

          {errors.confirmPassword && (
            <p className="field-error">
              {errors.confirmPassword.message}
            </p>
          )}
        </div>

        <button
          className="primary-button"
          type="submit"
          disabled={registerMutation.isPending}
        >
          {registerMutation.isPending ? (
            <>
              <LoaderCircle
                className="spinner"
                aria-hidden="true"
                size={18}
              />
              Creating account...
            </>
          ) : (
            <>
              Create account
              <ArrowRight aria-hidden="true" size={18} />
            </>
          )}
        </button>
      </form>

      <p className="auth-switch">
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </AuthLayout>
  );
}