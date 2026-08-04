import {
  describe,
  expect,
  it,
} from "vitest";

import { profileFormSchema } from "./profile-schema";

const validProfile = {
  location: "Bethlehem, Palestine",
  timezone: "Asia/Hebron",
  targetRoles: "Backend Engineer, Python Developer",
  experienceLevel: "junior",
  minimumSalary: "30000",
  salaryCurrency: "USD",
  excludedTechnologies: "PHP, Ruby",
  availabilityStart: "Immediately",
  weeklyHours: "40",
};

describe("profile form schema", () => {
  it("accepts valid candidate preferences", () => {
    const result =
      profileFormSchema.safeParse(validProfile);

    expect(result.success).toBe(true);
  });

  it("requires currency with minimum salary", () => {
    const result = profileFormSchema.safeParse({
      ...validProfile,
      salaryCurrency: "",
    });

    expect(result.success).toBe(false);
  });

  it("rejects more than 20 target roles", () => {
    const targetRoles = Array.from(
      {
        length: 21,
      },
      (_, index) => `Role ${index}`,
    ).join(", ");

    const result = profileFormSchema.safeParse({
      ...validProfile,
      targetRoles,
    });

    expect(result.success).toBe(false);
  });

  it("rejects invalid weekly hours", () => {
    const result = profileFormSchema.safeParse({
      ...validProfile,
      weeklyHours: "169",
    });

    expect(result.success).toBe(false);
  });

  it("allows optional salary and availability", () => {
    const result = profileFormSchema.safeParse({
      ...validProfile,
      minimumSalary: "",
      salaryCurrency: "",
      availabilityStart: "",
      weeklyHours: "",
    });

    expect(result.success).toBe(true);
  });
});