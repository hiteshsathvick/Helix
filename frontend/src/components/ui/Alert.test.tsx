import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Alert } from "./Alert";

describe("Alert", () => {
  it("renders error styling by default", () => {
    render(<Alert>Something went wrong</Alert>);
    expect(screen.getByText("Something went wrong")).toHaveClass("text-red-600");
  });

  it("renders success styling when requested", () => {
    render(<Alert variant="success">Saved</Alert>);
    expect(screen.getByText("Saved")).toHaveClass("text-green-700");
  });
});
