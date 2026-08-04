import {
  describe,
  expect,
  it,
} from "vitest";

import {
  loginSchema,
  registerSchema,
} from "./schemas";

describe("authentication schemas", () => {
  it("accepts a valid registration", () => {
    const result = registerSchema.safeParse({
      display_name: "Hamad Tarawa",
      email: "hamad@example.com",
      password: "secure-password-123",
      confirmPassword: "secure-password-123",
    });

    expect(result.success).toBe(true);
  });

  it("rejects mismatched passwords", () => {
    const result = registerSchema.safeParse({
      display_name: "Hamad Tarawa",
      email: "hamad@example.com",
      password: "secure-password-123",
      confirmPassword: "different-password",
    });

    expect(result.success).toBe(false);
  });

  it("rejects short registration passwords", () => {
    const result = registerSchema.safeParse({
      display_name: "Hamad Tarawa",
      email: "hamad@example.com",
      password: "short",
      confirmPassword: "short",
    });

    expect(result.success).toBe(false);
  });

  it("rejects invalid login email addresses", () => {
    const result = loginSchema.safeParse({
      email: "not-an-email",
      password: "secure-password-123",
    });

    expect(result.success).toBe(false);
  });
});