import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import "../../../../i18n";
import { AgentMenuItem } from "../AgentMenuItem";
import { AgentMenuHoverContext } from "../AgentMenuScrollArea";

afterEach(() => { cleanup(); vi.useRealTimers(); });

function setup(description = "Full agent introduction") {
  const onSelect = vi.fn();
  const result = render(<AgentMenuItem name="Writer" description={description}
    icon={<span>*</span>} selected={false} onSelect={onSelect} container={document.body} />);
  return { ...result, onSelect, select: screen.getByRole("button", { name: /Writer/, pressed: false }) };
}

it("omits the introduction and info button when the description is blank", () => {
  const { select, onSelect } = setup("  ");
  expect(screen.getAllByRole("button")).toHaveLength(1);
  fireEvent.click(select);
  expect(onSelect).toHaveBeenCalledOnce();
});

it("opens the full introduction from the info button without selecting the agent", () => {
  const { onSelect } = setup();
  expect(screen.queryByText("Full agent introduction")).not.toBeInTheDocument();
  fireEvent.click(screen.getAllByRole("button")[1]);
  expect(screen.getByText("Full agent introduction")).toBeInTheDocument();
  expect(onSelect).not.toHaveBeenCalled();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByText("Full agent introduction")).not.toBeInTheDocument();
});

it("keeps the introduction open while keyboard focus moves to the info button", async () => {
  vi.useFakeTimers();
  const { select } = setup();
  act(() => select.focus());
  expect(screen.getByText("Full agent introduction")).toBeInTheDocument();
  act(() => screen.getAllByRole("button")[1].focus());
  await act(async () => { await vi.advanceTimersByTimeAsync(500); });
  expect(screen.getByText("Full agent introduction")).toBeInTheDocument();
  act(() => screen.getAllByRole("button")[1].blur());
  expect(screen.queryByText("Full agent introduction")).not.toBeInTheDocument();
});

it("delays hover details and allows moving into the card to read them", async () => {
  vi.useFakeTimers();
  const { select } = setup();
  fireEvent.pointerEnter(select.parentElement!, { pointerType: "mouse" });
  await act(async () => { await vi.advanceTimersByTimeAsync(299); });
  expect(screen.queryByText("Full agent introduction")).not.toBeInTheDocument();
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  const card = screen.getByText("Full agent introduction").parentElement!;
  fireEvent.pointerLeave(select.parentElement!, { pointerType: "mouse" });
  fireEvent.pointerEnter(card, { pointerType: "mouse" });
  await act(async () => { await vi.advanceTimersByTimeAsync(500); });
  expect(screen.getByText("Full agent introduction")).toBeInTheDocument();
  fireEvent.pointerLeave(card, { pointerType: "mouse" });
  await act(async () => { await vi.advanceTimersByTimeAsync(150); });
  expect(screen.queryByText("Full agent introduction")).not.toBeInTheDocument();
});

it("replaces stationary-pointer hover details and cancels stale timers when scrolling across rows", async () => {
  vi.useFakeTimers();
  const items = ["First", "Second", "Blank"].map(name => (
    <AgentMenuItem key={name} name={name} description={name === "Blank" ? "" : `${name} introduction`}
      icon="*" selected={false} onSelect={() => {}} container={document.body} />
  ));
  const renderHover = (row: HTMLElement | null) => (
    <AgentMenuHoverContext.Provider value={row}>{items}</AgentMenuHoverContext.Provider>
  );
  const view = render(renderHover(null));
  const rows = Array.from(view.container.querySelectorAll<HTMLElement>(".chatAgentMenuItem"));
  view.rerender(renderHover(rows[0]));
  await act(async () => { await vi.advanceTimersByTimeAsync(300); });
  expect(screen.getByText("First introduction")).toBeInTheDocument();
  view.rerender(renderHover(rows[1]));
  expect(screen.queryByText("First introduction")).not.toBeInTheDocument();
  expect(rows[1]).toHaveAttribute("data-hovered", "true");
  await act(async () => { await vi.advanceTimersByTimeAsync(300); });
  expect(screen.getByText("Second introduction")).toBeInTheDocument();
  view.rerender(renderHover(rows[0]));
  await act(async () => { await vi.advanceTimersByTimeAsync(100); });
  view.rerender(renderHover(rows[2]));
  await act(async () => { await vi.advanceTimersByTimeAsync(500); });
  expect(screen.queryByText("First introduction")).not.toBeInTheDocument();
  expect(screen.queryByText("Second introduction")).not.toBeInTheDocument();
  expect(rows[2]).toHaveAttribute("data-hovered", "true");
});
