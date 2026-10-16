import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it } from "vitest";
import i18n from "../../i18n";
import { MarketplaceInstallProgress } from "../MarketplaceInstallProgress";

beforeEach(async () => { await i18n.changeLanguage("zh"); });

it("shows actual download percentage and bytes, then indeterminate dependency progress", () => {
  const view = render(<MarketplaceInstallProgress job={{ status: "downloading", stage: "downloading",
    size_bytes: 1048576, downloaded_bytes: 524288, elapsed_seconds: 12 }} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
  expect(screen.getByText("50%")).toBeInTheDocument();
  expect(screen.getByText("512.0 KB / 1.0 MB")).toBeInTheDocument();
  view.rerender(<MarketplaceInstallProgress job={{ status: "installing", stage: "dependency_downloading",
    current_dependency: "docxtpl", elapsed_seconds: 75 }} />);
  expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  expect(screen.queryByText(/\d+%/)).not.toBeInTheDocument();
  expect(screen.getByText("正在下载依赖…")).toBeInTheDocument();
  expect(screen.getByText("正在处理：docxtpl")).toBeInTheDocument();
  expect(screen.getByText("已用时 1:15")).toBeInTheDocument();
});

it.each(["installing", "verifying", "downloading"])("does not invent a percentage for %s without byte measurements", (status) => {
  render(<MarketplaceInstallProgress job={{ status }} />);
  expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  expect(screen.queryByText(/\d+%/)).not.toBeInTheDocument();
});

it("translates loading and elapsed time to English", async () => {
  await i18n.changeLanguage("en");
  render(<MarketplaceInstallProgress job={{ status: "installing", stage: "loading", elapsed_seconds: 123 }} />);
  expect(screen.getByText("Loading plugin…")).toBeInTheDocument();
  expect(screen.getByText("Elapsed 2:03")).toBeInTheDocument();
});
