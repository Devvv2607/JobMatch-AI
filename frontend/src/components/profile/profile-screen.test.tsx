import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { FEEDBACK_KEY } from "@/lib/feedback";
import type { StoredProfile } from "@/lib/profile/model";
import { PROFILE_KEY, readProfile, writeProfile } from "@/lib/profile/store";
import { expectNoAxeViolations } from "@/test/axe";
import { expectFitsNarrowScreen } from "@/test/narrow";
import { router } from "@/test/router";

import { Profile } from "./profile-screen";

const SAVED: StoredProfile = {
  version: 1,
  profile: {
    skills: ["Python", "SQL", "Airflow"],
    years_experience: 3,
    preferences: { workplace: ["remote"], countries: ["IN"], seniority: ["junior", "mid"] },
  },
  rules: [
    { kind: "work_eligibility", country: "IN", strict: true },
    { kind: "posted_within_days", days: 30, strict: false },
  ],
  query: "Data engineering",
  updated_at: "2026-11-27T09:30:00.000Z",
};

function setup(saved: StoredProfile | null = SAVED) {
  if (saved) writeProfile(saved);
  const user = userEvent.setup();
  const view = render(<Profile />);
  return { user, ...view };
}

function stored() {
  const state = readProfile();
  if (state.status !== "ready") throw new Error(state.status);
  return state.stored;
}

const section = (name: string) => screen.getByRole("region", { name });

describe("Profile page", () => {
  it("shows the saved profile by section, with the storage note", () => {
    setup();
    expect(screen.getByText("Your profile stays in this browser until accounts arrive.")).toBeInTheDocument();
    expect(within(section("Skills")).getByRole("list", { name: "Your skills" })).toHaveTextContent("PythonSQLAirflow");
    expect(within(section("Level and experience")).getByText("Junior, Mid-level")).toBeInTheDocument();
    expect(within(section("Where and how you work")).getByText("India")).toBeInTheDocument();
    const rules = section("Dealbreakers");
    expect(within(rules).getByText("Where I can legally work")).toBeInTheDocument();
    expect(within(rules).getByText("Strict")).toBeInTheDocument();
    expect(within(rules).getByText("Posted in the last 30 days")).toBeInTheDocument();
  });

  it("edits a section and saves it, leaving the others alone", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Edit skills" }));
    const input = screen.getByRole("combobox", { name: "Your skills" });
    expect(input).toHaveFocus();
    await user.type(input, "postgres{Enter}");
    await user.click(screen.getByRole("button", { name: "Remove SQL" }));
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(within(section("Skills")).getByRole("status")).toHaveTextContent("Saved.");
    expect(screen.getByRole("button", { name: "Edit skills" })).toHaveFocus();
    expect(stored().profile.skills).toEqual(["Python", "Airflow", "PostgreSQL"]);
    expect(stored().rules).toEqual(SAVED.rules);
    expect(stored().query).toBe("Data engineering");
  });

  it("edits a dealbreaker's strict flag", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Edit dealbreakers" }));
    const [eligibilityStrict] = screen.getAllByRole("switch", { name: "Strict" });
    await user.click(eligibilityStrict!);
    await user.click(screen.getByRole("switch", { name: "Employment type" }));
    await user.click(screen.getByRole("checkbox", { name: "Full-time" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(stored().rules).toEqual([
      { kind: "work_eligibility", country: "IN", strict: false },
      { kind: "employment_type", allowed: ["full_time"], strict: false },
      { kind: "posted_within_days", days: 30, strict: false },
    ]);
  });

  it("Save checks the section and says what to fix", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Edit skills" }));
    for (const name of ["Python", "SQL", "Airflow"]) await user.click(screen.getByRole("button", { name: `Remove ${name}` }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText("Add at least one skill so we can find matches.")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Your skills" })).toHaveFocus();
    expect(stored().profile.skills).toEqual(SAVED.profile.skills);
  });

  it("Cancel throws the changes away", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Edit level and experience" }));
    const years = screen.getByRole("textbox", { name: "Years of experience" });
    await user.clear(years);
    await user.type(years, "9");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Edit level and experience" })).toHaveFocus();
    expect(within(section("Level and experience")).getByText("3 years")).toBeInTheDocument();
    expect(stored().profile.years_experience).toBe(3);
  });

  it("guards unsaved changes when leaving by a link or opening another section", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Edit level and experience" }));
    await user.type(screen.getByRole("textbox", { name: "Field" }), " and analytics");

    // A link: the dialog asks first; "Keep editing" stays put.
    await user.click(screen.getByRole("link", { name: "Matches" }));
    let dialog = screen.getByRole("alertdialog", { name: "Discard your changes?" });
    expect(dialog).toHaveTextContent("You changed your level and experience but haven’t saved.");
    expect(within(dialog).getByRole("button", { name: "Keep editing" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(router.push).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Field" })).toHaveValue("Data engineering and analytics");

    // Another section: discard, then that section opens.
    await user.click(screen.getByRole("button", { name: "Edit skills" }));
    dialog = screen.getByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Discard changes" }));
    expect(screen.getByRole("combobox", { name: "Your skills" })).toBeInTheDocument();
    expect(stored().query).toBe("Data engineering");

    // Leaving with the warning accepted goes where the link pointed.
    await user.type(screen.getByRole("combobox", { name: "Your skills" }), "dbt{Enter}");
    await user.click(screen.getByRole("link", { name: "Matches" }));
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(router.push).toHaveBeenCalledWith("/matches");
  });

  it("asks the browser to warn before closing the tab with unsaved changes", async () => {
    const { user } = setup();
    const quiet = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(quiet);
    expect(quiet.defaultPrevented).toBe(false);

    await user.click(screen.getByRole("button", { name: "Edit skills" }));
    await user.type(screen.getByRole("combobox", { name: "Your skills" }), "dbt{Enter}");
    const warned = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(warned);
    expect(warned.defaultPrevented).toBe(true);
  });

  it("Clear my data asks first, then removes the profile and the job marks", async () => {
    window.localStorage.setItem(FEEDBACK_KEY, JSON.stringify({ a: { job_id: "a", action: "saved" } }));
    const { user } = setup();
    const clear = screen.getByRole("button", { name: "Clear my data" });
    await user.click(clear);
    const dialog = screen.getByRole("alertdialog", { name: "Clear your data?" });
    expect(dialog).toHaveAccessibleDescription(/can’t be undone/);
    await user.click(within(dialog).getByRole("button", { name: "Keep my data" }));
    expect(window.localStorage.getItem(PROFILE_KEY)).not.toBeNull();
    expect(clear).toHaveFocus();

    await user.click(clear);
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Clear my data" }));
    expect(window.localStorage.getItem(PROFILE_KEY)).toBeNull();
    expect(window.localStorage.getItem(FEEDBACK_KEY)).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Your data was cleared from this browser.");
    expect(screen.getByRole("heading", { name: "No profile yet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Set up your profile" })).toHaveAttribute("href", "/onboarding");
  });

  it("keeps Tab inside the confirmation", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Clear my data" }));
    const dialog = screen.getByRole("alertdialog");
    const [keep, clear] = within(dialog).getAllByRole("button");
    expect(keep).toHaveFocus();
    await user.tab();
    expect(clear).toHaveFocus();
    await user.tab();
    expect(keep).toHaveFocus();
    await user.tab({ shift: true });
    expect(clear).toHaveFocus();
  });

  it("shows an empty state with no profile", async () => {
    const { container } = setup(null);
    expect(screen.getByRole("heading", { name: "No profile yet" })).toBeInTheDocument();
    await expectNoAxeViolations(container);
  });

  it("shows an error state when the saved copy is damaged", async () => {
    window.localStorage.setItem(PROFILE_KEY, "{oops");
    const { container } = setup(null);
    expect(screen.getByRole("alert")).toHaveTextContent("We couldn’t read your saved profile");
    expect(screen.getByRole("link", { name: "Set up your profile again" })).toBeInTheDocument();
    await expectNoAxeViolations(container);
  });

  it("shows the error state, not a crash, when the saved copy is damaged inside", async () => {
    window.localStorage.setItem(PROFILE_KEY, JSON.stringify({ ...SAVED, profile: { skills: "Python" }, updated_at: "" }));
    const { container } = setup(null);
    expect(screen.getByRole("alert")).toHaveTextContent("We couldn’t read your saved profile");
    expect(screen.getByRole("button", { name: "Clear my data" })).toBeInTheDocument();
    await expectNoAxeViolations(container);
  });

  it("follows changes made in another tab", () => {
    setup(null);
    act(() => {
      window.localStorage.setItem(PROFILE_KEY, JSON.stringify(SAVED));
      window.dispatchEvent(new StorageEvent("storage", { key: PROFILE_KEY }));
    });
    expect(screen.getByRole("region", { name: "Skills" })).toBeInTheDocument();
  });

  it("has no axe violations reading, editing every section, with errors, and in the dialog", async () => {
    const { user, container } = setup();
    await expectNoAxeViolations(container);
    for (const name of ["skills", "level and experience", "where and how you work", "dealbreakers"]) {
      await user.click(screen.getByRole("button", { name: `Edit ${name}` }));
      if (name === "dealbreakers") {
        for (const toggle of screen.getAllByRole("switch").filter((s) => s.getAttribute("aria-checked") === "false"))
          await user.click(toggle);
      }
      await expectNoAxeViolations(container);
      expectFitsNarrowScreen(container);
      await user.click(screen.getByRole("button", { name: "Cancel" }));
    }
    await user.click(screen.getByRole("button", { name: "Clear my data" }));
    await expectNoAxeViolations(container);
  });
});
