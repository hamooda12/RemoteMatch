import { zodResolver } from "@hookform/resolvers/zod";
import {
  CheckCircle2,
  LoaderCircle,
  Save,
  UserRound,
} from "lucide-react";
import { useEffect } from "react";
import { useForm } from "react-hook-form";

import {
  profileFormSchema,
  type ProfileFormValues,
} from "../features/profile/profile-schema";
import {
  useProfile,
  useSaveProfile,
} from "../features/profile/use-profile";
import type {
  ExperienceLevel,
  ProfileUpsert,
} from "../features/profile/types";

const experienceOptions: Array<{
  value: ExperienceLevel;
  label: string;
}> = [
  {
    value: "no_experience",
    label: "No professional experience",
  },
  {
    value: "internship",
    label: "Internship",
  },
  {
    value: "entry_level",
    label: "Entry level",
  },
  {
    value: "junior",
    label: "Junior",
  },
  {
    value: "mid_level",
    label: "Mid level",
  },
  {
    value: "senior",
    label: "Senior",
  },
];

function parseCommaSeparatedList(value: string): string[] {
  const seenValues = new Set<string>();

  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => {
      if (!item) {
        return false;
      }

      const comparisonValue = item.toLowerCase();

      if (seenValues.has(comparisonValue)) {
        return false;
      }

      seenValues.add(comparisonValue);
      return true;
    });
}

const emptyFormValues: ProfileFormValues = {
  location: "",
  timezone: "Asia/Hebron",
  targetRoles: "",
  experienceLevel: "",
  minimumSalary: "",
  salaryCurrency: "",
  excludedTechnologies: "",
  availabilityStart: "",
  weeklyHours: "",
};

export function ProfilePage() {
  const profileQuery = useProfile();
  const saveProfileMutation = useSaveProfile();

  const {
    register,
    reset,
    handleSubmit,
    formState: { errors, isDirty },
  } = useForm<ProfileFormValues>({
    resolver: zodResolver(profileFormSchema),
    defaultValues: emptyFormValues,
  });

  useEffect(() => {
    if (profileQuery.data === undefined) {
      return;
    }

    const profile = profileQuery.data;

    if (profile === null) {
      reset(emptyFormValues);
      return;
    }

    reset({
      location: profile.location ?? "",
      timezone: profile.timezone,
      targetRoles: profile.target_roles.join(", "),
      experienceLevel: profile.experience_level ?? "",
      minimumSalary:
        profile.minimum_salary !== null
          ? String(profile.minimum_salary)
          : "",
      salaryCurrency: profile.salary_currency ?? "",
      excludedTechnologies:
        profile.excluded_technologies.join(", "),
      availabilityStart:
        profile.availability.start_date ?? "",
      weeklyHours:
        profile.availability.weekly_hours ?? "",
    });
  }, [profileQuery.data, reset]);

  async function submitProfile(
    values: ProfileFormValues,
  ): Promise<void> {
    const availability = {
      ...(profileQuery.data?.availability ?? {}),
    };

    if (values.availabilityStart) {
      availability.start_date = values.availabilityStart;
    } else {
      delete availability.start_date;
    }

    if (values.weeklyHours) {
      availability.weekly_hours = values.weeklyHours;
    } else {
      delete availability.weekly_hours;
    }

    const payload: ProfileUpsert = {
      location: values.location || null,
      timezone: values.timezone,
      target_roles: parseCommaSeparatedList(
        values.targetRoles,
      ),
      experience_level:
        values.experienceLevel === ""
          ? null
          : values.experienceLevel,
      minimum_salary:
        values.minimumSalary === ""
          ? null
          : Number(values.minimumSalary),
      salary_currency:
        values.salaryCurrency === ""
          ? null
          : values.salaryCurrency.toUpperCase(),
      excluded_technologies: parseCommaSeparatedList(
        values.excludedTechnologies,
      ),
      availability,
    };

    try {
      const savedProfile =
        await saveProfileMutation.mutateAsync(payload);

      reset({
        location: savedProfile.location ?? "",
        timezone: savedProfile.timezone,
        targetRoles: savedProfile.target_roles.join(", "),
        experienceLevel:
          savedProfile.experience_level ?? "",
        minimumSalary:
          savedProfile.minimum_salary !== null
            ? String(savedProfile.minimum_salary)
            : "",
        salaryCurrency:
          savedProfile.salary_currency ?? "",
        excludedTechnologies:
          savedProfile.excluded_technologies.join(", "),
        availabilityStart:
          savedProfile.availability.start_date ?? "",
        weeklyHours:
          savedProfile.availability.weekly_hours ?? "",
      });
    } catch {
      return;
    }
  }

  return (
    <main className="page-content">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Candidate preferences</p>
          <h1>Your profile</h1>
          <p>
            Define the roles, experience, salary, and working
            preferences used by the matching engine.
          </p>
        </div>

        {profileQuery.data && (
          <div className="profile-status">
            <CheckCircle2 aria-hidden="true" size={18} />
            Profile created
          </div>
        )}
      </section>

      {profileQuery.isPending && (
        <div className="page-state" aria-busy="true">
          <LoaderCircle
            className="spinner"
            aria-hidden="true"
            size={30}
          />
          <p>Loading your profile...</p>
        </div>
      )}

      {profileQuery.isError && (
        <div
          className="page-state page-state-error"
          role="alert"
        >
          <h2>Profile could not be loaded</h2>
          <p>
            Check the API connection and try again.
          </p>

          <button
            className="secondary-button"
            type="button"
            onClick={() => profileQuery.refetch()}
          >
            Try again
          </button>
        </div>
      )}

      {!profileQuery.isPending &&
        !profileQuery.isError && (
          <form
            className="profile-form"
            onSubmit={handleSubmit(submitProfile)}
            noValidate
          >
            <section className="profile-form-section">
              <div className="form-section-heading">
                <UserRound aria-hidden="true" size={21} />

                <div>
                  <h2>Candidate information</h2>
                  <p>
                    Your location and preferred working timezone.
                  </p>
                </div>
              </div>

              <div className="profile-field-grid">
                <div className="form-field">
                  <label htmlFor="profile-location">
                    Location
                  </label>

                  <input
                    id="profile-location"
                    type="text"
                    placeholder="Bethlehem, Palestine"
                    {...register("location")}
                  />

                  {errors.location && (
                    <p className="field-error">
                      {errors.location.message}
                    </p>
                  )}
                </div>

                <div className="form-field">
                  <label htmlFor="profile-timezone">
                    IANA timezone
                  </label>

                  <input
                    id="profile-timezone"
                    type="text"
                    list="timezone-options"
                    placeholder="Asia/Hebron"
                    {...register("timezone")}
                  />

                  <datalist id="timezone-options">
                    <option value="Asia/Hebron" />
                    <option value="Asia/Jerusalem" />
                    <option value="Europe/London" />
                    <option value="Europe/Berlin" />
                    <option value="America/New_York" />
                    <option value="UTC" />
                  </datalist>

                  {errors.timezone && (
                    <p className="field-error">
                      {errors.timezone.message}
                    </p>
                  )}
                </div>
              </div>
            </section>

            <section className="profile-form-section">
              <div className="form-section-heading">
                <UserRound aria-hidden="true" size={21} />

                <div>
                  <h2>Career targets</h2>
                  <p>
                    Add roles and technologies separated by
                    commas.
                  </p>
                </div>
              </div>

              <div className="form-field">
                <label htmlFor="target-roles">
                  Target roles
                </label>

                <input
                  id="target-roles"
                  type="text"
                  placeholder="Backend Engineer, Python Developer, DevOps Engineer"
                  {...register("targetRoles")}
                />

                <p className="field-hint">
                  Add up to 20 roles separated by commas.
                </p>

                {errors.targetRoles && (
                  <p className="field-error">
                    {errors.targetRoles.message}
                  </p>
                )}
              </div>

              <div className="profile-field-grid">
                <div className="form-field">
                  <label htmlFor="experience-level">
                    Experience level
                  </label>

                  <select
                    id="experience-level"
                    {...register("experienceLevel")}
                  >
                    <option value="">Not specified</option>

                    {experienceOptions.map((option) => (
                      <option
                        key={option.value}
                        value={option.value}
                      >
                        {option.label}
                      </option>
                    ))}
                  </select>

                  {errors.experienceLevel && (
                    <p className="field-error">
                      {errors.experienceLevel.message}
                    </p>
                  )}
                </div>

                <div className="form-field">
                  <label htmlFor="excluded-technologies">
                    Excluded technologies
                  </label>

                  <input
                    id="excluded-technologies"
                    type="text"
                    placeholder="PHP, Ruby"
                    {...register("excludedTechnologies")}
                  />

                  {errors.excludedTechnologies && (
                    <p className="field-error">
                      {
                        errors.excludedTechnologies
                          .message
                      }
                    </p>
                  )}
                </div>
              </div>
            </section>

            <section className="profile-form-section">
              <div className="form-section-heading">
                <UserRound aria-hidden="true" size={21} />

                <div>
                  <h2>Salary and availability</h2>
                  <p>
                    Optional expectations used by the matching
                    engine.
                  </p>
                </div>
              </div>

              <div className="profile-field-grid">
                <div className="form-field">
                  <label htmlFor="minimum-salary">
                    Minimum salary
                  </label>

                  <input
                    id="minimum-salary"
                    type="number"
                    min="0"
                    step="0.01"
                    placeholder="30000"
                    {...register("minimumSalary")}
                  />

                  {errors.minimumSalary && (
                    <p className="field-error">
                      {errors.minimumSalary.message}
                    </p>
                  )}
                </div>

                <div className="form-field">
                  <label htmlFor="salary-currency">
                    Currency
                  </label>

                  <input
                    id="salary-currency"
                    type="text"
                    maxLength={3}
                    placeholder="USD"
                    {...register("salaryCurrency")}
                  />

                  {errors.salaryCurrency && (
                    <p className="field-error">
                      {errors.salaryCurrency.message}
                    </p>
                  )}
                </div>

                <div className="form-field">
                  <label htmlFor="availability-start">
                    Available from
                  </label>

                  <input
                    id="availability-start"
                    type="text"
                    placeholder="Immediately"
                    {...register("availabilityStart")}
                  />

                  {errors.availabilityStart && (
                    <p className="field-error">
                      {errors.availabilityStart.message}
                    </p>
                  )}
                </div>

                <div className="form-field">
                  <label htmlFor="weekly-hours">
                    Weekly hours
                  </label>

                  <input
                    id="weekly-hours"
                    type="number"
                    min="1"
                    max="168"
                    placeholder="40"
                    {...register("weeklyHours")}
                  />

                  {errors.weeklyHours && (
                    <p className="field-error">
                      {errors.weeklyHours.message}
                    </p>
                  )}
                </div>
              </div>
            </section>

            {saveProfileMutation.error && (
              <div className="form-error" role="alert">
                {saveProfileMutation.error instanceof Error
                  ? saveProfileMutation.error.message
                  : "Profile could not be saved."}
              </div>
            )}

            {saveProfileMutation.isSuccess &&
              !isDirty && (
                <div className="success-message" role="status">
                  Profile saved successfully.
                </div>
              )}

            <div className="profile-form-actions">
              <button
                className="primary-button"
                type="submit"
                disabled={saveProfileMutation.isPending}
              >
                {saveProfileMutation.isPending ? (
                  <>
                    <LoaderCircle
                      className="spinner"
                      aria-hidden="true"
                      size={18}
                    />
                    Saving...
                  </>
                ) : (
                  <>
                    <Save aria-hidden="true" size={18} />
                    Save profile
                  </>
                )}
              </button>
            </div>
          </form>
        )}
    </main>
  );
}