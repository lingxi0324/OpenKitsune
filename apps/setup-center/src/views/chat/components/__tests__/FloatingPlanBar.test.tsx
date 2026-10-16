import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FloatingPlanBar } from "../FloatingPlanBar";

describe("FloatingPlanBar step actions", () => {
  it("emits skip for the active step from the collapsed bar", () => {
    const onStepAction = vi.fn();

    render(
      <FloatingPlanBar
        plan={{
          id: "plan-1",
          taskSummary: "Ship",
          status: "in_progress",
          steps: [
            { id: "s1", description: "Inspect files", status: "completed" },
            { id: "s2", description: "Patch UI", status: "in_progress" },
          ],
        }}
        onStepAction={onStepAction}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "跳过此步" }));

    expect(onStepAction).toHaveBeenCalledWith("skip", 1, "Patch UI");
  });
});
