import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError, ForbiddenError } from "@/api/problem";
import { ErrorState } from "./states";
import { DataTable } from "./table";

describe("ErrorState", () => {
  it("renders every structured 403 reason and a route back", () => {
    render(
      <ErrorState
        error={new ForbiddenError({
          type: "about:blank",
          title: "Forbidden",
          status: 403,
          reasons: [
            { code: "cycle_archived", human: "This cycle is archived." },
            { code: "unknown", human: "You do not coordinate this cycle." },
          ],
        })}
      />,
    );

    expect(screen.getByText("You cannot access this page")).toBeInTheDocument();
    expect(screen.getByText("This cycle is archived.")).toBeInTheDocument();
    expect(screen.getByText("You do not coordinate this cycle.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to home" })).toHaveAttribute("href", "/");
  });

  it("turns a problem+json 404 into human page copy", () => {
    render(
      <ErrorState
        error={new ApiError({
          type: "about:blank",
          title: "Not found",
          status: 404,
          detail: "No job exists with that id.",
        })}
      />,
    );

    expect(screen.getByText("Page not found")).toBeInTheDocument();
    expect(screen.getByText("No job exists with that id.")).toBeInTheDocument();
  });

  it("does not expose raw local exception text", () => {
    render(<ErrorState error={new Error("internal parser stack detail")} />);
    expect(screen.queryByText(/internal parser/)).not.toBeInTheDocument();
    expect(screen.getByText("The page could not be displayed. Please try again.")).toBeInTheDocument();
  });
});

describe("DataTable keyboard rows", () => {
  it("activates clickable rows with Enter", () => {
    const onRowClick = vi.fn();
    render(
      <DataTable
        columns={[{ key: "name", header: "Name", cell: (row: { id: string }) => row.id }]}
        rows={[{ id: "student-1" }]}
        rowKey={(row) => row.id}
        onRowClick={onRowClick}
      />,
    );

    const row = screen.getByText("student-1").closest("tr");
    expect(row).toHaveAttribute("tabindex", "0");
    fireEvent.keyDown(row!, { key: "Enter" });
    expect(onRowClick).toHaveBeenCalledWith({ id: "student-1" });
  });
});
