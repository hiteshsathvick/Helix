import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Button } from "./Button";

describe("Button", () => {
  it("renders its children and responds to clicks", () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Save</Button>);

    fireEvent.click(screen.getByText("Save"));

    expect(onClick).toHaveBeenCalledOnce();
  });

  it("does not fire onClick while disabled", () => {
    const onClick = vi.fn();
    render(
      <Button onClick={onClick} disabled>
        Save
      </Button>
    );

    fireEvent.click(screen.getByText("Save"));

    expect(onClick).not.toHaveBeenCalled();
  });

  it("applies variant-specific styling", () => {
    render(<Button variant="danger">Delete</Button>);
    expect(screen.getByText("Delete")).toHaveClass("text-red-600");
  });
});
