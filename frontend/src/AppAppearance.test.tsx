import {fireEvent, render, screen} from "@testing-library/react";
import {beforeEach, describe, expect, it} from "vitest";
import {APP_THEME_STORAGE_KEY, AppAppearanceSettings, resolveAppTheme, useAppAppearance} from "./AppAppearance";

beforeEach(() => {
  const values = new Map<string, string>();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
      clear: () => values.clear(),
    },
  });
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: () => ({matches: false, addEventListener: () => undefined, removeEventListener: () => undefined}),
  });
  delete document.documentElement.dataset.appTheme;
  document.documentElement.style.colorScheme = "";
});

function Harness() {
  const appearance = useAppAppearance();
  return <AppAppearanceSettings preference={appearance.preference} resolvedTheme={appearance.resolvedTheme} onChange={appearance.setPreference} />;
}

describe("AppAppearance", () => {
  it("resolves System without coupling the EPUB reader preference", () => {
    expect(resolveAppTheme("system", false)).toBe("paper");
    expect(resolveAppTheme("system", true)).toBe("night");
    localStorage.setItem("waypoint:reader-preferences:v1", JSON.stringify({theme: "warm"}));

    render(<Harness />);
    fireEvent.click(screen.getByRole("radio", {name: /Night/}));

    expect(document.documentElement.dataset.appTheme).toBe("night");
    expect(localStorage.getItem(APP_THEME_STORAGE_KEY)).toBe("night");
    expect(localStorage.getItem("waypoint:reader-preferences:v1")).toBe(JSON.stringify({theme: "warm"}));
  });

  it("shows all four app-level choices and their current resolution", () => {
    render(<Harness />);
    expect(screen.getAllByRole("radio")).toHaveLength(4);
    expect(screen.getByText("Using paper")).toBeInTheDocument();
    expect(screen.getByRole("radio", {name: /System/})).toHaveAttribute("aria-checked", "true");
  });
});
