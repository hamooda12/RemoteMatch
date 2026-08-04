import { z } from "zod";

export const loginSchema = z.object({
  email: z
    .string()
    .trim()
    .email("Enter a valid email address."),
  password: z
    .string()
    .min(1, "Password is required."),
});

export const registerSchema = z
  .object({
    display_name: z
      .string()
      .trim()
      .min(2, "Display name must contain at least 2 characters.")
      .max(120, "Display name cannot exceed 120 characters."),
    email: z
      .string()
      .trim()
      .email("Enter a valid email address."),
    password: z
      .string()
      .min(12, "Password must contain at least 12 characters.")
      .max(128, "Password cannot exceed 128 characters."),
    confirmPassword: z.string(),
  })
  .refine(
    (values) => values.password === values.confirmPassword,
    {
      message: "Passwords do not match.",
      path: ["confirmPassword"],
    },
  );

export type LoginFormValues = z.infer<typeof loginSchema>;
export type RegisterFormValues = z.infer<
  typeof registerSchema
>;