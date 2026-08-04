import { z } from "zod";

function countCommaSeparatedValues(value: string): number {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean).length;
}

export const profileFormSchema = z
  .object({
    location: z
      .string()
      .trim()
      .max(120, "Location cannot exceed 120 characters."),
    timezone: z
      .string()
      .trim()
      .min(1, "Timezone is required.")
      .max(50, "Timezone cannot exceed 50 characters."),
    targetRoles: z
      .string()
      .refine(
        (value) => countCommaSeparatedValues(value) <= 20,
        "You can add at most 20 target roles.",
      ),
    experienceLevel: z.enum([
      "",
      "no_experience",
      "internship",
      "entry_level",
      "junior",
      "mid_level",
      "senior",
    ]),
    minimumSalary: z
      .string()
      .trim()
      .refine(
        (value) =>
          value === "" ||
          (!Number.isNaN(Number(value)) &&
            Number(value) >= 0),
        "Minimum salary must be zero or greater.",
      ),
    salaryCurrency: z
      .string()
      .trim()
      .refine(
        (value) =>
          value === "" || /^[A-Za-z]{3}$/.test(value),
        "Use a three-letter currency code such as USD.",
      ),
    excludedTechnologies: z
      .string()
      .refine(
        (value) => countCommaSeparatedValues(value) <= 30,
        "You can exclude at most 30 technologies.",
      ),
    availabilityStart: z
      .string()
      .trim()
      .max(100, "Availability cannot exceed 100 characters."),
    weeklyHours: z
      .string()
      .trim()
      .refine(
        (value) =>
          value === "" ||
          (!Number.isNaN(Number(value)) &&
            Number(value) >= 1 &&
            Number(value) <= 168),
        "Weekly hours must be between 1 and 168.",
      ),
  })
  .refine(
    (values) =>
      values.minimumSalary === "" ||
      values.salaryCurrency !== "",
    {
      message:
        "Currency is required when minimum salary is provided.",
      path: ["salaryCurrency"],
    },
  );

export type ProfileFormValues = z.infer<
  typeof profileFormSchema
>;