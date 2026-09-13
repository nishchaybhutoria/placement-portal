import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RuleEditor, type Taxonomy } from "./RuleEditor";

/**
 * The controls themselves, not the compiler: a clause the palette offers but
 * whose control cannot be operated is the same gap as having no clause at all.
 */

const TAXONOMY: Taxonomy = { programs: [], branches: [], minors: [] };

function editor() {
  const onChange = vi.fn();
  render(
    <RuleEditor rule={null} taxonomy={TAXONOMY} disabled={false} onChange={onChange} />,
  );
  return onChange;
}

describe("RuleEditor controls", () => {
  it("writes a gender clause from the palette and its checkboxes", () => {
    const onChange = editor();
    fireEvent.click(screen.getByRole("button", { name: "Gender" }));
    // Added but unanswered, the draft is incomplete and nothing is saved.
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Complete or remove every unfinished condition before saving.",
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "Female" }));
    expect(onChange).toHaveBeenLastCalledWith({
      field: "gender",
      op: "eq",
      value: "female",
    });

    fireEvent.click(screen.getByRole("checkbox", { name: "Other" }));
    expect(onChange).toHaveBeenLastCalledWith({
      field: "gender",
      op: "in",
      value: ["female", "other"],
    });
  });

  it("writes school marks and a nationality from their own controls", () => {
    const onChange = editor();
    fireEvent.click(screen.getByRole("button", { name: "Minimum 10th percentage" }));
    fireEvent.change(screen.getByRole("spinbutton", { name: "Minimum 10th percentage" }), {
      target: { value: "60" },
    });
    expect(onChange).toHaveBeenLastCalledWith({
      field: "tenth_percent",
      op: "gte",
      value: 60,
    });

    fireEvent.click(screen.getByRole("button", { name: "Nationality" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Nationality" }), {
      target: { value: "IN" },
    });
    expect(onChange).toHaveBeenLastCalledWith({
      all: [
        { field: "tenth_percent", op: "gte", value: 60 },
        { field: "nationality", op: "eq", value: "IN" },
      ],
    });
  });

  it("opens a stored gender rule in the controls rather than in JSON", () => {
    render(
      <RuleEditor
        rule={{ field: "gender", op: "eq", value: "female" }}
        taxonomy={TAXONOMY}
        disabled={false}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("checkbox", { name: "Female" })).toBeChecked();
    expect(screen.queryByRole("textbox", { name: "Rule tree" })).not.toBeInTheDocument();
  });
});
