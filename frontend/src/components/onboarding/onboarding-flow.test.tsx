import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { PROFILE_KEY, readProfile } from "@/lib/profile/store";
import { expectNoAxeViolations } from "@/test/axe";
import { expectFitsNarrowScreen } from "@/test/narrow";
import { router } from "@/test/router";
import { check, rulesItemSchema, schemaFor } from "@/test/schema";

import { Onboarding } from "./onboarding-flow";

function setup() {
  // applyAccept off, so a wrong file type reaches our own check, as it can in a browser.
  const user = userEvent.setup({ applyAccept: false });
  const view = render(<Onboarding />);
  return { user, ...view };
}

function stored() {
  const state = readProfile();
  if (state.status !== "ready") throw new Error(`no profile stored: ${state.status}`);
  return state.stored;
}

const heading = () => screen.getByRole("heading", { level: 1 });
const next = () => screen.getByRole("button", { name: "Next" });

describe("Onboarding", () => {
  it("can be completed with a resume, skills, level and dealbreakers, then opens the matches", async () => {
    const { user } = setup();
    expect(screen.getByText("Step 1 of 4")).toBeInTheDocument();
    expect(screen.getByText("Resume parsing is coming soon. For now, add your basics in the next steps.")).toBeInTheDocument();
    await user.upload(screen.getByLabelText("Resume"), new File(["%PDF-1.7"], "cv.pdf", { type: "application/pdf" }));
    expect(screen.getByRole("status")).toHaveTextContent("cv.pdf");
    await user.click(next());

    // Skills: autocomplete from the taxonomy, free text normalised like the backend.
    expect(heading()).toHaveTextContent("Your skills");
    expect(heading()).toHaveFocus();
    const skills = screen.getByRole("combobox", { name: "Your skills" });
    await user.type(skills, "postg");
    expect(screen.getByRole("option", { name: "PostgreSQL" })).toBeInTheDocument();
    await user.keyboard("{ArrowDown}{Enter}");
    await user.type(skills, "k8s{Enter}python, our own tool,");
    const chips = within(screen.getByRole("list", { name: "Your skills" }));
    expect(chips.getAllByRole("listitem").map((li) => li.textContent?.replace("×", ""))).toEqual([
      "PostgreSQL",
      "Kubernetes",
      "Python",
      "our own tool",
    ]);
    await user.click(screen.getByRole("button", { name: "Remove our own tool" }));
    await user.click(next());

    expect(screen.getByText("Step 3 of 4")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Junior" }));
    await user.click(screen.getByRole("checkbox", { name: "Mid-level" }));
    await user.type(screen.getByRole("textbox", { name: "Years of experience" }), "2.5");
    await user.type(screen.getByRole("textbox", { name: "Field" }), "Data engineering");
    await user.click(next());

    expect(heading()).toHaveTextContent("Where and how you work");
    await user.type(screen.getByRole("combobox", { name: "Countries you’d work in" }), "Ind");
    await user.click(screen.getByRole("option", { name: "India" }));
    await user.click(screen.getByRole("checkbox", { name: "Remote" }));
    await user.click(screen.getByRole("switch", { name: "Where I can legally work" }));
    // Turned on, it starts from the country already given.
    expect(screen.getByRole("combobox", { name: "Country" })).toHaveValue("IN");
    await user.click(screen.getByRole("switch", { name: "Minimum salary" }));
    // India first, so the minimum starts in lakhs, with the dollar figure beside it.
    expect(screen.getByRole("combobox", { name: "Currency" })).toHaveValue("INR");
    await user.type(screen.getByRole("textbox", { name: "At least" }), "8");
    expect(screen.getByText("≈ $8,517/yr")).toBeInTheDocument();
    const strict = screen.getAllByRole("switch", { name: "Strict" })[1]!;
    expect(strict).toHaveAccessibleDescription("Strict also hides jobs that don’t list a salary.");
    await user.click(strict);
    await user.click(screen.getByRole("button", { name: "Finish" }));

    expect(router.push).toHaveBeenCalledWith("/matches");
    const out = stored();
    expect(out.profile).toEqual({
      skills: ["PostgreSQL", "Kubernetes", "Python"],
      years_experience: 2.5,
      preferences: { workplace: ["remote"], countries: ["IN"], seniority: ["junior", "mid"] },
    });
    expect(out.query).toBe("Data engineering");
    expect(out.rules).toEqual([
      { kind: "work_eligibility", country: "IN", strict: false },
      { kind: "min_salary_usd", amount: 8517, strict: true },
    ]);
    expect(check(out.profile, schemaFor("SearchProfile"))).toEqual([]);
    for (const rule of out.rules) expect(check(rule, rulesItemSchema())).toEqual([]);
  });

  it("takes the minimum salary in US dollars too, converting what was typed", async () => {
    const { user } = setup();
    for (let i = 0; i < 3; i++) await user.click(screen.getByRole("button", { name: "Skip this step" }));
    await user.click(screen.getByRole("switch", { name: "Minimum salary" }));
    // No country yet, so dollars.
    const currency = screen.getByRole("combobox", { name: "Currency" });
    expect(currency).toHaveValue("USD");
    await user.type(screen.getByRole("textbox", { name: "At least" }), "40000");
    expect(screen.queryByText(/≈ \$/)).toBeNull();
    await user.selectOptions(currency, "INR");
    expect(screen.getByRole("textbox", { name: "At least" })).toHaveValue("37.57");
    expect(screen.getByText("≈ $39,998/yr")).toBeInTheDocument();
    await user.selectOptions(currency, "USD");
    expect(screen.getByRole("textbox", { name: "At least" })).toHaveValue("39998");
    await user.click(screen.getByRole("button", { name: "Finish" }));
    expect(stored().rules).toEqual([{ kind: "min_salary_usd", amount: 39998, strict: false }]);
  });

  it("offers strict only where it changes something", async () => {
    const { user } = setup();
    for (let i = 0; i < 3; i++) await user.click(screen.getByRole("button", { name: "Skip this step" }));
    for (const name of ["Level", "Employment type", "Companies to avoid"]) {
      await user.click(screen.getByRole("switch", { name }));
    }
    expect(screen.queryByRole("switch", { name: "Strict" })).toBeNull();
    for (const toggle of screen.getAllByRole("switch").filter((s) => s.getAttribute("aria-checked") === "false"))
      await user.click(toggle);
    expect(screen.getAllByRole("switch", { name: "Strict" })).toHaveLength(6);
  });

  it("every step can be skipped", async () => {
    const { user } = setup();
    for (const n of [1, 2, 3]) {
      expect(screen.getByText(`Step ${n} of 4`)).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Skip this step" }));
    }
    await user.click(screen.getByRole("button", { name: "Skip and finish" }));
    expect(router.push).toHaveBeenCalledWith("/matches");
    expect(stored()).toMatchObject({
      profile: { skills: [], years_experience: null, preferences: { workplace: [], countries: [], seniority: [] } },
      rules: [],
      query: null,
    });
  });

  it("Next asks for the step's minimum, in words, and moves focus to it", async () => {
    const { user } = setup();
    await user.click(next());
    await user.click(next());
    expect(screen.getByText("Add at least one skill so we can find matches.")).toBeInTheDocument();
    const skills = screen.getByRole("combobox", { name: "Your skills" });
    expect(skills).toHaveFocus();
    expect(skills).toHaveAttribute("aria-invalid", "true");
    expect(skills).toHaveAccessibleDescription(/Add at least one skill so we can find matches\./);
    await user.type(skills, "SQL{Enter}");
    expect(screen.queryByText("Add at least one skill so we can find matches.")).toBeNull();
  });

  it("going back and forth keeps every answer", async () => {
    const { user } = setup();
    await user.upload(screen.getByLabelText("Resume"), new File(["x"], "cv.docx", { type: "" }));
    await user.click(next());
    await user.type(screen.getByRole("combobox", { name: "Your skills" }), "dbt{Enter}");
    await user.click(next());
    await user.click(screen.getByRole("checkbox", { name: "Senior" }));
    await user.type(screen.getByRole("textbox", { name: "Years of experience" }), "7");
    await user.click(next());
    await user.click(screen.getByRole("switch", { name: "Companies to avoid" }));
    await user.type(screen.getByRole("combobox", { name: "Companies" }), "Initech{Enter}");

    for (const title of ["Level and experience", "Your skills", "Start with your resume"]) {
      await user.click(screen.getByRole("button", { name: "Back" }));
      expect(heading()).toHaveTextContent(title);
      expect(heading()).toHaveFocus();
    }
    expect(screen.getByRole("status")).toHaveTextContent("cv.docx");
    await user.click(next());
    expect(screen.getByRole("list", { name: "Your skills" })).toHaveTextContent("dbt");
    await user.click(next());
    expect(screen.getByRole("checkbox", { name: "Senior" })).toBeChecked();
    expect(screen.getByRole("textbox", { name: "Years of experience" })).toHaveValue("7");
    await user.click(next());
    expect(screen.getByRole("switch", { name: "Companies to avoid" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("list", { name: "Companies" })).toHaveTextContent("Initech");
  });

  it("checks the resume's type and size in the browser and keeps nothing it rejects", async () => {
    const { user } = setup();
    const input = screen.getByLabelText("Resume");
    await user.upload(input, new File(["png"], "photo.png", { type: "image/png" }));
    expect(screen.getByText("That’s a .png file. Choose a PDF or a Word (.docx) file.")).toBeInTheDocument();
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByRole("status")).toBeNull();

    const big = new File(["x"], "long-cv.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { value: 7.4 * 1024 * 1024 });
    await user.upload(input, big);
    expect(screen.getByText("That file is 7.4 MB. Choose one that’s 5 MB or smaller.")).toBeInTheDocument();

    const ok = new File(["x"], "cv.pdf", { type: "application/pdf" });
    Object.defineProperty(ok, "size", { value: 5 * 1024 * 1024 });
    await user.upload(input, ok);
    expect(screen.getByRole("status")).toHaveTextContent("cv.pdf (5.0 MB) looks fine. Nothing was uploaded.");
    expect(input).not.toHaveAttribute("aria-invalid");
  });

  it("won't finish while a skipped step holds something invalid, and says where", async () => {
    const { user } = setup();
    await user.click(next());
    await user.click(screen.getByRole("button", { name: "Skip this step" }));
    await user.type(screen.getByRole("textbox", { name: "Years of experience" }), "seventy");
    await user.click(screen.getByRole("button", { name: "Skip this step" }));
    await user.click(screen.getByRole("button", { name: "Finish" }));
    expect(router.push).not.toHaveBeenCalled();
    expect(window.localStorage.getItem(PROFILE_KEY)).toBeNull();
    expect(heading()).toHaveTextContent("Level and experience");
    expect(screen.getByRole("alert")).toHaveTextContent("One answer needs fixing");
    expect(screen.getByRole("textbox", { name: "Years of experience" })).toHaveFocus();
  });

  it("works from the keyboard alone", async () => {
    const { user } = setup();
    // Skip link, logo, resume input, then Skip, then Next.
    await user.tab();
    expect(screen.getByRole("link", { name: "Skip to the form" })).toHaveFocus();
    await user.tab();
    await user.tab();
    expect(screen.getByLabelText("Resume")).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Skip this step" })).toHaveFocus();
    await user.tab();
    await user.keyboard("{Enter}");
    expect(heading()).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("combobox", { name: "Your skills" })).toHaveFocus();
    await user.keyboard("Python{Enter}");
    // Enter on an empty field submits the step.
    await user.keyboard("{Enter}");
    expect(heading()).toHaveTextContent("Level and experience");
    await user.tab();
    await user.keyboard(" ");
    expect(screen.getByRole("checkbox", { name: "Intern" })).toBeChecked();
  });

  it.each([0, 1, 2, 3])("step %i has no axe violations, errors shown too", async (step) => {
    const { user, container } = setup();
    for (let i = 0; i < step; i++) await user.click(screen.getByRole("button", { name: "Skip this step" }));
    if (step === 3) {
      // Every dealbreaker on, so every control is checked.
      for (const toggle of screen.getAllByRole("switch")) await user.click(toggle);
    }
    await expectNoAxeViolations(container);
    expectFitsNarrowScreen(container);
    await user.click(screen.getByRole("button", { name: step === 3 ? "Finish" : "Next" }));
    await expectNoAxeViolations(container);
  });
});
