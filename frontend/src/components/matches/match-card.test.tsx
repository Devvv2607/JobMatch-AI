import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { buildFixtures } from "@/lib/data/fixtures";
import { FEEDBACK_KEY } from "@/lib/feedback";
import { expectNoAxeViolations } from "@/test/axe";

import { MatchCard } from "./match-card";

const data = buildFixtures();
const [kestrel, tallgrass, brightwater, pinecrest] = data.response.results;

function renderCard(index: number) {
  const result = data.response.results[index]!;
  return render(
    <MatchCard result={result} extras={data.extras[result.job.id]} sentence={data.sentences[result.job.id]} />,
  );
}

function stored() {
  return JSON.parse(window.localStorage.getItem(FEEDBACK_KEY) ?? "{}");
}

describe("MatchCard", () => {
  it("builds 'why it matches' and gaps from the structured explanation", () => {
    renderCard(0);
    const why = screen.getByRole("region", { name: /^Why it matches/ });
    expect(within(why).getByText(/5 of 6 listed skills/)).toBeInTheDocument();
    // Matched preferences collapse into one line; skills and experience stay separate.
    expect(within(why).getByText("Fits your preferences: Hybrid · India · Mid-level")).toBeInTheDocument();
    expect(within(why).queryByText(/as you prefer/)).toBeNull();
    expect(within(why).getAllByRole("listitem")).toHaveLength(3);
    const gaps = screen.getByRole("region", { name: /^Gaps/ });
    expect(within(gaps).getByText("Kafka")).toBeInTheDocument();
    expect(screen.getByText("₹18–24 LPA")).toBeInTheDocument();
  });

  it("shows the LLM sentence only when its status is ok", () => {
    const first = renderCard(0);
    expect(screen.getByText(/covers most of this role/)).toBeInTheDocument();
    first.unmount();
    const { container } = renderCard(1);
    expect(data.sentences[tallgrass!.job.id]!.status).toBe("dropped");
    expect(container.querySelector("p.italic")).toBeNull();
  });

  it("marks snippets, staffing agencies, missing salary and reposts as facts", () => {
    renderCard(2);
    expect(brightwater!.job.source).toBe("adzuna");
    expect(screen.getByText("Short description from source")).toBeInTheDocument();
    expect(screen.getByText("Posted by a staffing agency")).toBeInTheDocument();
    expect(screen.getByText("Salary not stated")).toBeInTheDocument();
    expect(screen.getByText("Posted 11 months ago · reposted 3 times · seen at 2 sources")).toBeInTheDocument();
    expect(screen.queryByText(/ghost/i)).toBeNull();
    expect(screen.queryByRole("button", { name: /full description/ })).toBeNull();
  });

  it("shows worldwide eligibility, USD salary and a monogram when there is no logo", () => {
    renderCard(1);
    expect(screen.getByText("Open to applicants worldwide")).toBeInTheDocument();
    expect(screen.getByText("$140,000–$170,000 a year")).toBeInTheDocument();
    expect(screen.getByTestId("company-monogram")).toHaveTextContent("T");
  });

  it("collapses a long description behind a toggle", async () => {
    const user = userEvent.setup();
    renderCard(0);
    const toggle = screen.getByRole("button", { name: "Show full description" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(screen.getByRole("button", { name: "Show less" })).toHaveAttribute("aria-expanded", "true");
  });

  it("saves to localStorage in the feedback API shape", async () => {
    const user = userEvent.setup();
    renderCard(0);
    await user.click(screen.getByRole("button", { name: /^Save/ }));
    expect(screen.getByRole("button", { name: /^Saved/ })).toHaveAttribute("aria-pressed", "true");
    const row = stored()[kestrel!.job.id];
    expect(row).toMatchObject({ job_id: kestrel!.job.id, action: "saved", reason: null, note: null });
    expect(typeof row.created_at).toBe("string");
  });

  it("hides a job with a reason, and undo brings it back", async () => {
    const user = userEvent.setup();
    renderCard(3);
    await user.click(screen.getByRole("button", { name: /^Not for me/ }));
    const hide = screen.getByRole("button", { name: "Hide this job" });
    expect(hide).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: "Wrong level" }));
    await user.click(hide);
    expect(screen.getByText(/wrong level/)).toBeInTheDocument();
    expect(stored()[pinecrest!.job.id]).toMatchObject({ action: "dismissed", reason: "wrong_level", note: null });
    await user.click(screen.getByRole("button", { name: /Undo/ }));
    expect(screen.getByRole("heading", { name: /Data Engineering Intern/ })).toBeInTheDocument();
    expect(stored()[pinecrest!.job.id]).toBeUndefined();
  });

  it("moves focus to Undo after hiding, and back to the title after Undo", async () => {
    const user = userEvent.setup();
    renderCard(3);
    await user.click(screen.getByRole("button", { name: /^Not for me/ }));
    await user.click(screen.getByRole("radio", { name: "Wrong level" }));
    await user.click(screen.getByRole("button", { name: "Hide this job" }));
    const undo = screen.getByRole("button", { name: /Undo/ });
    expect(undo).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("heading", { name: /Data Engineering Intern/ })).toHaveFocus();
  });

  it("keeps a note only for 'something else'", async () => {
    const user = userEvent.setup();
    renderCard(3);
    await user.click(screen.getByRole("button", { name: /^Not for me/ }));
    await user.click(screen.getByRole("radio", { name: "Something else" }));
    await user.type(screen.getByRole("textbox", { name: /What’s wrong with it/ }), "Too far to commute");
    await user.click(screen.getByRole("button", { name: "Hide this job" }));
    expect(stored()[pinecrest!.job.id]).toMatchObject({ reason: "other", note: "Too far to commute" });
  });

  it("Escape closes the reason panel and returns focus to its button", async () => {
    const user = userEvent.setup();
    renderCard(0);
    const trigger = screen.getByRole("button", { name: /^Not for me/ });
    await user.click(trigger);
    expect(screen.getByRole("radio", { name: "Wrong level" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("group")).toBeNull();
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("shows the API's age note for a stale posting, quietly, and no computed age", async () => {
    const stale = {
      ...brightwater!,
      job: { ...brightwater!.job, stale_posting: true, age_note: "posted over a year ago" },
    };
    const { container } = render(<MatchCard result={stale} extras={data.extras[stale.job.id]} />);
    const note = screen.getByText("posted over a year ago", { exact: false });
    expect(note.closest("p")).toHaveTextContent("Old posting: posted over a year ago");
    // Muted, not the error colour.
    expect(note.closest("p")!.className).toContain("text-muted");
    expect(note.closest("p")!.className).not.toMatch(/danger/);
    // The age comes from the API only: the facts line keeps the other facts.
    expect(screen.getByText("reposted 3 times · seen at 2 sources")).toBeInTheDocument();
    expect(screen.queryByText(/Posted \d+ (months|years) ago/)).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("shows no age note when the posting isn't stale", () => {
    renderCard(2);
    expect(brightwater!.job.stale_posting).toBe(false);
    expect(screen.queryByText(/Old posting/)).toBeNull();
    expect(screen.getByText(/^Posted 11 months ago/)).toBeInTheDocument();
  });

  it("has no axe violations, with the reason panel open too", async () => {
    const user = userEvent.setup();
    const { container } = renderCard(2);
    await expectNoAxeViolations(container);
    await user.click(screen.getByRole("button", { name: /^Not for me/ }));
    await expectNoAxeViolations(container);
  });
});
