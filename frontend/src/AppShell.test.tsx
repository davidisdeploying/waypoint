import {render, screen} from "@testing-library/react";
import {createMemoryRouter, RouterProvider} from "react-router-dom";
import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import {describe, expect, it} from "vitest";
import {AppShell} from "./AppShell";

describe("AppShell", () => {
  it("renders the six primary product areas", () => {
    const router = createMemoryRouter([
      {path: "/", element: <AppShell />, children: [{index: true, element: <p>Home content</p>}]},
    ]);
    const queryClient = new QueryClient({defaultOptions: {queries: {staleTime: Infinity}}});
    queryClient.setQueryData(["daily-session"], {
      active: null,
      suggested: null,
      today: {minutes: 0, sessions: 0},
      recent: [],
    });
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    for (const label of ["Today", "Study", "Mastery", "Library", "Journey", "More"]) {
      expect(screen.getByRole("link", {name: label})).toBeInTheDocument();
    }
    expect(screen.queryByText(/preview/i)).not.toBeInTheDocument();
  });
});
